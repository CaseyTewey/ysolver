"""
Expected Value solver for single-player Yahtzee.

This module implements dynamic programming to compute:
- Maximum expected remaining score from any game state
- Optimal policy (what to keep, which category to score)

Uses precomputed tables from precompute_fast.py for instant lookups.
"""

from typing import Dict, Tuple, Optional, List
from functools import lru_cache
import numpy as np
from numba import njit
from dice import Counts, enumerate_rolls, roll_id, id_to_roll
from scoring import (
    score, get_score_table, NUM_CATEGORIES, UPPER_BONUS,
    UPPER_BONUS_THRESHOLD, is_upper_category, get_legal_categories,
    CATEGORY_NAMES, is_yahtzee_roll, get_yahtzee_face,
    get_forced_category_joker, get_joker_score_table_cached,
    get_yahtzee_detection_arrays, Category
)
from transitions import (
    get_keep_options, get_transition_dist, get_initial_roll_dist
)

# Constants
FULL_MASK = (1 << NUM_CATEGORIES) - 1  # All 13 categories filled
MAX_UPPER = 63  # Clamp upper subtotal at bonus threshold
NUM_ROLLS = 252

# Joker mode constants
YAHTZEE_UNFILLED = 0   # Yahtzee category not yet filled
YAHTZEE_SCRATCHED = 1  # Yahtzee filled with 0 (no future bonuses)
YAHTZEE_SCORED = 2     # Yahtzee filled with 50 (eligible for bonuses)
YAHTZEE_BONUS = 100    # Bonus points for each additional Yahtzee
YAHTZEE_CATEGORY = 11  # Category index for Yahtzee
NUM_YAHTZEE_STATUS = 3 # Number of yahtzee status values

# Precomputed tables (loaded from cache)
_TABLES = None
_TRANS = None
_SCORE_TABLE: List[List[int]] = None

# Joker mode cache (loaded separately)
_JOKER_TABLES = None
_JOKER_SCORE_TABLE = None


def _load_tables():
    """Load precomputed tables from cache."""
    global _TABLES
    if _TABLES is None:
        from precompute_fast import get_tables
        _TABLES = get_tables(verbose=False)
    return _TABLES


def _load_transitions():
    """Load transition arrays for fast numba computation."""
    global _TRANS
    if _TRANS is None:
        from precompute_fast import build_transition_arrays
        _TRANS = build_transition_arrays()
    return _TRANS


def _get_score_table():
    global _SCORE_TABLE
    if _SCORE_TABLE is None:
        tables = _load_tables()
        _SCORE_TABLE = tables['score_table'].tolist()
    return _SCORE_TABLE


# =============================================================================
# Numba-accelerated functions for fast v1/v2/v3 computation
# =============================================================================

@njit(cache=True)
def _compute_v3_all_rolls(mask, upper, score_table, ev_remaining):
    """Compute v3 for all 252 rolls for a given (mask, upper). Returns array[252]."""
    v3_arr = np.zeros(NUM_ROLLS, dtype=np.float64)

    # Find legal categories
    legal_cats = []
    for c in range(13):
        if not (mask & (1 << c)):
            legal_cats.append(c)

    for rid in range(NUM_ROLLS):
        best_ev = -1e9
        for i in range(len(legal_cats)):
            cat = legal_cats[i]
            pts = score_table[rid, cat]
            new_mask = mask | (1 << cat)
            new_upper = upper + pts if cat < 6 else upper
            if new_upper > 63:
                new_upper = 63
            ev = pts + ev_remaining[new_mask, new_upper]
            if ev > best_ev:
                best_ev = ev
        v3_arr[rid] = best_ev

    return v3_arr


@njit(cache=True)
def _compute_v2_all_rolls(v3_arr, num_keeps, trans_starts, trans_ends, trans_next, trans_prob):
    """Compute v2 for all 252 rolls given v3 array. Returns array[252]."""
    v2_arr = np.zeros(NUM_ROLLS, dtype=np.float64)

    for rid in range(NUM_ROLLS):
        best_ev = -1e9
        n_keeps = num_keeps[rid]

        for k in range(n_keeps):
            t_start = trans_starts[rid, k]
            t_end = trans_ends[rid, k]

            ev = 0.0
            for t in range(t_start, t_end):
                next_rid = trans_next[t]
                prob = trans_prob[t]
                ev += prob * v3_arr[next_rid]

            if ev > best_ev:
                best_ev = ev

        v2_arr[rid] = best_ev

    return v2_arr


@njit(cache=True)
def _compute_v1_all_rolls(v2_arr, num_keeps, trans_starts, trans_ends, trans_next, trans_prob):
    """Compute v1 for all 252 rolls given v2 array. Returns array[252]."""
    v1_arr = np.zeros(NUM_ROLLS, dtype=np.float64)

    for rid in range(NUM_ROLLS):
        best_ev = -1e9
        n_keeps = num_keeps[rid]

        for k in range(n_keeps):
            t_start = trans_starts[rid, k]
            t_end = trans_ends[rid, k]

            ev = 0.0
            for t in range(t_start, t_end):
                next_rid = trans_next[t]
                prob = trans_prob[t]
                ev += prob * v2_arr[next_rid]

            if ev > best_ev:
                best_ev = ev

        v1_arr[rid] = best_ev

    return v1_arr


@njit(cache=True)
def _find_best_keep(rid, target_arr, num_keeps, trans_starts, trans_ends, trans_next, trans_prob):
    """Find best keep index for a roll given target values. Returns (best_keep_idx, best_ev)."""
    best_ev = -1e9
    best_k = 0
    n_keeps = num_keeps[rid]

    for k in range(n_keeps):
        t_start = trans_starts[rid, k]
        t_end = trans_ends[rid, k]

        ev = 0.0
        for t in range(t_start, t_end):
            next_rid = trans_next[t]
            prob = trans_prob[t]
            ev += prob * target_arr[next_rid]

        if ev > best_ev:
            best_ev = ev
            best_k = k

    return best_k, best_ev


# Cache for v1/v2/v3 arrays by (mask, upper)
_v_cache = {}

def _get_v_arrays(mask: int, upper: int):
    """Get cached v1, v2, v3 arrays for a (mask, upper) state."""
    upper = min(upper, MAX_UPPER)
    key = (mask, upper)

    if key not in _v_cache:
        tables = _load_tables()
        trans = _load_transitions()

        v3_arr = _compute_v3_all_rolls(
            mask, upper,
            tables['score_table'],
            tables['ev_remaining']
        )
        v2_arr = _compute_v2_all_rolls(
            v3_arr,
            trans['num_keeps'],
            trans['trans_starts'],
            trans['trans_ends'],
            trans['trans_next'],
            trans['trans_prob']
        )
        v1_arr = _compute_v1_all_rolls(
            v2_arr,
            trans['num_keeps'],
            trans['trans_starts'],
            trans['trans_ends'],
            trans['trans_next'],
            trans['trans_prob']
        )

        _v_cache[key] = (v1_arr, v2_arr, v3_arr)

    return _v_cache[key]


def clamp_upper(upper: int) -> int:
    """Clamp upper subtotal to [0, 63] since we only care about bonus threshold."""
    return min(upper, MAX_UPPER)


def get_upper_contribution(cat: int, roll_idx: int) -> int:
    """Get the contribution to upper subtotal from scoring a category."""
    if not is_upper_category(cat):
        return 0
    return _get_score_table()[roll_idx][cat]


# =============================================================================
# Core DP Functions (using precomputed cache for instant lookups)
# =============================================================================

def ev_remaining(mask: int, upper: int) -> float:
    """
    Compute maximum expected remaining score from this state.

    Args:
        mask: 13-bit mask of filled categories
        upper: Upper section subtotal (clamped to 0-63)

    Returns:
        Expected additional points under optimal play
    """
    tables = _load_tables()
    upper = min(upper, MAX_UPPER)
    return float(tables['ev_remaining'][mask, upper])


def v3(roll_idx: int, mask: int, upper: int) -> float:
    """Best expected value after roll 3, must choose a category."""
    v1_arr, v2_arr, v3_arr = _get_v_arrays(mask, upper)
    return float(v3_arr[roll_idx])


def v2(roll_idx: int, mask: int, upper: int) -> float:
    """Best expected value after roll 2, before choosing what to keep."""
    v1_arr, v2_arr, v3_arr = _get_v_arrays(mask, upper)
    return float(v2_arr[roll_idx])


def v1(roll_idx: int, mask: int, upper: int) -> float:
    """Best expected value after roll 1, before choosing what to keep."""
    v1_arr, v2_arr, v3_arr = _get_v_arrays(mask, upper)
    return float(v1_arr[roll_idx])


# =============================================================================
# Policy Extraction Functions
# =============================================================================

def best_keep_roll1(roll_idx: int, mask: int, upper: int) -> Counts:
    """Get optimal keep decision after roll 1."""
    upper = min(upper, MAX_UPPER)
    v1_arr, v2_arr, v3_arr = _get_v_arrays(mask, upper)
    trans = _load_transitions()

    best_k, _ = _find_best_keep(
        roll_idx, v2_arr,
        trans['num_keeps'],
        trans['trans_starts'],
        trans['trans_ends'],
        trans['trans_next'],
        trans['trans_prob']
    )

    # Convert keep index back to Counts
    keeps = get_keep_options(roll_idx)
    return keeps[best_k]


def best_keep_roll2(roll_idx: int, mask: int, upper: int) -> Counts:
    """Get optimal keep decision after roll 2."""
    upper = min(upper, MAX_UPPER)
    v1_arr, v2_arr, v3_arr = _get_v_arrays(mask, upper)
    trans = _load_transitions()

    best_k, _ = _find_best_keep(
        roll_idx, v3_arr,
        trans['num_keeps'],
        trans['trans_starts'],
        trans['trans_ends'],
        trans['trans_next'],
        trans['trans_prob']
    )

    # Convert keep index back to Counts
    keeps = get_keep_options(roll_idx)
    return keeps[best_k]


def best_category(roll_idx: int, mask: int, upper: int) -> Tuple[int, float]:
    """
    Get optimal category to score and its expected value.

    Returns:
        (category_index, expected_value_including_future)
    """
    score_table = _get_score_table()
    legal_cats = get_legal_categories(mask)

    best_ev = float('-inf')
    best_cat = None

    for cat in legal_cats:
        pts = score_table[roll_idx][cat]

        new_mask = mask | (1 << cat)
        new_upper = upper
        if is_upper_category(cat):
            new_upper = clamp_upper(upper + pts)

        ev = pts + ev_remaining(new_mask, new_upper)

        if ev > best_ev:
            best_ev = ev
            best_cat = cat

    return best_cat, best_ev


def get_all_category_evs(roll_idx: int, mask: int, upper: int) -> List[Tuple[int, int, float]]:
    """
    Get expected values for all legal categories.

    Returns:
        List of (category, immediate_points, total_expected_value) sorted by EV
    """
    score_table = _get_score_table()
    legal_cats = get_legal_categories(mask)

    results = []
    for cat in legal_cats:
        pts = score_table[roll_idx][cat]

        new_mask = mask | (1 << cat)
        new_upper = upper
        if is_upper_category(cat):
            new_upper = clamp_upper(upper + pts)

        ev = pts + ev_remaining(new_mask, new_upper)
        results.append((cat, pts, ev))

    # Sort by EV descending
    results.sort(key=lambda x: -x[2])
    return results


# =============================================================================
# High-level API
# =============================================================================

def get_recommendation(dice: List[int], mask: int, upper: int,
                       rolls_remaining: int) -> Dict:
    """
    Get full recommendation for current game state.

    Args:
        dice: Current dice as list of values [1-6]
        mask: Filled categories bitmask
        upper: Upper section subtotal
        rolls_remaining: 2 (just rolled first), 1 (just rolled second), 0 (must score)

    Returns:
        Dict with recommendation details
    """
    from dice import dice_list_to_counts, counts_to_dice_list

    counts = dice_list_to_counts(dice)
    roll_idx = roll_id(counts)
    score_table = _get_score_table()

    result = {
        "dice": dice,
        "mask": mask,
        "upper": upper,
        "rolls_remaining": rolls_remaining,
    }

    if rolls_remaining == 2:
        # After roll 1
        keep = best_keep_roll1(roll_idx, mask, upper)
        result["action"] = "keep"
        result["keep_counts"] = keep
        result["keep_dice"] = counts_to_dice_list(keep)
        result["expected_value"] = v1(roll_idx, mask, upper)

    elif rolls_remaining == 1:
        # After roll 2
        keep = best_keep_roll2(roll_idx, mask, upper)
        result["action"] = "keep"
        result["keep_counts"] = keep
        result["keep_dice"] = counts_to_dice_list(keep)
        result["expected_value"] = v2(roll_idx, mask, upper)

    else:
        # Must score
        cat, ev = best_category(roll_idx, mask, upper)
        pts = score_table[roll_idx][cat]
        result["action"] = "score"
        result["category"] = cat
        result["category_name"] = CATEGORY_NAMES[cat]
        result["points"] = pts
        result["expected_value"] = ev

    # Add all category options
    result["category_options"] = [
        {
            "category": cat,
            "name": CATEGORY_NAMES[cat],
            "points": pts,
            "expected_value": ev
        }
        for cat, pts, ev in get_all_category_evs(roll_idx, mask, upper)
    ]

    return result


def warm_cache(verbose: bool = True):
    """
    Load precomputed EV tables from disk (or compute if cache doesn't exist).

    This is now instant if the cache file exists, or ~10 minutes on first run.
    """
    from precompute_fast import get_tables, CACHE_FILE

    if verbose:
        print("=" * 50)
        print("LOADING EV CACHE")
        print("=" * 50)

    tables = get_tables(verbose=verbose)

    if verbose:
        print(f"\nFresh game EV: {tables['ev_remaining'][0, 0]:.2f}")
        print("=" * 50)


def get_expected_score_fresh_game() -> float:
    """Get expected final score starting from empty scorecard."""
    return ev_remaining(0, 0)


# =============================================================================
# JOKER MODE FUNCTIONS
# =============================================================================

def _load_joker_tables():
    """Load precomputed joker mode tables from cache."""
    global _JOKER_TABLES, _JOKER_SCORE_TABLE
    if _JOKER_TABLES is None:
        import pickle
        from pathlib import Path

        cache_path = Path(__file__).parent / "ev_cache_joker.pkl"
        if not cache_path.exists():
            raise RuntimeError(
                f"Joker cache not found at {cache_path}. "
                "Run 'python precompute_joker.py' to generate it."
            )

        with open(cache_path, 'rb') as f:
            _JOKER_TABLES = pickle.load(f)

        _JOKER_SCORE_TABLE = _JOKER_TABLES['joker_score_table']

    return _JOKER_TABLES


def ev_remaining_joker(mask: int, upper: int, yahtzee_status: int) -> float:
    """
    Compute maximum expected remaining score in joker mode.

    Args:
        mask: 13-bit mask of filled categories
        upper: Upper section subtotal (clamped to 0-63)
        yahtzee_status: 0=unfilled, 1=scratched, 2=scored 50

    Returns:
        Expected additional points under optimal joker play
    """
    tables = _load_joker_tables()
    upper = min(upper, MAX_UPPER)
    return float(tables['ev_remaining'][mask, upper, yahtzee_status])


def best_category_joker(roll_idx: int, mask: int, upper: int,
                        yahtzee_status: int) -> Tuple[int, float]:
    """
    Get optimal category to score in joker mode.

    Handles:
    - Forced upper section when rolling another Yahtzee
    - Joker bonus (+100) for additional Yahtzees when eligible
    - Joker scoring exceptions (FH=25, SS=30, LS=40)

    Returns:
        (category_index, expected_value_including_future)
    """
    tables = _load_joker_tables()
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

    return best_cat, best_ev


def get_all_category_evs_joker(roll_idx: int, mask: int, upper: int,
                               yahtzee_status: int) -> List[Tuple[int, int, float, bool]]:
    """
    Get expected values for all legal categories in joker mode.

    Returns:
        List of (category, immediate_points, total_expected_value, is_forced)
        sorted by EV descending
    """
    tables = _load_joker_tables()
    is_ytz_arr = tables['is_yahtzee']
    ytz_face_arr = tables['yahtzee_face']
    score_table = tables['score_table']
    joker_score_table = tables['joker_score_table']
    ev_remaining_arr = tables['ev_remaining']

    is_ytz = is_ytz_arr[roll_idx]
    ytz_face = ytz_face_arr[roll_idx]

    joker_bonus = YAHTZEE_BONUS if (is_ytz and yahtzee_status == YAHTZEE_SCORED) else 0

    # Check for forced category
    forced_cat = None
    if is_ytz and yahtzee_status == YAHTZEE_SCORED:
        upper_cat = ytz_face
        if not (mask & (1 << upper_cat)):
            forced_cat = upper_cat

    legal_cats = get_legal_categories(mask)
    results = []

    for cat in legal_cats:
        is_forced = (forced_cat is not None and cat == forced_cat)

        # Skip non-forced categories if there's a forced one
        if forced_cat is not None and cat != forced_cat:
            continue

        # Use joker score table if eligible
        if is_ytz and yahtzee_status == YAHTZEE_SCORED:
            pts = int(joker_score_table[roll_idx, cat])
        else:
            pts = int(score_table[roll_idx, cat])

        new_mask = mask | (1 << cat)
        new_upper = min(MAX_UPPER, upper + pts) if is_upper_category(cat) else upper

        new_ys = yahtzee_status
        if cat == YAHTZEE_CATEGORY:
            new_ys = YAHTZEE_SCORED if pts == 50 else YAHTZEE_SCRATCHED

        future_ev = float(ev_remaining_arr[new_mask, new_upper, new_ys])
        ev = pts + joker_bonus + future_ev

        results.append((cat, pts, ev, is_forced))

    results.sort(key=lambda x: -x[2])
    return results


def get_recommendation_joker(dice: List[int], mask: int, upper: int,
                             rolls_remaining: int, yahtzee_status: int) -> Dict:
    """
    Get full recommendation for joker mode game state.

    Args:
        dice: Current dice as list of values [1-6]
        mask: Filled categories bitmask
        upper: Upper section subtotal
        rolls_remaining: 2 (roll 1), 1 (roll 2), 0 (must score)
        yahtzee_status: 0=unfilled, 1=scratched, 2=scored

    Returns:
        Dict with recommendation details including joker-specific info
    """
    from dice import dice_list_to_counts, counts_to_dice_list

    counts = dice_list_to_counts(dice)
    roll_idx = roll_id(counts)

    tables = _load_joker_tables()
    is_ytz_arr = tables['is_yahtzee']
    is_ytz = bool(is_ytz_arr[roll_idx])

    result = {
        "dice": dice,
        "mask": mask,
        "upper": upper,
        "rolls_remaining": rolls_remaining,
        "mode": "joker",
        "yahtzee_status": yahtzee_status,
        "is_yahtzee_roll": is_ytz,
        "joker_bonus_available": is_ytz and yahtzee_status == YAHTZEE_SCORED,
    }

    if rolls_remaining == 0:
        # Must score
        cat, ev = best_category_joker(roll_idx, mask, upper, yahtzee_status)
        forced_cat = get_forced_category_joker(roll_idx, mask) if (
            is_ytz and yahtzee_status == YAHTZEE_SCORED
        ) else None

        # Get actual points
        if is_ytz and yahtzee_status == YAHTZEE_SCORED:
            pts = int(tables['joker_score_table'][roll_idx, cat])
        else:
            pts = int(tables['score_table'][roll_idx, cat])

        result["action"] = "score"
        result["category"] = cat
        result["category_name"] = CATEGORY_NAMES[cat]
        result["points"] = pts
        result["expected_value"] = ev
        result["forced_category"] = forced_cat
        result["forced_category_name"] = CATEGORY_NAMES[forced_cat] if forced_cat is not None else None

        # Add joker bonus info
        if result["joker_bonus_available"]:
            result["joker_bonus"] = YAHTZEE_BONUS

    elif rolls_remaining in [1, 2]:
        # Need to recommend keep - use precomputed best keeps
        # For now, fall back to computing on-the-fly (Phase 3 will optimize)
        # TODO: Use precomputed best_keep arrays from joker cache

        # Compute v3 for this state
        v3_values = _compute_v3_joker_for_state(mask, upper, yahtzee_status, tables)

        if rolls_remaining == 1:
            # Find best keep for roll 2
            keep, ev = _find_best_keep_joker(roll_idx, v3_values, tables)
            result["expected_value"] = ev
        else:
            # Find best keep for roll 1 (need v2 first)
            v2_values = _compute_v2_joker_for_state(v3_values, tables)
            keep, ev = _find_best_keep_joker(roll_idx, v2_values, tables)
            result["expected_value"] = ev

        result["action"] = "keep"
        result["keep_counts"] = keep
        result["keep_dice"] = counts_to_dice_list(keep)

    # Add all category options
    result["category_options"] = [
        {
            "category": cat,
            "name": CATEGORY_NAMES[cat],
            "points": pts,
            "expected_value": ev,
            "is_forced": is_forced,
        }
        for cat, pts, ev, is_forced in get_all_category_evs_joker(
            roll_idx, mask, upper, yahtzee_status
        )
    ]

    return result


def _compute_v3_joker_for_state(mask: int, upper: int, yahtzee_status: int,
                                 tables: Dict) -> np.ndarray:
    """Compute v3 values for all rolls for a given joker state."""
    v3_arr = np.zeros(NUM_ROLLS, dtype=np.float64)

    is_ytz_arr = tables['is_yahtzee']
    ytz_face_arr = tables['yahtzee_face']
    score_table = tables['score_table']
    joker_score_table = tables['joker_score_table']
    ev_remaining_arr = tables['ev_remaining']

    legal_cats = get_legal_categories(mask)

    for rid in range(NUM_ROLLS):
        is_ytz = is_ytz_arr[rid]
        ytz_face = ytz_face_arr[rid]

        joker_bonus = YAHTZEE_BONUS if (is_ytz and yahtzee_status == YAHTZEE_SCORED) else 0

        # Check forced category
        forced_cat = None
        if is_ytz and yahtzee_status == YAHTZEE_SCORED:
            if not (mask & (1 << ytz_face)):
                forced_cat = ytz_face

        cats_to_check = [forced_cat] if forced_cat is not None else legal_cats
        best_ev = -1e9

        for cat in cats_to_check:
            if mask & (1 << cat):
                continue

            if is_ytz and yahtzee_status == YAHTZEE_SCORED:
                pts = joker_score_table[rid, cat]
            else:
                pts = score_table[rid, cat]

            new_mask = mask | (1 << cat)
            new_upper = min(MAX_UPPER, upper + pts) if cat < 6 else upper

            new_ys = yahtzee_status
            if cat == YAHTZEE_CATEGORY:
                new_ys = YAHTZEE_SCORED if pts == 50 else YAHTZEE_SCRATCHED

            ev = pts + joker_bonus + ev_remaining_arr[new_mask, new_upper, new_ys]
            if ev > best_ev:
                best_ev = ev

        v3_arr[rid] = best_ev

    return v3_arr


def _compute_v2_joker_for_state(v3_arr: np.ndarray, tables: Dict) -> np.ndarray:
    """Compute v2 values from v3 using transitions."""
    trans = _load_transitions()
    return _compute_v2_all_rolls(
        v3_arr,
        trans['num_keeps'],
        trans['trans_starts'],
        trans['trans_ends'],
        trans['trans_next'],
        trans['trans_prob']
    )


def _find_best_keep_joker(roll_idx: int, target_values: np.ndarray,
                          tables: Dict) -> Tuple[Counts, float]:
    """Find best keep for a roll given target values (v2 or v3)."""
    trans = _load_transitions()

    best_k, best_ev = _find_best_keep(
        roll_idx, target_values,
        trans['num_keeps'],
        trans['trans_starts'],
        trans['trans_ends'],
        trans['trans_next'],
        trans['trans_prob']
    )

    keeps = get_keep_options(roll_idx)
    return keeps[best_k], float(best_ev)


def warm_cache_joker(verbose: bool = True):
    """
    Load precomputed joker EV tables from disk.

    The cache must exist - run 'python precompute_joker.py' to generate it.
    """
    if verbose:
        print("=" * 50)
        print("LOADING JOKER MODE CACHE")
        print("=" * 50)

    try:
        tables = _load_joker_tables()
        if verbose:
            print(f"Cache version: {tables.get('version', 'unknown')}")
            print(f"Fresh game EV (joker): {tables['ev_remaining'][0, 0, 0]:.2f}")
            print("=" * 50)
    except RuntimeError as e:
        if verbose:
            print(f"ERROR: {e}")
        raise


def get_expected_score_fresh_game_joker() -> float:
    """Get expected final score in joker mode starting from empty scorecard."""
    return ev_remaining_joker(0, 0, YAHTZEE_UNFILLED)


if __name__ == "__main__":
    from dice import dice_list_to_counts, counts_to_dice_list

    print("Warming cache (this may take a minute)...")
    warm_cache()

    print(f"\nExpected score from fresh game: {get_expected_score_fresh_game():.2f}")

    # Test a specific situation
    print("\n" + "=" * 60)
    print("Test scenario: First roll of game")
    test_dice = [1, 1, 3, 5, 6]
    rec = get_recommendation(test_dice, mask=0, upper=0, rolls_remaining=2)

    print(f"Dice: {rec['dice']}")
    print(f"Recommended keep: {rec['keep_dice']}")
    print(f"Expected value: {rec['expected_value']:.2f}")

    print("\nAll category options if you scored now:")
    for opt in rec['category_options'][:5]:
        print(f"  {opt['name']}: {opt['points']} pts, EV={opt['expected_value']:.2f}")

    # Test mid-game scenario
    print("\n" + "=" * 60)
    print("Test scenario: Mid-game, have Yahtzee opportunity")
    yahtzee_dice = [4, 4, 4, 4, 3]
    # Assume some categories filled
    mid_mask = (1 << 0) | (1 << 6)  # Ones and 3-of-a-kind filled
    mid_upper = 3  # Got 3 in Ones

    rec2 = get_recommendation(yahtzee_dice, mask=mid_mask, upper=mid_upper, rolls_remaining=1)

    print(f"Dice: {rec2['dice']}")
    print(f"Filled: Ones, Three of a Kind")
    print(f"Recommended keep: {rec2['keep_dice']}")

    # What if we must score?
    rec3 = get_recommendation(yahtzee_dice, mask=mid_mask, upper=mid_upper, rolls_remaining=0)
    print(f"\nIf must score now: {rec3['category_name']} for {rec3['points']} pts")
