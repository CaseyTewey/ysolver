"""Clean-room optimal-EV Yahtzee solver, kept independent of engine.py as a reference.

Written separately from the engine (dense numpy float64, no numba). The tests compare the
engine's tables against solve_reference(preset) at every reachable state.

State: (mask 13 bits, upper 0..63 clamped, yb = Yahtzee box holds 50).
Category order (from repo scoring.py): 0-5 Ones..Sixes, 6 3K, 7 4K, 8 FH, 9 SS, 10 LS, 11 Yahtzee, 12 Chance.
Roll order: compositions of 5 into 6 parts, lexicographic in count of face 1 first (matches repo dice.py).

Presets (solve_reference):
    hasbro    mode 'strict' with the default rule flags        fresh EV 254.587729
    verhoeff  mode 'strict', forced_upper=False,
              joker_scores_need_upper_filled=True, zero_upper_ok=True   fresh EV 254.589609
    plain     mode 'plain' (no bonus, no Joker), yb plane duplicated  fresh EV 245.870775

Each solve takes one to three minutes and is cached per process. Set YSOLVER_REF_CACHE to a
directory to also keep the solved arrays on disk between runs (ref_<preset>.npy).
"""
import os
import time
from math import factorial
from pathlib import Path
from typing import Dict, Optional

import numpy as np

NAMES = ["Ones", "Twos", "Threes", "Fours", "Fives", "Sixes", "3K", "4K", "FH", "SS", "LS", "Yahtzee", "Chance"]
YZ = 11
UPPER = list(range(6))
LOWER_JOKER = [6, 7, 8, 9, 10, 12]


def compositions(n, k=6):
    if k == 1:
        return [(n,)]
    out = []
    for i in range(n + 1):
        for rest in compositions(n - i, k - 1):
            out.append((i,) + rest)
    return out


def multinom_prob(x):
    r = sum(x)
    c = factorial(r)
    for v in x:
        c //= factorial(v)
    return c / 6 ** r


def build_tables():
    rolls = compositions(5, 6)  # 252
    keeps = []
    for n in range(6):
        keeps.extend(compositions(n, 6))  # 462 total
    R = np.array(rolls, dtype=np.int64)
    K = np.array(keeps, dtype=np.int64)
    keep_id = {k: i for i, k in enumerate(keeps)}
    P = np.array([multinom_prob(r) for r in rolls])
    assert abs(P.sum() - 1) < 1e-12
    # T[keep, roll]
    T = np.zeros((len(keeps), len(rolls)))
    for ki, k in enumerate(keeps):
        for ri, r in enumerate(rolls):
            d = tuple(a - b for a, b in zip(r, k))
            if min(d) >= 0:
                T[ki, ri] = multinom_prob(d)
    assert np.allclose(T.sum(axis=1), 1)
    # lattice edges for max over sub-multisets: for each size s>=1, (child, parent=child-e_f)
    edges = []  # list per size of (children, parents) arrays
    for s in range(1, 6):
        ch, pa = [], []
        for ki, k in enumerate(keeps):
            if sum(k) != s:
                continue
            for f in range(6):
                if k[f] > 0:
                    p = list(k); p[f] -= 1
                    ch.append(ki); pa.append(keep_id[tuple(p)])
        edges.append((np.array(ch), np.array(pa)))
    roll_as_keep = np.array([keep_id[r] for r in rolls])
    return rolls, keeps, R, K, P, T, edges, roll_as_keep


def max_over_subkeeps(E, edges, roll_as_keep):
    """V[r] = max over keeps k <= r of E[k]; E shape (462, C)."""
    W = E.copy()
    for ch, pa in edges:
        # parents of size s-1 are already final (W over all subsets) when we process size s
        np.maximum.at(W, ch, W[pa])
    return W[roll_as_keep]


def score_tables(R, mode):
    """Return normal score table (252,13), joker score table (252,13), is_yz, yz_face(0-5)."""
    n = len(R)
    faces = np.arange(1, 7)
    total = (R * faces).sum(axis=1)
    sc = np.zeros((n, 13), dtype=np.int64)
    for c in range(6):
        sc[:, c] = R[:, c] * (c + 1)
    mx = R.max(axis=1)
    sc[:, 6] = np.where(mx >= 3, total, 0)
    sc[:, 7] = np.where(mx >= 4, total, 0)
    is_fh = np.array([sorted(r)[-2:] == [2, 3] for r in R])
    sc[:, 8] = np.where(is_fh, 25, 0)
    present = R > 0
    def has_run(p, L):
        return any(all(p[i + j] for j in range(L)) for i in range(0, 7 - L))
    ss = np.array([has_run(p, 4) for p in present])
    ls = np.array([has_run(p, 5) for p in present])
    sc[:, 9] = np.where(ss, 30, 0)
    sc[:, 10] = np.where(ls, 40, 0)
    is_yz = mx == 5
    sc[:, 11] = np.where(is_yz, 50, 0)
    sc[:, 12] = total
    if mode == "fh":
        sc[is_yz, 8] = 25
    if mode == "natjoker":
        sc[is_yz, 8] = 25; sc[is_yz, 9] = 30; sc[is_yz, 10] = 40
    jsc = sc.copy()
    jsc[is_yz, 8] = 25
    jsc[is_yz, 9] = 30
    jsc[is_yz, 10] = 40
    yz_face = np.where(is_yz, R.argmax(axis=1), -1)
    return sc, jsc, is_yz, yz_face


def solve(mode, rules=None):
    rules = {**dict(forced_upper=True, zero_upper_ok=False, joker_when_scratched=True, joker_scores_need_upper_filled=False, natural_yz_joker_scores=False), **(rules or {})}
    """mode: 'strict' (official), 'fh' (natural Yahtzee also = FH 25 when Yahtzee box open), 'plain' (no bonus, no joker)."""
    t0 = time.time()
    rolls, keeps, R, K, P, T, edges, roll_as_keep = build_tables()
    sc, jsc, is_yz, yz_face = score_tables(R, mode)
    NR = 252
    up_col = np.repeat(np.arange(64), 2)  # col = upper*2 + yb
    yb_col = np.tile(np.arange(2), 64)
    V = np.zeros((8192, 64, 2))
    FULL = (1 << 13) - 1
    V[FULL, 63, :] = 35.0
    bonus_yz = mode != "plain"
    joker = mode != "plain"
    masks = sorted(range(FULL), key=lambda m: -bin(m).count("1"))
    for mask in masks:
        open_boxes = [c for c in range(13) if not (mask >> c) & 1]
        yz_filled = bool((mask >> YZ) & 1)
        best = np.full((NR, 128), -np.inf)
        # joker legality per roll for yahtzee rolls when yahtzee box filled
        if joker and yz_filled:
            # per yahtzee roll: forced upper open? else lower open? else upper zero
            forced_upper = np.full(NR, -1, dtype=np.int64)
            lower_open_any = any(c in open_boxes for c in LOWER_JOKER)
            for r in np.nonzero(is_yz)[0]:
                f = yz_face[r]
                if f in open_boxes:
                    forced_upper[r] = f
        for c in open_boxes:
            succ = V[mask | (1 << c)]  # (64,2)
            if joker and yz_filled:
                use_sc = np.where(is_yz[:, None], jsc, sc)[:, c]
            else:
                use_sc = sc[:, c]
            use_sc = use_sc.astype(np.float64)
            legal = np.ones(NR, dtype=bool)
            score_r = use_sc.copy()
            if joker and yz_filled:
                for r in np.nonzero(is_yz)[0]:
                    if forced_upper[r] >= 0 and rules['forced_upper']:
                        legal[r] = (c == forced_upper[r])
                    elif forced_upper[r] >= 0:
                        # unforced: matching upper normal, lower joker, other upper 0
                        if c < 6 and c != forced_upper[r]:
                            score_r[r] = 0.0
                        if c >= 6 and rules['joker_scores_need_upper_filled']:
                            score_r[r] = float(sc[r, c])
                    elif lower_open_any:
                        legal[r] = (c in LOWER_JOKER) or (rules['zero_upper_ok'] and c < 6)
                        if c < 6:
                            score_r[r] = 0.0
                    else:
                        legal[r] = c < 6
                        score_r[r] = 0.0
            if c < 6:
                newup = np.minimum(63, up_col[None, :] + score_r[:, None].astype(np.int64))
            else:
                newup = np.broadcast_to(up_col[None, :], (NR, 128))
            if c == YZ:
                newyb = yb_col[None, :] | is_yz[:, None].astype(np.int64)
            else:
                newyb = np.broadcast_to(yb_col[None, :], (NR, 128))
            cand = score_r[:, None] + succ[newup, newyb]
            if bonus_yz:
                cand = cand + 100.0 * (yb_col[None, :] * is_yz[:, None])
            cand[~legal, :] = -np.inf
            if joker and yz_filled and not rules['joker_when_scratched']:
                # scratched Yahtzee box (yb=0 columns): no joker, normal scoring/legality
                sr = sc[:, c].astype(np.float64)
                nu = np.minimum(63, up_col[None, :] + sr[:, None].astype(np.int64)) if c < 6 else newup
                cn = sr[:, None] + succ[nu, newyb]
                cand = np.where(yb_col[None, :] == 0, cn, cand)
            np.maximum(best, cand, out=best)
        V3 = best
        E2 = T @ V3
        V2 = max_over_subkeeps(E2, edges, roll_as_keep)
        E1 = T @ V2
        V1 = max_over_subkeeps(E1, edges, roll_as_keep)
        V[mask] = (P @ V1).reshape(64, 2)
    print(f"[{mode}] fresh EV = {V[0,0,0]:.6f}  ({time.time()-t0:.1f}s)", flush=True)
    return V


# --------------------------------------------------------------------------------------
# Library entry point used by the tests
# --------------------------------------------------------------------------------------
PRESETS = {
    "hasbro": ("strict", None),
    "verhoeff": ("strict", dict(forced_upper=False, joker_scores_need_upper_filled=True, zero_upper_ok=True)),
    "plain": ("plain", None),
}
EXPECTED_FRESH_EV = {"hasbro": 254.587729, "verhoeff": 254.589609, "plain": 245.870775}

_CACHE: Dict[str, np.ndarray] = {}


def _disk_path(preset: str) -> Optional[Path]:
    d = os.environ.get("YSOLVER_REF_CACHE")
    return Path(d) / f"ref_{preset}.npy" if d else None


def solve_reference(preset: str) -> np.ndarray:
    """Reference EV table, shape (8192, 64, 2), for 'hasbro', 'verhoeff' or 'plain'."""
    if preset not in PRESETS:
        raise ValueError(f"unknown preset {preset!r}; expected one of {sorted(PRESETS)}")
    V = _CACHE.get(preset)
    if V is not None:
        return V
    path = _disk_path(preset)
    if path is not None and path.exists():
        V = np.load(path)
    else:
        mode, rules = PRESETS[preset]
        V = solve(mode, rules)
        if mode == "plain":
            # plain has no yb dependence: keep one plane and duplicate it to (8192, 64, 2)
            plane = V[:, :, 0] if V.ndim == 3 else V
            V = np.stack([plane, plane], axis=-1)
        V = np.ascontiguousarray(V, dtype=np.float64)
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            np.save(path, V)
    if V.shape != (8192, 64, 2):
        raise ValueError(f"reference table for {preset} has shape {V.shape}")
    _CACHE[preset] = V
    return V
