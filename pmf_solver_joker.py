"""
Probability Mass Function (PMF) solver for Joker Mode score distributions.

This module computes the full distribution of remaining scores
under optimal JOKER mode play, enabling exact win probability calculations.

Key differences from traditional PMF:
- State space includes yahtzee_status: (mask, upper, yahtzee_status)
- Models joker bonus (+100) for additional Yahtzees
- Uses joker scoring rules (FH=25, SS=30, LS=40 for jokers)
- Handles forced category rule
"""

import sys
import time
from typing import Dict, Tuple, List, Optional
import numpy as np
from scipy.signal import fftconvolve

from dice import Counts, enumerate_rolls, roll_id, id_to_roll
from scoring import (
    get_score_table, NUM_CATEGORIES, UPPER_BONUS,
    UPPER_BONUS_THRESHOLD, is_upper_category, get_legal_categories
)
from transitions import get_keep_options, get_transition_dist, get_initial_roll_dist
from ev_solver import (
    FULL_MASK, MAX_UPPER, clamp_upper,
    YAHTZEE_UNFILLED, YAHTZEE_SCRATCHED, YAHTZEE_SCORED,
    YAHTZEE_BONUS, YAHTZEE_CATEGORY,
    _load_joker_tables, _load_transitions,
    _compute_v3_joker_for_state, _compute_v2_joker_for_state,
    _find_best_keep
)

# Type alias for PMF: maps score delta to probability
PMF = Dict[int, float]


# =============================================================================
# PMF Helper Functions (same as pmf_solver.py)
# =============================================================================

def prune_pmf(pmf: PMF, eps: float = 1e-7, topk: int = 2000) -> PMF:
    """
    Prune a PMF to reduce size while preserving most mass.

    Args:
        pmf: Input probability mass function
        eps: Minimum probability threshold
        topk: Maximum number of entries to keep

    Returns:
        Pruned PMF (renormalized)
    """
    if len(pmf) <= topk:
        # Just remove tiny probabilities
        pruned = {k: v for k, v in pmf.items() if v >= eps}
    else:
        # Keep top-k by probability mass
        sorted_items = sorted(pmf.items(), key=lambda x: -x[1])[:topk]
        pruned = {k: v for k, v in sorted_items if v >= eps}

    # Renormalize
    total = sum(pruned.values())
    if total > 0 and abs(total - 1.0) > 1e-9:
        pruned = {k: v / total for k, v in pruned.items()}

    return pruned


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
# Progress Tracking
# =============================================================================

def print_progress_bar(current: int, total: int, start_time: float,
                       bar_width: int = 40, prefix: str = "Progress"):
    """Print a progress bar with ETA."""
    if total == 0:
        return

    fraction = current / total
    filled = int(bar_width * fraction)
    bar = "█" * filled + "░" * (bar_width - filled)

    elapsed = time.time() - start_time
    if fraction > 0:
        eta = elapsed / fraction - elapsed
        eta_str = f"ETA: {eta:.1f}s"
    else:
        eta_str = "ETA: --"

    sys.stdout.write(f"\r{prefix}: |{bar}| {current}/{total} ({fraction*100:.1f}%) {eta_str}   ")
    sys.stdout.flush()


# =============================================================================
# Joker Mode PMF Cache
# =============================================================================

# Cache key: (mask, upper, yahtzee_status)
# Using OrderedDict for LRU eviction
from collections import OrderedDict

_PMF_JOKER_CACHE = OrderedDict()  # OrderedDict[Tuple[int, int, int], PMF]
_PMF_CACHE_MAX_SIZE = 10000  # Limit cache to 10K entries (~50-100MB max)


def clear_pmf_joker_cache():
    """Clear the joker PMF cache."""
    global _PMF_JOKER_CACHE
    _PMF_JOKER_CACHE = OrderedDict()


def get_pmf_cache_size() -> int:
    """Get current cache size."""
    return len(_PMF_JOKER_CACHE)


def _cache_get(key: Tuple[int, int, int]) -> Optional[PMF]:
    """Get from cache with LRU update."""
    if key in _PMF_JOKER_CACHE:
        # Move to end (most recently used)
        _PMF_JOKER_CACHE.move_to_end(key)
        return _PMF_JOKER_CACHE[key]
    return None


def _cache_put(key: Tuple[int, int, int], value: PMF):
    """Put in cache with LRU eviction."""
    global _PMF_JOKER_CACHE
    if key in _PMF_JOKER_CACHE:
        _PMF_JOKER_CACHE.move_to_end(key)
    else:
        if len(_PMF_JOKER_CACHE) >= _PMF_CACHE_MAX_SIZE:
            # Evict oldest (first) entry
            _PMF_JOKER_CACHE.popitem(last=False)
    _PMF_JOKER_CACHE[key] = value


# =============================================================================
# Joker Turn PMF Computation
# =============================================================================

def _precompute_best_keeps_joker(mask: int, upper: int, yahtzee_status: int,
                                  tables: Dict) -> Tuple[np.ndarray, np.ndarray]:
    """
    Pre-compute best keep indices for all rolls in a state.

    This is the key optimization - compute v2/v3 once and use for all rolls.

    Returns:
        (best_keep_roll1, best_keep_roll2) - arrays of shape (252,)
    """
    trans = _load_transitions()
    num_rolls = 252

    # Compute v3 for this state (best category to score for each final roll)
    v3_values = _compute_v3_joker_for_state(mask, upper, yahtzee_status, tables)

    # Compute v2 from v3 (best keep after roll 2)
    v2_values = _compute_v2_joker_for_state(v3_values, tables)

    # Compute v1 from v2 (best keep after roll 1) - we need this for roll1 decisions
    # v1[roll] = max over keeps of E[v2[next_roll]] = max_k sum_r trans[roll,k,r] * v2[r]
    # But we actually need the v1 values to know what to keep after roll 1

    # For each roll, find the best keep index using v2 (for roll1) and v3 (for roll2)
    best_keep_roll1 = np.zeros(num_rolls, dtype=np.int32)
    best_keep_roll2 = np.zeros(num_rolls, dtype=np.int32)

    for roll_idx in range(num_rolls):
        # Best keep after roll 2 uses v3
        k2, _ = _find_best_keep(
            roll_idx, v3_values,
            trans['num_keeps'],
            trans['trans_starts'],
            trans['trans_ends'],
            trans['trans_next'],
            trans['trans_prob']
        )
        best_keep_roll2[roll_idx] = k2

        # Best keep after roll 1 uses v2
        k1, _ = _find_best_keep(
            roll_idx, v2_values,
            trans['num_keeps'],
            trans['trans_starts'],
            trans['trans_ends'],
            trans['trans_next'],
            trans['trans_prob']
        )
        best_keep_roll1[roll_idx] = k1

    return best_keep_roll1, best_keep_roll2


def _get_best_category_joker_full(roll_idx: int, mask: int, upper: int,
                                   yahtzee_status: int, tables: Dict) -> Tuple[int, int, int, int]:
    """
    Get optimal category and full state transition info.

    Returns:
        (category, points_including_bonus, next_upper, next_yahtzee_status)
    """
    is_ytz_arr = tables['is_yahtzee']
    ytz_face_arr = tables['yahtzee_face']
    score_table = tables['score_table']
    joker_score_table = tables['joker_score_table']
    ev_remaining_arr = tables['ev_remaining']

    is_ytz = is_ytz_arr[roll_idx]
    ytz_face = ytz_face_arr[roll_idx]

    # Joker bonus if rolling another yahtzee after scoring 50
    joker_bonus = YAHTZEE_BONUS if (is_ytz and yahtzee_status == YAHTZEE_SCORED) else 0

    # Check for forced category
    forced_cat = None
    if is_ytz and yahtzee_status == YAHTZEE_SCORED:
        upper_cat = ytz_face
        if not (mask & (1 << upper_cat)):
            forced_cat = upper_cat

    legal_cats = get_legal_categories(mask)

    # If forced, only consider that category
    if forced_cat is not None:
        legal_cats = [forced_cat]

    best_ev = float('-inf')
    best_cat = None
    best_pts = 0
    best_next_upper = upper
    best_next_ys = yahtzee_status

    for cat in legal_cats:
        # Use joker score table if eligible for joker
        if is_ytz and yahtzee_status == YAHTZEE_SCORED:
            pts = int(joker_score_table[roll_idx, cat])
        else:
            pts = int(score_table[roll_idx, cat])

        new_mask = mask | (1 << cat)
        new_upper = upper
        if is_upper_category(cat):
            new_upper = min(MAX_UPPER, upper + pts)

        # Update yahtzee status if scoring in yahtzee category
        new_ys = yahtzee_status
        if cat == YAHTZEE_CATEGORY:
            new_ys = YAHTZEE_SCORED if pts == 50 else YAHTZEE_SCRATCHED

        future_ev = float(ev_remaining_arr[new_mask, new_upper, new_ys])
        ev = pts + joker_bonus + future_ev

        if ev > best_ev:
            best_ev = ev
            best_cat = cat
            best_pts = pts + joker_bonus
            best_next_upper = new_upper
            best_next_ys = new_ys

    return best_cat, best_pts, best_next_upper, best_next_ys


def compute_turn_pmf_joker(mask: int, upper: int, yahtzee_status: int,
                           eps: float = 1e-7, topk: int = 2000) -> Dict[Tuple[int, int, int, int], float]:
    """
    Compute distribution of turn outcomes under optimal joker policy.

    This function enumerates all possible paths through a turn and
    accumulates the probability of each unique outcome.

    Args:
        mask: Filled categories bitmask
        upper: Upper section subtotal (clamped)
        yahtzee_status: Current yahtzee status (0, 1, or 2)
        eps: Probability pruning threshold
        topk: Max outcomes to keep

    Returns:
        Dict mapping (points, next_mask, next_upper, next_yahtzee_status) -> probability
    """
    tables = _load_joker_tables()
    result = {}

    # Pre-compute best keeps for all rolls in this state (key optimization!)
    best_keep_roll1, best_keep_roll2 = _precompute_best_keeps_joker(
        mask, upper, yahtzee_status, tables
    )

    # Enumerate all paths through the turn
    for roll1_idx, p1 in get_initial_roll_dist():
        if p1 < eps:
            continue

        # Get optimal keep after roll 1 (using pre-computed index)
        keep_options1 = get_keep_options(roll1_idx)
        keep1 = keep_options1[best_keep_roll1[roll1_idx]]

        for roll2_idx, p2 in get_transition_dist(roll1_idx, keep1):
            if p1 * p2 < eps:
                continue

            # Get optimal keep after roll 2 (using pre-computed index)
            keep_options2 = get_keep_options(roll2_idx)
            keep2 = keep_options2[best_keep_roll2[roll2_idx]]

            for roll3_idx, p3 in get_transition_dist(roll2_idx, keep2):
                path_prob = p1 * p2 * p3
                if path_prob < eps:
                    continue

                # Get optimal category and state transition
                cat, pts, next_upper, next_ys = _get_best_category_joker_full(
                    roll3_idx, mask, upper, yahtzee_status, tables
                )

                next_mask = mask | (1 << cat)

                # Accumulate probability
                key = (pts, next_mask, next_upper, next_ys)
                result[key] = result.get(key, 0.0) + path_prob

    return result


# =============================================================================
# Joker PMF Remaining (Recursive)
# =============================================================================

def pmf_remaining_joker(mask: int, upper: int, yahtzee_status: int,
                        eps: float = 1e-7, topk: int = 2000) -> PMF:
    """
    Compute distribution of remaining score under optimal joker policy.

    This function recursively computes the PMF of remaining scores
    by convolving turn outcomes with future PMFs.

    Args:
        mask: Filled categories bitmask
        upper: Upper section subtotal (clamped)
        yahtzee_status: Current yahtzee status (0=unfilled, 1=scratched, 2=scored)
        eps: Probability pruning threshold
        topk: Max PMF entries

    Returns:
        PMF mapping additional_score -> probability
    """
    cache_key = (mask, upper, yahtzee_status)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    # Base case: all categories filled
    if mask == FULL_MASK:
        bonus = UPPER_BONUS if upper >= UPPER_BONUS_THRESHOLD else 0
        result = {bonus: 1.0}
        _cache_put(cache_key, result)
        return result

    # Compute turn PMF and convolve with future
    turn_result = compute_turn_pmf_joker(mask, upper, yahtzee_status, eps, topk)

    # turn_result maps (points, next_mask, next_upper, next_ys) -> probability
    # We need to convolve each outcome with its future PMF

    final_pmf = {}

    for (pts, next_mask, next_upper, next_ys), prob in turn_result.items():
        # Get future PMF from next state (recursive call)
        future_pmf = pmf_remaining_joker(next_mask, next_upper, next_ys, eps, topk)

        # Shift future PMF by points scored this turn
        shifted = shift_pmf(future_pmf, pts)

        # Add to mixture
        for score, p in shifted.items():
            final_pmf[score] = final_pmf.get(score, 0.0) + prob * p

    # Prune result
    final_pmf = prune_pmf(final_pmf, eps, topk)

    _cache_put(cache_key, final_pmf)
    return final_pmf


# =============================================================================
# PMF Statistics
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
# Win Probability Computation
# =============================================================================

def compute_win_probability_exact(
    p1_locked: int, p1_mask: int, p1_upper: int, p1_yahtzee_status: int,
    p2_locked: int, p2_mask: int, p2_upper: int, p2_yahtzee_status: int
) -> Tuple[float, float, float]:
    """
    Compute exact win probability using full PMF distributions.

    Args:
        p1_locked: Player 1's locked score (already earned)
        p1_mask: Player 1's filled categories mask
        p1_upper: Player 1's upper section subtotal
        p1_yahtzee_status: Player 1's yahtzee status
        p2_locked: Player 2's locked score
        p2_mask: Player 2's filled categories mask
        p2_upper: Player 2's upper section subtotal
        p2_yahtzee_status: Player 2's yahtzee status

    Returns:
        (p1_win_prob, tie_prob, p2_win_prob)
    """
    # Get PMFs for remaining scores
    pmf1 = pmf_remaining_joker(p1_mask, p1_upper, p1_yahtzee_status)
    pmf2 = pmf_remaining_joker(p2_mask, p2_upper, p2_yahtzee_status)

    # Shift by locked scores to get final score distributions
    pmf1_final = shift_pmf(pmf1, p1_locked)
    pmf2_final = shift_pmf(pmf2, p2_locked)

    # Compute P(p1 wins), P(tie), P(p2 wins)
    p1_wins = 0.0
    tie_prob = 0.0
    p2_wins = 0.0

    for s1, prob1 in pmf1_final.items():
        for s2, prob2 in pmf2_final.items():
            joint_prob = prob1 * prob2
            if s1 > s2:
                p1_wins += joint_prob
            elif s1 < s2:
                p2_wins += joint_prob
            else:
                tie_prob += joint_prob

    return (p1_wins, tie_prob, p2_wins)


# =============================================================================
# Cache Warming with Progress
# =============================================================================

def warm_pmf_cache_joker(max_unfilled: int = 5, verbose: bool = True):
    """
    Warm PMF cache for joker mode states with up to max_unfilled categories remaining.

    This pre-computes PMFs for late-game states where exact calculation matters most.

    Args:
        max_unfilled: Maximum unfilled categories to compute (5 is typical)
        verbose: Show progress bar
    """
    if verbose:
        print(f"\n{'=' * 60}")
        print("WARMING JOKER PMF CACHE")
        print(f"{'=' * 60}")
        print(f"Computing states with <= {max_unfilled} unfilled categories...")

    # First, count total states to compute
    states_to_compute = []
    for mask in range(FULL_MASK + 1):
        num_filled = bin(mask).count('1')
        if NUM_CATEGORIES - num_filled <= max_unfilled:
            for upper in range(MAX_UPPER + 1):
                for ys in range(3):  # UNFILLED, SCRATCHED, SCORED
                    # Skip invalid states (e.g., SCORED but yahtzee category not filled)
                    yahtzee_filled = bool(mask & (1 << YAHTZEE_CATEGORY))
                    if ys != YAHTZEE_UNFILLED and not yahtzee_filled:
                        continue
                    states_to_compute.append((mask, upper, ys))

    total = len(states_to_compute)
    if verbose:
        print(f"Total states to compute: {total:,}")

    start_time = time.time()
    last_update = start_time

    for i, (mask, upper, ys) in enumerate(states_to_compute):
        pmf_remaining_joker(mask, upper, ys)

        # Update progress every 0.5 seconds
        now = time.time()
        if verbose and (now - last_update > 0.5 or i == total - 1):
            print_progress_bar(i + 1, total, start_time, prefix="PMF Cache")
            last_update = now

    elapsed = time.time() - start_time

    if verbose:
        print()  # Newline after progress bar
        print(f"\nCache warming complete!")
        print(f"  States computed: {total:,}")
        print(f"  Cache size: {len(_PMF_JOKER_CACHE):,}")
        print(f"  Time elapsed: {elapsed:.1f}s")
        print(f"{'=' * 60}")


# =============================================================================
# Main Test / Demo
# =============================================================================

if __name__ == "__main__":
    from ev_solver import warm_cache_joker, ev_remaining_joker

    print("=" * 60)
    print("JOKER PMF SOLVER TEST")
    print("=" * 60)
    print("\nNOTE: This test uses LATE-GAME states (2-3 categories remaining)")
    print("      Fresh game PMF is computationally infeasible.")
    print("      No cache warming - computes on demand (fast for late-game).")
    print("=" * 60)

    # Late-game test state: 11 categories filled, 2 remaining
    # Filled: All except Yahtzee(11) and Chance(12)
    TEST_MASK = 0b0011111111111  # Categories 0-10 filled (11 categories)
    TEST_UPPER = 35  # Reasonable upper section total
    TEST_CATS_REMAINING = 2

    print("\nStep 1: Loading joker EV tables...")
    try:
        warm_cache_joker(verbose=True)
    except RuntimeError as e:
        print(f"ERROR: {e}")
        print("Please run 'python precompute_joker.py' first!")
        sys.exit(1)

    print("\n" + "=" * 60)
    print(f"Step 2: Testing late-game PMF ({TEST_CATS_REMAINING} categories remaining)...")
    print(f"        Mask: {bin(TEST_MASK)}, Upper: {TEST_UPPER}")

    start = time.time()
    test_pmf = pmf_remaining_joker(TEST_MASK, TEST_UPPER, YAHTZEE_UNFILLED)
    elapsed = time.time() - start

    stats = pmf_stats(test_pmf)
    print(f"\n  Computation time: {elapsed:.2f}s")
    print(f"  PMF entries: {len(test_pmf)}")
    print(f"\n  Distribution stats:")
    print(f"    Mean: {stats['mean']:.2f}")
    print(f"    Std:  {stats['std']:.2f}")
    print(f"    Min:  {stats['min']}")
    print(f"    Max:  {stats['max']}")

    # Compare to EV from joker solver
    ev_for_state = ev_remaining_joker(TEST_MASK, TEST_UPPER, YAHTZEE_UNFILLED)
    print(f"\n  EV from joker solver: {ev_for_state:.2f}")
    print(f"  Mean from PMF:        {stats['mean']:.2f}")
    print(f"  Difference:           {abs(ev_for_state - stats['mean']):.4f}")

    if abs(ev_for_state - stats['mean']) < 1.0:
        print("  VALIDATION PASSED: Mean matches EV!")
    else:
        print("  VALIDATION FAILED: Mean does not match EV!")

    # Test probability axiom
    total_prob = sum(test_pmf.values())
    print(f"\n  Total probability: {total_prob:.6f}")
    if abs(total_prob - 1.0) < 1e-5:
        print("  PROBABILITY AXIOM: Sum = 1.0")
    else:
        print("  PROBABILITY AXIOM VIOLATED!")

    # Percentiles
    print(f"\n  Percentiles:")
    for p in [0.1, 0.25, 0.5, 0.75, 0.9]:
        print(f"    {int(p*100)}th: {percentile(test_pmf, p)}")

    print("\n" + "=" * 60)
    print("Step 4: Testing win probability calculation...")

    # Test symmetric case (both same late-game state)
    print(f"\n  Symmetric case (both with {TEST_CATS_REMAINING} remaining):")
    p1_win, tie, p2_win = compute_win_probability_exact(
        p1_locked=100, p1_mask=TEST_MASK, p1_upper=TEST_UPPER, p1_yahtzee_status=YAHTZEE_UNFILLED,
        p2_locked=100, p2_mask=TEST_MASK, p2_upper=TEST_UPPER, p2_yahtzee_status=YAHTZEE_UNFILLED
    )
    print(f"    P1 wins: {p1_win*100:.2f}%")
    print(f"    Tie:     {tie*100:.2f}%")
    print(f"    P2 wins: {p2_win*100:.2f}%")

    if abs(p1_win - p2_win) < 0.01:
        print("  SYMMETRY CHECK: Identical states have equal win probs")
    else:
        print("  SYMMETRY CHECK FAILED!")

    # Test with score advantage
    print("\n  Asymmetric case (P1 has 30 point lead):")
    p1_win, tie, p2_win = compute_win_probability_exact(
        p1_locked=130, p1_mask=TEST_MASK, p1_upper=TEST_UPPER, p1_yahtzee_status=YAHTZEE_UNFILLED,
        p2_locked=100, p2_mask=TEST_MASK, p2_upper=TEST_UPPER, p2_yahtzee_status=YAHTZEE_UNFILLED
    )
    print(f"    P1 wins: {p1_win*100:.2f}%")
    print(f"    Tie:     {tie*100:.2f}%")
    print(f"    P2 wins: {p2_win*100:.2f}%")

    if p1_win > p2_win:
        print("  MONOTONICITY: More points = higher win prob")
    else:
        print("  MONOTONICITY FAILED!")

    print("\n" + "=" * 60)
    print("Step 5: Testing yahtzee_status impact...")

    # Test SCORED vs UNFILLED (same mask)
    print(f"\n  Comparing yahtzee_status=UNFILLED vs SCORED:")
    pmf_unfilled = pmf_remaining_joker(TEST_MASK, TEST_UPPER, YAHTZEE_UNFILLED)
    stats_unfilled = pmf_stats(pmf_unfilled)

    # For SCORED, we need yahtzee category filled - adjust mask
    SCORED_MASK = TEST_MASK | (1 << 11)  # Add yahtzee (category 11)
    pmf_scored = pmf_remaining_joker(SCORED_MASK, TEST_UPPER, YAHTZEE_SCORED)
    stats_scored = pmf_stats(pmf_scored)

    print(f"    UNFILLED (3 remaining): mean={stats_unfilled['mean']:.2f}")
    print(f"    SCORED (2 remaining):   mean={stats_scored['mean']:.2f}")
    print("  (SCORED has fewer categories so lower remaining, but includes joker bonus potential)")

    print("\n" + "=" * 60)
    print("ALL TESTS COMPLETE")
    print("=" * 60)
