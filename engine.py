#!/usr/bin/env python3
"""
engine.py - optimal-play Yahtzee solver built as ONE parameterised dynamic program.

State
-----
    mask   13-bit set of filled boxes, bit i = Category i (scoring.Category order:
           0-5 Ones..Sixes, 6 3K, 7 4K, 8 FH, 9 SS, 10 LS, 11 Yahtzee, 12 Chance)
    upper  upper-section subtotal clamped to 63 (63 means "bonus secured")
    yb     1 if the Yahtzee box holds 50 (eligible for Yahtzee bonuses), else 0

Per turn the program works backwards through the three decisions:
    V3[roll]  best box to score the final roll in  (rules live in _fill_options)
    V2[roll]  best keep after the second roll        = max over keeps k <= roll of  T[k] . V3
    V1[roll]  best keep after the first roll         = max over keeps k <= roll of  T[k] . V2
    EV[state] = P . V1                                (P = distribution of the first roll)

T[k, r] is the probability of ending on roll r after keeping the multiset k (462 keeps x
252 rolls). It depends only on the keep, so it is stored once, not per (roll, keep) pair.

Two tables are produced for every rule set: EV (expected remaining score) and M2 (expected
square of the remaining score) under the SAME optimal policy, so std = sqrt(M2 - EV^2) is
exact for every state. The 35-point upper bonus is credited at the end of the game inside EV,
so EV[mask, 63, yb] already contains it. When two keeps are tied (values within TIE_TOL) the
policy takes the highest keep id, in the precompute and at runtime alike. Keep ids are ordered
by the number of dice kept, so a tie goes to the keep that rerolls the fewest dice (standing
pat wins a tie with a pointless reroll), and the keep the app recommends is exactly the keep
the M2 table assumed even though the two paths reach the values through different BLAS
routines.

Rule sets (Rules): the Yahtzee bonus amount, the Joker rule variant, and one house rule.
    HASBRO    official rules printed by Hasbro: a Yahtzee rolled when the Yahtzee box is
              already filled (50 or 0) MUST go in the matching upper box if open; else in an
              open lower box (FH 25, SS 30, LS 40, 3K/4K/Chance = sum); else as 0 in an open
              upper box. +100 only if the box holds 50.            fresh-game EV 254.5877
    VERHOEFF  the rule set behind the widely quoted 254.5896 (Verhoeff): no forcing; FH/SS/LS
              score in full only when both the Yahtzee box and the matching upper box are
              filled; otherwise any open box at normal scores.       fresh-game EV 254.5896
    PLAIN     no Yahtzee bonus, no Joker rule (extra Yahtzees score normally).  EV 245.8708
"""
import os
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")  # numba prange + BLAS: avoid oversubscription

import json
import math
import re
import sys
import time
from collections import OrderedDict
from dataclasses import dataclass, asdict
from fractions import Fraction
from math import factorial
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
from numba import njit, prange

from dice import enumerate_rolls, roll_id, dice_list_to_counts, counts_to_dice_list
from scoring import (
    CATEGORY_NAMES, UPPER_BONUS, UPPER_BONUS_THRESHOLD,
    get_score_table, get_joker_score_table,
)

# --------------------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------------------
NUM_CATS = 13
FULL_MASK = (1 << NUM_CATS) - 1
MAX_UPPER = 63
NUM_ROLLS = 252
NUM_KEEPS = 462
# Keep values closer than TIE_TOL are tied. Measured on the three shipped tables: cross-path float
# noise never exceeds 8.5e-14, and the smallest gap between genuinely different keeps is 4.4e-9.
TIE_TOL = 1e-10
YAHTZEE = 11
FULL_HOUSE = 8
LOWER_BOXES = (6, 7, 8, 9, 10, 12)          # lower section without the Yahtzee box
CATEGORY_MAX = (5, 10, 15, 20, 25, 30, 30, 30, 25, 30, 40, 50, 30)
TABLE_VERSION = 5

# yahtzee_status values used by the web UI / API
YAHTZEE_UNFILLED = 0
YAHTZEE_SCRATCHED = 1
YAHTZEE_SCORED = 2

JOKER_CODES = {"none": 0, "hasbro": 1, "verhoeff": 2}


@dataclass(frozen=True)
class Rules:
    yahtzee_bonus: int = 100          # points per additional Yahtzee while the box holds 50
    joker: str = "hasbro"             # "hasbro" | "verhoeff" | "none"
    natural_yahtzee_fh: bool = False  # house rule: a natural Yahtzee may score FH 25 while the box is open

    def __post_init__(self):
        if self.joker not in JOKER_CODES:
            raise ValueError(f"unknown joker rule {self.joker!r}; expected one of {sorted(JOKER_CODES)}")
        if self.yahtzee_bonus < 0:
            raise ValueError("yahtzee_bonus must be >= 0")

    @property
    def joker_code(self) -> int:
        return JOKER_CODES[self.joker]

    @property
    def key(self) -> str:
        if self == HASBRO:
            return "hasbro"
        if self == VERHOEFF:
            return "verhoeff"
        if self == PLAIN:
            return "plain"
        return f"custom_b{self.yahtzee_bonus}_{self.joker}_{'fh' if self.natural_yahtzee_fh else 'nofh'}"

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True)


HASBRO = Rules()
VERHOEFF = Rules(joker="verhoeff")
PLAIN = Rules(yahtzee_bonus=0, joker="none")
PRESETS = {"hasbro": HASBRO, "verhoeff": VERHOEFF, "plain": PLAIN}


# --------------------------------------------------------------------------------------
# Static tables: rolls, keeps, transition matrix, score tables
# --------------------------------------------------------------------------------------
def _compositions(n: int, k: int = 6) -> List[Tuple[int, ...]]:
    if k == 1:
        return [(n,)]
    out = []
    for i in range(n + 1):
        for rest in _compositions(n - i, k - 1):
            out.append((i,) + rest)
    return out


def _multinomial(counts: Sequence[int]) -> Fraction:
    n = sum(counts)
    ways = factorial(n)
    for c in counts:
        ways //= factorial(c)
    return Fraction(ways, 6 ** n)


class Tables:
    """All static arrays. Built once per process (about half a second)."""

    def __init__(self):
        rolls = [tuple(int(x) for x in r) for r in enumerate_rolls()]
        assert len(rolls) == NUM_ROLLS
        keeps = [c for n in range(6) for c in _compositions(n)]
        assert len(keeps) == NUM_KEEPS
        keep_id = {k: i for i, k in enumerate(keeps)}

        self.rolls = np.array(rolls, dtype=np.int64)
        self.keeps = np.array(keeps, dtype=np.int64)
        self.P = np.array([float(_multinomial(r)) for r in rolls])
        T = np.zeros((NUM_KEEPS, NUM_ROLLS))
        for ki, k in enumerate(keeps):
            for ri, r in enumerate(rolls):
                d = tuple(a - b for a, b in zip(r, k))
                if min(d) >= 0:
                    T[ki, ri] = float(_multinomial(d))
        self.T = T
        self.Tt = np.ascontiguousarray(T.T)
        # keeps that are sub-multisets of each roll, CSR layout, keep ids ascending
        ptr = [0]
        idx = []
        for r in rolls:
            ks = [ki for ki, k in enumerate(keeps) if all(a <= b for a, b in zip(k, r))]
            idx.extend(ks)
            ptr.append(len(idx))
        self.sub_ptr = np.array(ptr, dtype=np.int64)
        self.sub_idx = np.array(idx, dtype=np.int64)
        assert len(idx) == 4368
        self.keep_of_roll = np.array([keep_id[r] for r in rolls], dtype=np.int64)

        self.score = np.array(get_score_table(), dtype=np.int64)
        self.joker_score = np.asarray(get_joker_score_table(), dtype=np.int64)
        assert self.score.shape == (NUM_ROLLS, NUM_CATS) == self.joker_score.shape
        self.is_yz = self.score[:, YAHTZEE] == 50
        self.yz_face = np.where(self.is_yz, self.rolls.argmax(axis=1), -1).astype(np.int64)
        assert self.is_yz.sum() == 6


_TABLES: Optional[Tables] = None


def tables() -> Tables:
    global _TABLES
    if _TABLES is None:
        _TABLES = Tables()
    return _TABLES


# --------------------------------------------------------------------------------------
# The rules, in one place
# --------------------------------------------------------------------------------------
@njit(cache=True)
def _fill_options(joker_code, yahtzee_bonus, natural_fh, mask, yb, rid,
                  score, joker_score, is_yz, yz_face, legal, pts):
    """
    For one (state, final roll): which boxes may be used and what each scores.

    Fills legal[13] and pts[13]; returns the Yahtzee bonus earned this turn (0 or the bonus).
    This is the single implementation of the scoring rules used by the precompute, the
    runtime policy and the distribution code.
    """
    bonus = 0
    yz = is_yz[rid]
    yz_filled = (mask >> YAHTZEE) & 1
    for c in range(NUM_CATS):
        legal[c] = ((mask >> c) & 1) == 0
        pts[c] = score[rid, c]
    if not yz:
        return bonus
    if yb:
        bonus = yahtzee_bonus
    if not yz_filled:
        # Yahtzee box still open: score anywhere at normal values (50 in the Yahtzee box)
        if natural_fh:
            pts[FULL_HOUSE] = 25
        return bonus
    if joker_code == 0:
        return bonus
    f = yz_face[rid]
    face_open = ((mask >> f) & 1) == 0
    if joker_code == 1:
        # Hasbro Joker rule
        if face_open:
            for c in range(NUM_CATS):
                legal[c] = c == f
            return bonus
        lower_open = False
        for c in (6, 7, 8, 9, 10, 12):
            if ((mask >> c) & 1) == 0:
                lower_open = True
        if lower_open:
            for c in range(NUM_CATS):
                legal[c] = legal[c] and c >= 6 and c != YAHTZEE
                pts[c] = joker_score[rid, c]
        else:
            for c in range(6):
                pts[c] = 0           # only open upper boxes remain; they take a zero
        return bonus
    # Verhoeff variant: never forced; joker values only once the matching upper box is filled
    if not face_open:
        for c in range(NUM_CATS):
            pts[c] = joker_score[rid, c]
    return bonus


# --------------------------------------------------------------------------------------
# Precompute kernels
# --------------------------------------------------------------------------------------
@njit(cache=True)
def _turn_v3(joker_code, yahtzee_bonus, natural_fh, mask, yb,
             score, joker_score, is_yz, yz_face, EV, M2, v3, m3):
    """v3[u, r], m3[u, r] for every upper u (rows) and final roll r (cols)."""
    legal = np.zeros(NUM_CATS, np.bool_)
    pts = np.zeros(NUM_CATS, np.int64)
    for rid in range(NUM_ROLLS):
        bonus = _fill_options(joker_code, yahtzee_bonus, natural_fh, mask, yb, rid,
                              score, joker_score, is_yz, yz_face, legal, pts)
        for u in range(MAX_UPPER + 1):
            v3[u, rid] = -1e18
            m3[u, rid] = 0.0
        for c in range(NUM_CATS):
            if not legal[c]:
                continue
            new_mask = mask | (1 << c)
            new_yb = yb
            if c == YAHTZEE and is_yz[rid]:
                new_yb = 1
            p = float(pts[c] + bonus)
            for u in range(MAX_UPPER + 1):
                nu = u
                if c < 6:
                    nu = u + pts[c]
                    if nu > MAX_UPPER:
                        nu = MAX_UPPER
                evn = EV[new_mask, nu, new_yb]
                val = p + evn
                if val > v3[u, rid]:
                    v3[u, rid] = val
                    m3[u, rid] = p * p + 2.0 * p * evn + M2[new_mask, nu, new_yb]


@njit(cache=True)
def _max_over_subkeeps(E, F, sub_ptr, sub_idx, V, M):
    """
    V[u, r] = max over keeps k <= r of E[u, k]; M takes F at the keep the policy picks:
    the highest keep id within TIE_TOL of the maximum. sub_idx lists keep ids ascending and
    keep ids are ordered by dice kept, so a tie goes to the keep that rerolls the fewest dice.
    """
    for u in range(E.shape[0]):
        for r in range(NUM_ROLLS):
            best = -1e18
            for j in range(sub_ptr[r], sub_ptr[r + 1]):
                k = sub_idx[j]
                if E[u, k] > best:
                    best = E[u, k]
            bm = 0.0
            for j in range(sub_ptr[r + 1] - 1, sub_ptr[r] - 1, -1):
                k = sub_idx[j]
                if E[u, k] >= best - TIE_TOL:
                    bm = F[u, k]
                    break
            V[u, r] = best
            M[u, r] = bm


@njit(cache=True, parallel=True)
def _solve_level(masks, joker_code, yahtzee_bonus, natural_fh,
                 score, joker_score, is_yz, yz_face, Tt, P, sub_ptr, sub_idx, EV, M2):
    """Solve every (mask, upper, yb) for the masks given (all with the same popcount)."""
    for i in prange(masks.shape[0]):
        mask = masks[i]
        for yb in range(2):
            v3 = np.empty((MAX_UPPER + 1, NUM_ROLLS))
            m3 = np.empty((MAX_UPPER + 1, NUM_ROLLS))
            _turn_v3(joker_code, yahtzee_bonus, natural_fh, mask, yb,
                     score, joker_score, is_yz, yz_face, EV, M2, v3, m3)
            e2 = np.dot(v3, Tt)
            f2 = np.dot(m3, Tt)
            v2 = np.empty((MAX_UPPER + 1, NUM_ROLLS))
            m2 = np.empty((MAX_UPPER + 1, NUM_ROLLS))
            _max_over_subkeeps(e2, f2, sub_ptr, sub_idx, v2, m2)
            e1 = np.dot(v2, Tt)
            f1 = np.dot(m2, Tt)
            v1 = np.empty((MAX_UPPER + 1, NUM_ROLLS))
            m1 = np.empty((MAX_UPPER + 1, NUM_ROLLS))
            _max_over_subkeeps(e1, f1, sub_ptr, sub_idx, v1, m1)
            for u in range(MAX_UPPER + 1):
                s = 0.0
                s2 = 0.0
                for r in range(NUM_ROLLS):
                    s += P[r] * v1[u, r]
                    s2 += P[r] * m1[u, r]
                EV[mask, u, yb] = s
                M2[mask, u, yb] = s2


def compute_tables(rules: Rules, verbose: bool = False) -> Tuple[np.ndarray, np.ndarray]:
    """Run the full dynamic program. Returns (EV, M2), each shaped (8192, 64, 2)."""
    t = tables()
    EV = np.zeros((FULL_MASK + 1, MAX_UPPER + 1, 2))
    M2 = np.zeros_like(EV)
    EV[FULL_MASK, MAX_UPPER, :] = UPPER_BONUS
    M2[FULL_MASK, MAX_UPPER, :] = UPPER_BONUS ** 2
    levels: List[List[int]] = [[] for _ in range(NUM_CATS + 1)]
    for mask in range(FULL_MASK):
        levels[bin(mask).count("1")].append(mask)
    start = time.time()
    for n_filled in range(NUM_CATS - 1, -1, -1):
        masks = np.array(levels[n_filled], dtype=np.int64)
        _solve_level(masks, rules.joker_code, rules.yahtzee_bonus, int(rules.natural_yahtzee_fh),
                     t.score, t.joker_score, t.is_yz, t.yz_face, t.Tt, t.P,
                     t.sub_ptr, t.sub_idx, EV, M2)
        if verbose:
            print(f"  {NUM_CATS - n_filled:2d} boxes open: {len(masks):5d} masks done, "
                  f"{time.time() - start:6.1f}s elapsed", flush=True)
    return EV, M2


# --------------------------------------------------------------------------------------
# Runtime kernels (one state at a time)
# --------------------------------------------------------------------------------------
@njit(cache=True)
def _v3_single(joker_code, yahtzee_bonus, natural_fh, mask, upper, yb,
               score, joker_score, is_yz, yz_face, EV, out):
    legal = np.zeros(NUM_CATS, np.bool_)
    pts = np.zeros(NUM_CATS, np.int64)
    for rid in range(NUM_ROLLS):
        bonus = _fill_options(joker_code, yahtzee_bonus, natural_fh, mask, yb, rid,
                              score, joker_score, is_yz, yz_face, legal, pts)
        best = -1e18
        for c in range(NUM_CATS):
            if not legal[c]:
                continue
            new_mask = mask | (1 << c)
            new_yb = yb
            if c == YAHTZEE and is_yz[rid]:
                new_yb = 1
            nu = upper
            if c < 6:
                nu = upper + pts[c]
                if nu > MAX_UPPER:
                    nu = MAX_UPPER
            val = pts[c] + bonus + EV[new_mask, nu, new_yb]
            if val > best:
                best = val
        out[rid] = best


@njit(cache=True)
def _max_sub_1d(e, sub_ptr, sub_idx, out):
    for r in range(NUM_ROLLS):
        best = -1e18
        for j in range(sub_ptr[r], sub_ptr[r + 1]):
            k = sub_idx[j]
            if e[k] > best:
                best = e[k]
        out[r] = best


@njit(cache=True)
def _argmax_sub(e, r, sub_ptr, sub_idx):
    """The keep the policy picks for roll r: highest keep id within TIE_TOL of the best value."""
    best = -1e18
    for j in range(sub_ptr[r], sub_ptr[r + 1]):
        k = sub_idx[j]
        if e[k] > best:
            best = e[k]
    for j in range(sub_ptr[r + 1] - 1, sub_ptr[r] - 1, -1):
        k = sub_idx[j]
        if e[k] >= best - TIE_TOL:
            return k
    return -1


# --------------------------------------------------------------------------------------
# State helpers and input validation
# --------------------------------------------------------------------------------------
def popcount(mask: int) -> int:
    return bin(mask).count("1")


def canonical_yb(mask: int, yahtzee_status: int) -> int:
    """yb is 1 only when the Yahtzee box is filled AND holds 50."""
    if yahtzee_status not in (YAHTZEE_UNFILLED, YAHTZEE_SCRATCHED, YAHTZEE_SCORED):
        raise ValueError("yahtzee_status must be 0 (unfilled), 1 (scratched) or 2 (scored 50)")
    return 1 if ((mask >> YAHTZEE) & 1) and yahtzee_status == YAHTZEE_SCORED else 0


def yahtzee_status_of(mask: int, yb: int) -> int:
    if not (mask >> YAHTZEE) & 1:
        return YAHTZEE_UNFILLED
    return YAHTZEE_SCORED if yb else YAHTZEE_SCRATCHED


def allowed_scores(cat: int) -> frozenset:
    if cat < 6:
        return frozenset((cat + 1) * k for k in range(6))
    if cat in (6, 7, 12):
        return frozenset([0] + list(range(5, 31)))
    return {8: frozenset((0, 25)), 9: frozenset((0, 30)), 10: frozenset((0, 40)),
            11: frozenset((0, 50))}[cat]


def parse_dice(dice) -> List[int]:
    if not isinstance(dice, (list, tuple)) or len(dice) != 5:
        raise ValueError("dice must be a list of 5 values")
    out = []
    for d in dice:
        if isinstance(d, bool) or not isinstance(d, int) or not 1 <= d <= 6:
            raise ValueError("each die must be an integer from 1 to 6")
        out.append(int(d))
    return out


def parse_rolls_remaining(x) -> int:
    if isinstance(x, bool) or not isinstance(x, int) or x not in (0, 1, 2):
        raise ValueError("rolls_remaining must be 0, 1 or 2")
    return int(x)


@dataclass(frozen=True)
class ScoreState:
    mask: int
    upper: int            # clamped to 63
    upper_raw: int        # actual upper subtotal
    yb: int
    yahtzee_status: int
    filled: Tuple[int, ...]
    locked: int           # sum of box scores, without the 35 upper bonus
    upper_bonus_earned: int

    @property
    def open_boxes(self) -> List[int]:
        return [c for c in range(NUM_CATS) if not (self.mask >> c) & 1]

    @property
    def boxes_remaining(self) -> int:
        return NUM_CATS - len(self.filled)


def parse_scorecard(scores) -> ScoreState:
    """
    Validate a scorecard {category_index: points or None} and derive the solver state.
    Category keys may be ints or numeric strings. Raises ValueError on anything impossible.
    """
    if scores is None:
        scores = {}
    if not isinstance(scores, dict):
        raise ValueError("scores must be an object mapping category index to points")
    filled: Dict[int, int] = {}
    for k, v in scores.items():
        if v is None or k in ("undefined", "null", ""):
            continue
        if isinstance(k, str) and re.fullmatch(r"\d{1,2}", k):
            cat = int(k)
        elif isinstance(k, int) and not isinstance(k, bool):
            cat = k
        else:
            raise ValueError(f"invalid category key {k!r}")
        if not 0 <= cat < NUM_CATS:
            raise ValueError(f"category index {cat} out of range")
        if isinstance(v, bool) or not isinstance(v, int):
            if isinstance(v, float) and v.is_integer():
                v = int(v)
            else:
                raise ValueError(f"score for {CATEGORY_NAMES[cat]} must be an integer")
        if v not in allowed_scores(cat):
            raise ValueError(f"{v} is not a possible score for {CATEGORY_NAMES[cat]}")
        filled[cat] = int(v)
    mask = 0
    for cat in filled:
        mask |= 1 << cat
    upper_raw = sum(v for c, v in filled.items() if c < 6)
    upper = min(upper_raw, MAX_UPPER)
    if YAHTZEE in filled:
        status = YAHTZEE_SCORED if filled[YAHTZEE] == 50 else YAHTZEE_SCRATCHED
    else:
        status = YAHTZEE_UNFILLED
    yb = canonical_yb(mask, status)
    return ScoreState(
        mask=mask, upper=upper, upper_raw=upper_raw, yb=yb, yahtzee_status=status,
        filled=tuple(sorted(filled)), locked=sum(filled.values()),
        upper_bonus_earned=UPPER_BONUS if upper_raw >= UPPER_BONUS_THRESHOLD else 0,
    )


def max_remaining(rules: Rules, mask: int, upper: int, yb: int) -> int:
    """Upper bound on the remaining score (bonus included) from a state."""
    open_boxes = [c for c in range(NUM_CATS) if not (mask >> c) & 1]
    total = sum(CATEGORY_MAX[c] for c in open_boxes)
    up_gain = sum(CATEGORY_MAX[c] for c in open_boxes if c < 6)
    if upper >= UPPER_BONUS_THRESHOLD or upper + up_gain >= UPPER_BONUS_THRESHOLD:
        total += UPPER_BONUS
    if rules.yahtzee_bonus > 0:
        n = len(open_boxes)
        if yb:
            total += rules.yahtzee_bonus * n
        elif not (mask >> YAHTZEE) & 1:
            total += rules.yahtzee_bonus * max(0, n - 1)
    return total


# --------------------------------------------------------------------------------------
# Solver
# --------------------------------------------------------------------------------------
DEFAULT_TABLE_DIR = Path(__file__).resolve().parent / "tables"


class Solver:
    """Loads (or builds) the tables for one rule set and answers policy questions."""

    def __init__(self, rules: Rules = HASBRO, table_dir: Optional[Path] = None,
                 build_if_missing: bool = True, verbose: bool = True, cache_states: int = 4096):
        self.rules = rules
        self.t = tables()
        self.table_dir = Path(table_dir) if table_dir else DEFAULT_TABLE_DIR
        self.path = self.table_dir / f"ev_{rules.key}.npz"
        self._turn_cache: "OrderedDict[Tuple[int, int, int], dict]" = OrderedDict()
        self._cache_states = cache_states
        loaded = self._load()
        if not loaded:
            if not build_if_missing:
                raise FileNotFoundError(f"no usable table at {self.path}")
            if verbose:
                print(f"Building tables for rules {rules.key} (a few seconds)...", flush=True)
            self.EV, self.M2 = compute_tables(rules, verbose=verbose)
            self.save()
        self.fresh_ev = float(self.EV[0, 0, 0])

    # ----- persistence -----
    def _load(self) -> bool:
        if not self.path.exists() or self.path.stat().st_size < 1000:   # LFS pointer or missing
            return False
        try:
            with np.load(self.path) as z:
                meta = json.loads(str(z["meta"]))
                if meta.get("version") != TABLE_VERSION or meta.get("rules") != self.rules.to_json():
                    return False
                self.EV = z["EV"]
                self.M2 = z["M2"]
        except Exception:
            return False
        return self.EV.shape == (FULL_MASK + 1, MAX_UPPER + 1, 2) and self.M2.shape == self.EV.shape

    def save(self):
        self.table_dir.mkdir(parents=True, exist_ok=True)
        meta = {"version": TABLE_VERSION, "rules": self.rules.to_json(), "rules_key": self.rules.key,
                "fresh_ev": float(self.EV[0, 0, 0]), "fresh_std": float(self.std(0, 0, 0))}
        np.savez_compressed(self.path, EV=self.EV, M2=self.M2, meta=np.array(json.dumps(meta)))

    # ----- table lookups -----
    def _check(self, mask: int, upper: int, yb: int):
        if not 0 <= mask <= FULL_MASK:
            raise ValueError("mask out of range")
        if not 0 <= upper <= MAX_UPPER:
            raise ValueError("upper must be between 0 and 63")
        if yb not in (0, 1):
            raise ValueError("yb must be 0 or 1")
        if yb == 1 and not (mask >> YAHTZEE) & 1:
            raise ValueError("yb can only be 1 when the Yahtzee box is filled (with 50)")

    def ev(self, mask: int, upper: int, yb: int) -> float:
        self._check(mask, upper, yb)
        return float(self.EV[mask, upper, yb])

    def variance(self, mask: int, upper: int, yb: int) -> float:
        self._check(mask, upper, yb)
        e = float(self.EV[mask, upper, yb])
        return max(0.0, float(self.M2[mask, upper, yb]) - e * e)

    def std(self, mask: int, upper: int, yb: int) -> float:
        return math.sqrt(self.variance(mask, upper, yb))

    def ev_status(self, mask: int, upper: int, yahtzee_status: int) -> float:
        return self.ev(mask, upper, canonical_yb(mask, yahtzee_status))

    # ----- per-state turn arrays -----
    def turn(self, mask: int, upper: int, yb: int) -> dict:
        """v1, v2, v3 over the 252 rolls and e1, e2 over the 462 keeps for one state."""
        self._check(mask, upper, yb)
        if mask == FULL_MASK:
            raise ValueError("game is over: every box is filled")
        key = (mask, upper, yb)
        hit = self._turn_cache.get(key)
        if hit is not None:
            self._turn_cache.move_to_end(key)
            return hit
        t = self.t
        r = self.rules
        v3 = np.empty(NUM_ROLLS)
        _v3_single(r.joker_code, r.yahtzee_bonus, int(r.natural_yahtzee_fh), mask, upper, yb,
                   t.score, t.joker_score, t.is_yz, t.yz_face, self.EV, v3)
        e2 = t.T @ v3
        v2 = np.empty(NUM_ROLLS)
        _max_sub_1d(e2, t.sub_ptr, t.sub_idx, v2)
        e1 = t.T @ v2
        v1 = np.empty(NUM_ROLLS)
        _max_sub_1d(e1, t.sub_ptr, t.sub_idx, v1)
        out = {"v1": v1, "v2": v2, "v3": v3, "e1": e1, "e2": e2}
        self._turn_cache[key] = out
        if len(self._turn_cache) > self._cache_states:
            self._turn_cache.popitem(last=False)
        return out

    def turn_ev(self, mask: int, upper: int, yb: int) -> float:
        """Expectation of v1 over the first roll; equals EV[mask, upper, yb] (consistency check)."""
        return float(self.t.P @ self.turn(mask, upper, yb)["v1"])

    # ----- decisions -----
    def options(self, mask: int, upper: int, yb: int, rid: int):
        """(legal[13], pts[13], bonus) for one final roll under this rule set."""
        self._check(mask, upper, yb)
        t = self.t
        r = self.rules
        legal = np.zeros(NUM_CATS, np.bool_)
        pts = np.zeros(NUM_CATS, np.int64)
        bonus = _fill_options(r.joker_code, r.yahtzee_bonus, int(r.natural_yahtzee_fh), mask, yb, rid,
                              t.score, t.joker_score, t.is_yz, t.yz_face, legal, pts)
        return legal, pts, int(bonus)

    def joker_situation(self, mask: int, yb: int, rid: int) -> Optional[str]:
        """
        How the Joker rule applies to this final roll:
        None (not a Yahtzee, or Yahtzee box open, or rule off), 'forced_upper', 'lower_only',
        'zero_upper' (Hasbro) or 'joker' (Verhoeff variant, joker values available).
        """
        t = self.t
        if not t.is_yz[rid] or not (mask >> YAHTZEE) & 1 or self.rules.joker == "none":
            return None
        f = int(t.yz_face[rid])
        face_open = not (mask >> f) & 1
        if self.rules.joker == "hasbro":
            if face_open:
                return "forced_upper"
            if any(not (mask >> c) & 1 for c in LOWER_BOXES):
                return "lower_only"
            return "zero_upper"
        return None if face_open else "joker"

    def category_options(self, mask: int, upper: int, yb: int, rid: int) -> List[dict]:
        """Every legal box for this final roll with immediate points and total EV, best first."""
        self._check(mask, upper, yb)
        if mask == FULL_MASK:
            raise ValueError("game is over: every box is filled")
        legal, pts, bonus = self.options(mask, upper, yb, rid)
        situation = self.joker_situation(mask, yb, rid)
        is_yz = bool(self.t.is_yz[rid])
        out = []
        for c in range(NUM_CATS):
            if not legal[c]:
                continue
            p = int(pts[c])
            new_mask = mask | (1 << c)
            new_yb = 1 if (c == YAHTZEE and is_yz) else yb
            new_upper = min(MAX_UPPER, upper + p) if c < 6 else upper
            future = float(self.EV[new_mask, new_upper, new_yb])
            out.append({
                "category": c,
                "name": CATEGORY_NAMES[c],
                "points": p,
                "bonus": bonus,
                "expected_value": p + bonus + future,
                "is_forced": situation == "forced_upper",
            })
        out.sort(key=lambda o: -o["expected_value"])   # stable: lowest index wins ties
        return out

    def best_category(self, mask: int, upper: int, yb: int, rid: int) -> dict:
        return self.category_options(mask, upper, yb, rid)[0]

    def best_keep(self, mask: int, upper: int, yb: int, rid: int, rolls_remaining: int) -> Tuple[Tuple[int, ...], float]:
        """Optimal keep (as face counts) and the expected value after making it."""
        if rolls_remaining not in (1, 2):
            raise ValueError("best_keep needs rolls_remaining 1 or 2")
        tv = self.turn(mask, upper, yb)
        target = tv["e1"] if rolls_remaining == 2 else tv["e2"]
        k = int(_argmax_sub(target, rid, self.t.sub_ptr, self.t.sub_idx))
        return tuple(int(x) for x in self.t.keeps[k]), float(target[k])

    def roll_ev(self, mask: int, upper: int, yb: int, rid: int, rolls_remaining: int) -> float:
        """Expected final total from this roll onward under optimal play."""
        tv = self.turn(mask, upper, yb)
        return float({2: tv["v1"], 1: tv["v2"], 0: tv["v3"]}[rolls_remaining][rid])

    # ----- the API-facing recommendation -----
    def recommend(self, dice: Sequence[int], mask: int, upper: int, yahtzee_status: int,
                  rolls_remaining: int) -> dict:
        dice = parse_dice(dice)
        rolls_remaining = parse_rolls_remaining(rolls_remaining)
        yb = canonical_yb(mask, yahtzee_status)
        self._check(mask, upper, yb)
        if mask == FULL_MASK:
            raise ValueError("game is over: every box is filled")
        counts = dice_list_to_counts(dice)
        rid = roll_id(counts)
        is_yz = bool(self.t.is_yz[rid])
        situation = self.joker_situation(mask, yb, rid)
        options = self.category_options(mask, upper, yb, rid)
        bonus = options[0]["bonus"]
        forced = options[0]["category"] if situation == "forced_upper" else None
        res = {
            "dice": dice,
            "mask": mask,
            "upper": upper,
            "rolls_remaining": rolls_remaining,
            "mode": "joker" if self.rules.joker != "none" else "traditional",
            "rules": self.rules.key,
            "yahtzee_status": yahtzee_status_of(mask, yb),
            "is_yahtzee_roll": is_yz,
            "joker_bonus_available": bool(is_yz and yb and self.rules.yahtzee_bonus > 0),
            "joker_rule": situation,
            "forced_category": forced,
            "forced_category_name": CATEGORY_NAMES[forced] if forced is not None else None,
            "category_options": options,
        }
        if bonus:
            res["joker_bonus"] = bonus
        if rolls_remaining == 0:
            best = options[0]
            res.update(action="score", category=best["category"], category_name=best["name"],
                       points=best["points"], expected_value=best["expected_value"])
        else:
            keep, keep_ev = self.best_keep(mask, upper, yb, rid, rolls_remaining)
            res.update(action="keep", keep_counts=keep, keep_dice=counts_to_dice_list(keep),
                       keep_all=(sum(keep) == 5), keep_expected_value=keep_ev,
                       expected_value=self.roll_ev(mask, upper, yb, rid, rolls_remaining))
        return res

    # ----- how confident is this recommendation? -----
    def decision_report(self, mask: int, upper: int, yb: int, rid: int, rolls_remaining: int) -> dict:
        """
        Compare the recommended play with every alternative at this roll.

        The values come from a fully solved table (exact under the rule set and verified against an
        independent solver at every reachable state), so the question is never "is the number right"
        but "how much does the choice matter". gap = best play minus runner-up in expected final
        points; the label bands are in CONFIDENCE_BANDS. exact_tie marks a runner-up within TIE_TOL,
        where the tie-break (fewest dice rerolled, then lowest box) decided.
        """
        self._check(mask, upper, yb)
        rolls_remaining = parse_rolls_remaining(rolls_remaining)
        t = self.t
        if rolls_remaining == 0:
            options = self.category_options(mask, upper, yb, rid)
            cands = [{"play": f"score {o['name']}", "expected_value": float(o["expected_value"])} for o in options]
            kind = "box"
        else:
            tv = self.turn(mask, upper, yb)
            target = tv["e1"] if rolls_remaining == 2 else tv["e2"]
            best_k = int(_argmax_sub(target, rid, t.sub_ptr, t.sub_idx))
            ks = [int(k) for k in t.sub_idx[t.sub_ptr[rid]:t.sub_ptr[rid + 1]]]
            ks.sort(key=lambda k: (k != best_k, -float(target[k]), -k))
            cands = []
            for k in ks:
                kept = counts_to_dice_list(tuple(int(x) for x in t.keeps[k]))
                name = "stand pat" if len(kept) == 5 else ("reroll everything" if not kept else "keep " + " ".join(map(str, kept)))
                cands.append({"play": name, "expected_value": float(target[k])})
            kind = "keep"
        best = cands[0]
        runner = cands[1] if len(cands) > 1 else None
        gap = (best["expected_value"] - runner["expected_value"]) if runner else None
        key, headline = confidence_label(gap)
        near = sum(1 for c in cands[1:] if best["expected_value"] - c["expected_value"] < 0.25)
        alternatives = [{"play": c["play"], "loss": best["expected_value"] - c["expected_value"]} for c in cands[1:4]]
        report = {
            "solved": "exact",
            "basis": "Exact optimal-play table for this rule set, checked against an independent solver at every state.",
            "decision": kind,
            "label": key,
            "headline": headline,
            "gap": gap,
            "best": best["play"],
            "runner_up": runner["play"] if runner else None,
            "alternatives": alternatives,
            "near_ties": near,
            "exact_tie": bool(runner and gap <= TIE_TOL),
            "outcome_std": self.std(mask, upper, yb),
        }
        if report["exact_tie"]:
            report["tie_note"] = ("Exactly tied with " + runner["play"] +
                                  "; the tie went to the play that rerolls fewer dice" if kind == "keep"
                                  else "Exactly tied with " + runner["play"] + "; the tie went to the earlier box")
        return report

    # ----- Monte Carlo sanity check -----
    def _roll_lut(self) -> np.ndarray:
        lut = getattr(self.t, "_enc_lut", None)
        if lut is None:
            pow6 = 6 ** np.arange(6)
            lut = np.full(6 ** 6, -1, np.int64)
            lut[(self.t.rolls * pow6).sum(axis=1)] = np.arange(NUM_ROLLS)
            self.t._enc_lut = lut
        return lut

    def _policy_vectors(self, mask: int, upper: int, yb: int):
        key = (mask, upper, yb)
        cache = self.__dict__.setdefault("_policy_cache", OrderedDict())
        hit = cache.get(key)
        if hit is not None:
            cache.move_to_end(key)
            return hit
        tv = self.turn(mask, upper, yb)
        t = self.t
        r = self.rules
        keep1 = np.empty(NUM_ROLLS, np.int64)
        keep2 = np.empty(NUM_ROLLS, np.int64)
        gain = np.zeros(NUM_ROLLS, np.int64)
        nmask = np.empty(NUM_ROLLS, np.int64)
        nupper = np.empty(NUM_ROLLS, np.int64)
        nyb = np.empty(NUM_ROLLS, np.int64)
        _policy_vectors(r.joker_code, r.yahtzee_bonus, int(r.natural_yahtzee_fh), mask, upper, yb,
                        t.score, t.joker_score, t.is_yz, t.yz_face, self.EV, tv["e1"], tv["e2"],
                        t.sub_ptr, t.sub_idx, keep1, keep2, gain, nmask, nupper, nyb)
        vecs = (keep1, keep2, gain, nmask, nupper, nyb)
        cache[key] = vecs
        if len(cache) > 4096:
            cache.popitem(last=False)
        return vecs

    def simulate(self, mask: int, upper: int, yb: int, games: int = 2000, seed: Optional[int] = None) -> dict:
        """
        Play `games` games from this state with the table policy and random dice, and compare the
        sample mean of the remaining score with the table EV. A sanity check, not a proof: the
        table is exact, so |z| should look like a standard normal draw.
        """
        self._check(mask, upper, yb)
        games = int(games)
        if games < 1:
            raise ValueError("games must be at least 1")
        rng = np.random.default_rng(seed)
        t = self.t
        lut = self._roll_lut()
        pow6 = 6 ** np.arange(6)
        faces = np.arange(6)
        cols = np.arange(5)
        n = games
        g_mask = np.full(n, mask, np.int64)
        g_upper = np.full(n, upper, np.int64)
        g_yb = np.full(n, yb, np.int64)
        g_score = np.zeros(n, np.float64)

        def roll_counts(kept_counts: np.ndarray) -> np.ndarray:
            m = 5 - kept_counts.sum(axis=1)
            rolled = rng.integers(0, 6, size=(n, 5))
            active = cols[None, :] < m[:, None]
            onehot = (rolled[:, :, None] == faces[None, None, :]) & active[:, :, None]
            return kept_counts + onehot.sum(axis=1)

        for _ in range(NUM_CATS - popcount(mask)):
            keys = g_mask * 128 + g_upper * 2 + g_yb
            uniq, inv = np.unique(keys, return_inverse=True)
            vec_list = [self._policy_vectors(int(k) >> 7, (int(k) >> 1) & 63, int(k) & 1) for k in uniq]
            K1 = np.stack([v[0] for v in vec_list])
            K2 = np.stack([v[1] for v in vec_list])
            GAIN = np.stack([v[2] for v in vec_list])
            NM = np.stack([v[3] for v in vec_list])
            NU = np.stack([v[4] for v in vec_list])
            NY = np.stack([v[5] for v in vec_list])
            counts = roll_counts(np.zeros((n, 6), np.int64))
            rid = lut[counts @ pow6]
            counts = roll_counts(t.keeps[K1[inv, rid]])
            rid = lut[counts @ pow6]
            counts = roll_counts(t.keeps[K2[inv, rid]])
            rid = lut[counts @ pow6]
            g_score += GAIN[inv, rid]
            g_mask = NM[inv, rid]
            g_upper = NU[inv, rid]
            g_yb = NY[inv, rid]
        g_score += np.where(g_upper >= UPPER_BONUS_THRESHOLD, UPPER_BONUS, 0)
        ev = self.ev(mask, upper, yb)
        table_std = self.std(mask, upper, yb)
        mean = float(g_score.mean())
        sd = float(g_score.std(ddof=1)) if n > 1 else 0.0
        se = sd / math.sqrt(n) if n > 1 else float("nan")
        z = (mean - ev) / se if se and se > 0 else 0.0
        return {
            "games": n,
            "seed": seed,
            "mean": mean,
            "std": sd,
            "se": se,
            "table_ev": ev,
            "table_std": table_std,
            "z": z,
            "consistent": abs(z) < 3.0,
            "p5": float(np.percentile(g_score, 5)),
            "p50": float(np.percentile(g_score, 50)),
            "p95": float(np.percentile(g_score, 95)),
            "min": float(g_score.min()),
            "max": float(g_score.max()),
        }




# --------------------------------------------------------------------------------------
# Policy vectors for simulation (one call per state: what the policy does for every roll)
# --------------------------------------------------------------------------------------
@njit(cache=True)
def _policy_vectors(joker_code, yahtzee_bonus, natural_fh, mask, upper, yb,
                    score, joker_score, is_yz, yz_face, EV, e1, e2, sub_ptr, sub_idx,
                    keep1, keep2, gain, nmask, nupper, nyb):
    """For every roll r: the keep after roll 1, the keep after roll 2, and for a final roll the
    points gained (bonus included) and the successor state, all under the table policy."""
    for r in range(NUM_ROLLS):
        keep1[r] = _argmax_sub(e1, r, sub_ptr, sub_idx)
        keep2[r] = _argmax_sub(e2, r, sub_ptr, sub_idx)
    legal = np.zeros(NUM_CATS, np.bool_)
    pts = np.zeros(NUM_CATS, np.int64)
    for r in range(NUM_ROLLS):
        bonus = _fill_options(joker_code, yahtzee_bonus, natural_fh, mask, yb, r,
                              score, joker_score, is_yz, yz_face, legal, pts)
        best = -1e18
        for c in range(NUM_CATS):
            if not legal[c]:
                continue
            nm = mask | (1 << c)
            ny = yb
            if c == YAHTZEE and is_yz[r]:
                ny = 1
            nu = upper
            if c < 6:
                nu = upper + pts[c]
                if nu > MAX_UPPER:
                    nu = MAX_UPPER
            val = pts[c] + bonus + EV[nm, nu, ny]
            if val > best:
                best = val
                gain[r] = pts[c] + bonus
                nmask[r] = nm
                nupper[r] = nu
                nyb[r] = ny


# Decision confidence: how far the best play is ahead of the runner-up, in expected final points
CONFIDENCE_BANDS = (
    (3.0, "clear", "Clear choice"),
    (1.0, "solid", "Solid choice"),
    (0.25, "close", "Close call"),
    (0.0, "toss-up", "Toss-up: the top plays are equally good"),
)


def confidence_label(gap: Optional[float]) -> Tuple[str, str]:
    if gap is None:
        return "forced", "Forced: only one legal play"
    for threshold, key, text in CONFIDENCE_BANDS:
        if gap >= threshold:
            return key, text
    return "toss-up", CONFIDENCE_BANDS[-1][2]


# --------------------------------------------------------------------------------------
# Command line: build / inspect tables
# --------------------------------------------------------------------------------------
def _main(argv: List[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Yahtzee solver tables")
    ap.add_argument("command", choices=["precompute", "info"])
    ap.add_argument("--rules", default="hasbro", choices=sorted(PRESETS))
    ap.add_argument("--force", action="store_true", help="rebuild even if a table exists")
    ap.add_argument("--table-dir", default=None)
    a = ap.parse_args(argv)
    rules = PRESETS[a.rules]
    table_dir = Path(a.table_dir) if a.table_dir else DEFAULT_TABLE_DIR
    if a.command == "precompute":
        path = table_dir / f"ev_{rules.key}.npz"
        if a.force and path.exists():
            path.unlink()
        start = time.time()
        s = Solver(rules, table_dir=table_dir, verbose=True)
        print(f"rules={rules.key}  fresh EV={s.fresh_ev:.6f}  std={s.std(0, 0, 0):.4f}  "
              f"table={s.path}  ({time.time() - start:.1f}s)")
        return 0
    s = Solver(rules, table_dir=table_dir, build_if_missing=False, verbose=False)
    print(f"rules={rules.key}  fresh EV={s.fresh_ev:.6f}  std={s.std(0, 0, 0):.4f}  table={s.path}")
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
