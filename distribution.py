"""
distribution.py - exact score distributions under the solver's optimal policy.

pmf_remaining(solver, mask, upper, yb) returns the probability mass function of the
REMAINING score (upper bonus and Yahtzee bonuses included) when the player follows the
EV-optimal policy from that state. It is exact: no pruning, dense vectors, the same
tie-breaking as the tables (so its mean equals EV and its variance equals M2 - EV^2).

Cost grows with the number of states reachable from the root, roughly 2^open boxes x
reachable uppers. Use it for end-games (the app caps it at MAX_OPEN_FOR_EXACT boxes); for
earlier states the solver's exact mean and standard deviation are available instantly.

win_probabilities(...) combines two such distributions into P(win), P(tie), P(lose).
"""
from typing import Dict, Optional, Tuple

import numpy as np

from engine import (
    Solver, FULL_MASK, MAX_UPPER, NUM_CATS, NUM_ROLLS, YAHTZEE, UPPER_BONUS,
    UPPER_BONUS_THRESHOLD, max_remaining, _argmax_sub,
)

MAX_OPEN_FOR_EXACT = 7


class TooManyBoxesOpen(ValueError):
    pass


def pmf_remaining(solver: Solver, mask: int, upper: int, yb: int,
                  max_open: int = MAX_OPEN_FOR_EXACT) -> np.ndarray:
    """PMF (index = points) of the remaining score under optimal play from (mask, upper, yb)."""
    solver._check(mask, upper, yb)
    n_open = NUM_CATS - bin(mask).count("1")
    if n_open > max_open:
        raise TooManyBoxesOpen(f"{n_open} boxes open; exact distribution limited to {max_open}")
    L = max_remaining(solver.rules, mask, upper, yb) + 1
    memo: Dict[Tuple[int, int, int], np.ndarray] = {}
    return _pmf(solver, mask, upper, yb, L, memo)


def _pmf(solver: Solver, mask: int, upper: int, yb: int, L: int, memo: dict) -> np.ndarray:
    key = (mask, upper, yb)
    hit = memo.get(key)
    if hit is not None:
        return hit
    if mask == FULL_MASK:
        pmf = np.zeros(L)
        pmf[UPPER_BONUS if upper >= UPPER_BONUS_THRESHOLD else 0] = 1.0
        memo[key] = pmf
        return pmf
    t = solver.t
    tv = solver.turn(mask, upper, yb)
    is_yz = t.is_yz
    # final roll: the chosen box (same tie-break as the tables: lowest index among maxima)
    pmf3 = np.zeros((NUM_ROLLS, L))
    for rid in range(NUM_ROLLS):
        legal, pts, bonus = solver.options(mask, upper, yb, rid)
        best = -1e18
        choice = None
        for c in range(NUM_CATS):
            if not legal[c]:
                continue
            p = int(pts[c])
            nm = mask | (1 << c)
            nyb = 1 if (c == YAHTZEE and is_yz[rid]) else yb
            nu = min(MAX_UPPER, upper + p) if c < 6 else upper
            val = p + bonus + solver.EV[nm, nu, nyb]
            if val > best:
                best = val
                choice = (p + bonus, nm, nu, nyb)
        gain, nm, nu, nyb = choice
        succ = _pmf(solver, nm, nu, nyb, L, memo)
        if gain:
            pmf3[rid, gain:] = succ[:L - gain]
        else:
            pmf3[rid, :] = succ
    # keeps: rows of T for the keep chosen after roll 2 (target e2) and after roll 1 (target e1)
    k2 = np.fromiter((_argmax_sub(tv["e2"], r, t.sub_ptr, t.sub_idx) for r in range(NUM_ROLLS)), dtype=np.int64, count=NUM_ROLLS)
    k1 = np.fromiter((_argmax_sub(tv["e1"], r, t.sub_ptr, t.sub_idx) for r in range(NUM_ROLLS)), dtype=np.int64, count=NUM_ROLLS)
    pmf2 = t.T[k2] @ pmf3
    pmf1 = t.T[k1] @ pmf2
    pmf = t.P @ pmf1
    memo[key] = pmf
    return pmf


def pmf_mean_var(pmf: np.ndarray) -> Tuple[float, float]:
    x = np.arange(len(pmf))
    m = float(pmf @ x)
    return m, float(pmf @ (x * x)) - m * m


def pmf_stats(pmf: np.ndarray) -> dict:
    m, v = pmf_mean_var(pmf)
    cdf = np.cumsum(pmf)
    def pct(q):
        return int(np.searchsorted(cdf, q))
    return {"mean": m, "std": v ** 0.5, "p10": pct(0.10), "p50": pct(0.50), "p90": pct(0.90),
            "mass": float(pmf.sum())}


def shift(pmf: np.ndarray, offset: int, length: Optional[int] = None) -> np.ndarray:
    """Return the distribution of (X + offset) on [0, length). Raises rather than dropping mass."""
    if length is None:
        length = len(pmf) + offset
    if offset < 0 or offset + len(pmf) > length:
        raise ValueError("shift: the shifted distribution does not fit in the requested length")
    out = np.zeros(length)
    out[offset:offset + len(pmf)] = pmf
    return out


def win_probabilities(pmf1: np.ndarray, locked1: int, pmf2: np.ndarray, locked2: int) -> Tuple[float, float, float]:
    """
    P(player 1 final > player 2 final), P(tie), P(player 2 wins).
    locked_i are the points already banked (without the 35 upper bonus, which the PMFs carry).
    """
    L = max(locked1 + len(pmf1), locked2 + len(pmf2))
    f1 = shift(pmf1, locked1, L)
    f2 = shift(pmf2, locked2, L)
    cdf2 = np.cumsum(f2)
    below = np.concatenate(([0.0], cdf2[:-1]))      # P(final2 < s)
    p1 = float(f1 @ below)
    tie = float(f1 @ f2)
    p2 = max(0.0, 1.0 - p1 - tie)
    return p1, tie, p2


def normal_win_probabilities(mean1: float, std1: float, mean2: float, std2: float) -> Tuple[float, float, float]:
    """Normal approximation to P(win), P(tie), P(lose) from exact means and standard deviations."""
    import math
    var = std1 * std1 + std2 * std2
    if var < 1e-12:
        if mean1 > mean2:
            return 1.0, 0.0, 0.0
        if mean1 < mean2:
            return 0.0, 0.0, 1.0
        return 0.0, 1.0, 0.0
    z = (mean1 - mean2) / math.sqrt(var)
    # erfc keeps the far tails (z beyond about 6) from rounding to exactly 0 or 1
    p1 = 0.5 * math.erfc(-z / math.sqrt(2.0))
    p2 = 0.5 * math.erfc(z / math.sqrt(2.0))
    return p1, 0.0, p2
