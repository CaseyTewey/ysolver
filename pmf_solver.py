"""
Probability Mass Function (PMF) solver for score distributions.

This module computes the full distribution of remaining scores
under optimal play, enabling win probability calculations.
"""

from typing import Dict, Tuple, List, Optional
from functools import lru_cache
from collections import OrderedDict
from threading import RLock
from math import isfinite
import numpy as np
from scipy.signal import fftconvolve
from dice import Counts, enumerate_rolls, roll_id, id_to_roll
from scoring import (
    get_score_table, NUM_CATEGORIES, UPPER_BONUS,
    UPPER_BONUS_THRESHOLD, is_upper_category, get_legal_categories
)
from transitions import get_keep_options, get_transition_dist, get_initial_roll_dist
from ev_solver import best_keep_roll1, best_keep_roll2, best_category, clamp_upper, FULL_MASK, MAX_UPPER

# Type alias for PMF: maps score delta to probability
PMF = Dict[int, float]


def prune_pmf(pmf: PMF, eps: float = 0.0, topk: int = 2000) -> PMF:
    """
    Prune a PMF to reduce size while preserving most mass.

    Args:
        pmf: Input probability mass function
        eps: Minimum probability threshold
        topk: Maximum number of entries to keep

    Returns:
        Pruned PMF (renormalized)
    """
    if not isfinite(eps) or eps < 0:
        raise ValueError("eps must be a finite nonnegative number")
    if isinstance(topk, bool) or not isinstance(topk, int) or topk < 1:
        raise ValueError("topk must be a positive integer")
    if not pmf:
        return {}
    if any(not isfinite(prob) or prob < 0 for prob in pmf.values()):
        raise ValueError("PMF probabilities must be finite and nonnegative")
    positive = {score: prob for score, prob in pmf.items() if prob > 0}
    if not positive:
        raise ValueError("PMF must contain positive probability mass")
    pruned = dict(sorted(positive.items(), key=lambda item: -item[1])[:topk])
    pruned = {score: prob for score, prob in pruned.items() if prob >= eps}
    # An aggressive caller-supplied cutoff must not produce an empty distribution.
    if not pruned:
        score = max(positive, key=positive.get)
        pruned = {score: positive[score]}
    total = sum(pruned.values())
    return {score: prob / total for score, prob in pruned.items()}


def shift_pmf(pmf: PMF, delta: int) -> PMF:
    """Shift all scores in PMF by delta."""
    return {k + delta: v for k, v in pmf.items()}


def convolve_pmf(pmf1: PMF, pmf2: PMF) -> PMF:
    """
    Convolve two PMFs using FFT for O(n log n) complexity.

    This replaces the naive O(n^2) nested loop implementation with
    scipy.signal.fftconvolve for dramatic speedup on large PMFs.

    Result[k] = sum over i,j where i+j=k of pmf1[i] * pmf2[j]

    Args:
        pmf1: First probability mass function (score -> probability)
        pmf2: Second probability mass function (score -> probability)

    Returns:
        Convolved PMF representing the distribution of the sum
    """
    # Handle edge cases
    if not pmf1 or not pmf2:
        return {}

    if len(pmf1) == 1 and len(pmf2) == 1:
        # Both single-entry: direct computation is faster
        s1, p1 = next(iter(pmf1.items()))
        s2, p2 = next(iter(pmf2.items()))
        return {s1 + s2: p1 * p2}

    # For very small PMFs, use direct computation (faster than FFT overhead)
    if len(pmf1) * len(pmf2) < 500:
        result = {}
        for s1, p1 in pmf1.items():
            for s2, p2 in pmf2.items():
                s = s1 + s2
                result[s] = result.get(s, 0.0) + p1 * p2
        return result

    # Convert sparse PMF dicts to dense arrays for FFT
    min1, max1 = min(pmf1.keys()), max(pmf1.keys())
    min2, max2 = min(pmf2.keys()), max(pmf2.keys())

    # Create dense arrays (offset so indices start at 0)
    arr1 = np.zeros(max1 - min1 + 1, dtype=np.float64)
    arr2 = np.zeros(max2 - min2 + 1, dtype=np.float64)

    for s, p in pmf1.items():
        arr1[s - min1] = p
    for s, p in pmf2.items():
        arr2[s - min2] = p

    # FFT convolution: O(n log n) instead of O(n^2)
    conv = fftconvolve(arr1, arr2, mode='full')

    # Convert back to sparse PMF dict
    # The result array starts at index 0, corresponding to score min1 + min2
    result_min = min1 + min2
    result = {}

    # Use a threshold to avoid storing near-zero probabilities
    eps = 1e-15
    for i, p in enumerate(conv):
        if p > eps:
            result[result_min + i] = p

    return result


def mix_pmfs(pmfs_with_weights: List[Tuple[PMF, float]]) -> PMF:
    """
    Create mixture of PMFs with given weights.

    Args:
        pmfs_with_weights: List of (pmf, weight) pairs

    Returns:
        Mixed PMF
    """
    result = {}
    for pmf, weight in pmfs_with_weights:
        for score, prob in pmf.items():
            result[score] = result.get(score, 0.0) + prob * weight
    return result


# =============================================================================
# PMF Computation Under Optimal Policy
# =============================================================================

# Include approximation options in the cache key. Serialize recursive solves so
# concurrent callers share work and cannot race cache clearing or LRU updates.
_PMF_CACHE = OrderedDict()
_PMF_CACHE_MAX_SIZE = 10000
_PMF_LOCK = RLock()


def clear_pmf_cache():
    """Clear the PMF cache after any current solve completes."""
    with _PMF_LOCK:
        _PMF_CACHE.clear()


def _validate_pmf_state(mask: int, upper: int, eps: float, topk: int) -> int:
    if isinstance(mask, bool) or not isinstance(mask, int) or not 0 <= mask <= FULL_MASK:
        raise ValueError("mask must be a 13-bit nonnegative integer")
    if isinstance(upper, bool) or not isinstance(upper, int) or upper < 0:
        raise ValueError("upper must be a nonnegative integer")
    prune_pmf({}, eps, topk)
    return clamp_upper(upper)


def pmf_remaining(mask: int, upper: int, eps: float = 0.0, topk: int = 2000) -> PMF:
    """Return remaining category points plus the upper bonus awarded at game end.

    Locked scores used with this distribution must exclude the upper bonus.
    eps=0 preserves every positive outcome; nonzero eps or a restrictive topk
    explicitly requests an approximate distribution. Full-game recursive solves
    are expensive; interactive callers should restrict the remaining categories.
    """
    upper = _validate_pmf_state(mask, upper, eps, topk)
    with _PMF_LOCK:
        return _pmf_remaining(mask, upper, eps, topk).copy()


def _pmf_remaining(mask: int, upper: int, eps: float, topk: int) -> PMF:
    cache_key = (mask, upper, eps, topk)
    if cache_key in _PMF_CACHE:
        _PMF_CACHE.move_to_end(cache_key)
        return _PMF_CACHE[cache_key]
    if mask == FULL_MASK:
        result = {UPPER_BONUS if upper >= UPPER_BONUS_THRESHOLD else 0: 1.0}
    else:
        final_pmf = {}
        for (pts, next_mask, next_upper), prob in compute_turn_pmf(mask, upper).items():
            for score, future_prob in _pmf_remaining(next_mask, next_upper, eps, topk).items():
                total_score = score + pts
                final_pmf[total_score] = final_pmf.get(total_score, 0.0) + prob * future_prob
        result = prune_pmf(final_pmf, eps, topk)
    _PMF_CACHE[cache_key] = result
    if len(_PMF_CACHE) > _PMF_CACHE_MAX_SIZE:
        _PMF_CACHE.popitem(last=False)
    return result


def _final_roll_distribution(keeps_after_roll1, keeps_after_roll2) -> Dict[int, float]:
    """Propagate mass across roll states; never prune individual roll paths."""
    current = dict(get_initial_roll_dist())
    for keeps in (keeps_after_roll1, keeps_after_roll2):
        following = {}
        for roll_idx, probability in current.items():
            for next_roll, transition_prob in get_transition_dist(roll_idx, keeps[roll_idx]):
                following[next_roll] = following.get(next_roll, 0.0) + probability * transition_prob
        current = following
    return current


def compute_turn_pmf(mask: int, upper: int, eps: float = 0.0,
                     topk: int = 2000) -> Dict[Tuple[int, int, int], float]:
    """
    Compute distribution of turn outcomes under optimal policy.

    Returns:
        Dict mapping (points, next_mask, next_upper) -> probability
    """
    upper = _validate_pmf_state(mask, upper, eps, topk)
    if mask == FULL_MASK:
        return {(0, mask, upper): 1.0}
    score_table = get_score_table()
    keep1 = [best_keep_roll1(rid, mask, upper) for rid in range(len(score_table))]
    keep2 = [best_keep_roll2(rid, mask, upper) for rid in range(len(score_table))]
    result = {}
    for roll_idx, probability in _final_roll_distribution(keep1, keep2).items():
        cat, _ = best_category(roll_idx, mask, upper)
        pts = int(score_table[roll_idx][cat])
        next_upper = clamp_upper(upper + pts) if is_upper_category(cat) else upper
        key = (pts, mask | (1 << cat), next_upper)
        result[key] = result.get(key, 0.0) + probability
    return result


# =============================================================================
# Score Distribution Analysis
# =============================================================================

def pmf_stats(pmf: PMF) -> Dict:
    """Compute statistics of a PMF."""
    if not pmf:
        return {"mean": 0, "std": 0, "min": 0, "max": 0}

    mean = sum(s * p for s, p in pmf.items())
    variance = sum(p * (s - mean) ** 2 for s, p in pmf.items())
    std = variance ** 0.5

    return {
        "mean": mean,
        "std": std,
        "min": min(pmf.keys()),
        "max": max(pmf.keys()),
    }


def pmf_cdf(pmf: PMF) -> Dict[int, float]:
    """Convert PMF to CDF."""
    sorted_scores = sorted(pmf.keys())
    cdf = {}
    cumulative = 0.0
    for score in sorted_scores:
        cumulative += pmf[score]
        cdf[score] = cumulative
    return cdf


def prob_at_least(pmf: PMF, threshold: int) -> float:
    """Probability of achieving at least threshold score."""
    return sum(p for s, p in pmf.items() if s >= threshold)


def prob_at_most(pmf: PMF, threshold: int) -> float:
    """Probability of achieving at most threshold score."""
    return sum(p for s, p in pmf.items() if s <= threshold)


def percentile(pmf: PMF, p: float) -> int:
    """Get the score at the p-th percentile."""
    cdf = pmf_cdf(pmf)
    sorted_scores = sorted(cdf.keys())
    for score in sorted_scores:
        if cdf[score] >= p:
            return score
    return sorted_scores[-1] if sorted_scores else 0


# =============================================================================
# "Outs" Style Analysis
# =============================================================================

def compute_turn_score_dist(mask: int, upper: int) -> PMF:
    """
    Compute distribution of points scored THIS TURN only.
    (Not including future turns)
    """
    result = {}
    for (points, _, _), probability in compute_turn_pmf(mask, upper).items():
        result[points] = result.get(points, 0.0) + probability
    return result


def compute_category_hit_probs(mask: int, upper: int) -> Dict[int, float]:
    """Compute probability of choosing each open category on the next turn."""
    result = {cat: 0.0 for cat in get_legal_categories(mask)}
    if not result:
        return result
    for (_, next_mask, _), probability in compute_turn_pmf(mask, upper).items():
        cat = (next_mask ^ mask).bit_length() - 1
        result[cat] += probability
    return result


def get_outs_analysis(mask: int, upper: int, current_score: int,
                      target_score: int) -> Dict:
    """
    Analyze "outs" - what needs to happen to reach target score.

    Args:
        mask: Current filled categories
        upper: Upper section subtotal
        current_score: Points already locked in
        target_score: Score needed to win

    Returns:
        Dict with outs analysis
    """
    from scoring import CATEGORY_NAMES

    needed = target_score - current_score

    # Get remaining score distribution
    remaining_pmf = pmf_remaining(mask, upper)
    stats = pmf_stats(remaining_pmf)

    # Probability of reaching target
    prob_reach = prob_at_least(remaining_pmf, needed)

    # Turn score distribution
    turn_pmf = compute_turn_score_dist(mask, upper)
    turn_stats = pmf_stats(turn_pmf)

    # Category hit probabilities
    cat_probs = compute_category_hit_probs(mask, upper)

    # Score thresholds this turn
    turn_thresholds = [
        (10, prob_at_least(turn_pmf, 10)),
        (20, prob_at_least(turn_pmf, 20)),
        (30, prob_at_least(turn_pmf, 30)),
        (40, prob_at_least(turn_pmf, 40)),
        (50, prob_at_least(turn_pmf, 50)),
    ]

    return {
        "needed_to_reach_target": needed,
        "prob_reach_target": prob_reach,
        "remaining_score_stats": stats,
        "turn_score_stats": turn_stats,
        "turn_thresholds": [
            {"threshold": t, "probability": p}
            for t, p in turn_thresholds if p > 0.001
        ],
        "category_probs": [
            {"category": cat, "name": CATEGORY_NAMES[cat], "probability": p}
            for cat, p in sorted(cat_probs.items(), key=lambda x: -x[1])
            if p > 0.01
        ],
    }


# =============================================================================
# Warm-up and Testing
# =============================================================================

def warm_pmf_cache(max_unfilled: int = 5, verbose: bool = True):
    """
    Warm PMF cache for states with up to max_unfilled categories remaining.

    This is useful for late-game analysis where PMF computation matters most.
    """
    if verbose:
        print(f"Warming PMF cache for states with <= {max_unfilled} categories remaining...")

    count = 0
    for mask in range(FULL_MASK + 1):
        num_filled = bin(mask).count('1')
        if NUM_CATEGORIES - num_filled <= max_unfilled:
            for upper in range(MAX_UPPER + 1):
                pmf_remaining(mask, upper)
                count += 1

    if verbose:
        print(f"Computed {count} PMF states")


if __name__ == "__main__":
    from ev_solver import warm_cache, get_expected_score_fresh_game

    print("Warming EV cache first...")
    warm_cache(verbose=True)

    print("\n" + "=" * 60)
    print("Testing PMF computation...")

    # Fresh game PMF
    fresh_pmf = pmf_remaining(0, 0)
    stats = pmf_stats(fresh_pmf)

    print(f"\nFresh game score distribution:")
    print(f"  Mean: {stats['mean']:.2f}")
    print(f"  Std:  {stats['std']:.2f}")
    print(f"  Min:  {stats['min']}")
    print(f"  Max:  {stats['max']}")
    print(f"  PMF entries: {len(fresh_pmf)}")

    # Compare mean to EV
    ev = get_expected_score_fresh_game()
    print(f"\nEV from ev_solver: {ev:.2f}")
    print(f"Mean from PMF:     {stats['mean']:.2f}")
    print(f"Difference:        {abs(ev - stats['mean']):.4f}")

    # Percentiles
    print(f"\nPercentiles:")
    for p in [0.1, 0.25, 0.5, 0.75, 0.9]:
        print(f"  {int(p*100)}th: {percentile(fresh_pmf, p)}")

    # Turn analysis
    print("\n" + "=" * 60)
    print("Turn analysis (first turn of game):")

    turn_pmf = compute_turn_score_dist(0, 0)
    turn_stats = pmf_stats(turn_pmf)
    print(f"  Mean points this turn: {turn_stats['mean']:.2f}")
    print(f"  P(>=20 pts): {prob_at_least(turn_pmf, 20):.3f}")
    print(f"  P(>=30 pts): {prob_at_least(turn_pmf, 30):.3f}")
    print(f"  P(>=50 pts): {prob_at_least(turn_pmf, 50):.3f}")

    # Outs analysis
    print("\n" + "=" * 60)
    print("Outs analysis (need 280 to win from fresh game):")
    outs = get_outs_analysis(0, 0, 0, 280)
    print(f"  Needed: {outs['needed_to_reach_target']}")
    print(f"  P(reach target): {outs['prob_reach_target']:.3f}")

    print("\n  This turn thresholds:")
    for t in outs['turn_thresholds']:
        print(f"    >= {t['threshold']} pts: {t['probability']:.3f}")
