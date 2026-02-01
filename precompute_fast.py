#!/usr/bin/env python3
"""
FAST precomputation using Numba JIT compilation.

This computes all Yahtzee optimal values in ~2-5 minutes instead of hours.
"""

import numpy as np
from numba import njit, prange
import pickle
import os
import time
import sys
from pathlib import Path

# Constants
NUM_CATS = 13
FULL_MASK = (1 << NUM_CATS) - 1
MAX_UPPER = 63
NUM_ROLLS = 252
UPPER_BONUS = 35
UPPER_THRESHOLD = 63

CACHE_FILE = Path(__file__).parent / "ev_cache.pkl"


def build_transition_arrays():
    """
    Build numpy arrays for transitions that numba can use efficiently.

    Returns:
        - initial_rolls: array of (roll_id, probability) for initial roll
        - keep_starts[rid]: start index in keep_data for roll rid
        - keep_ends[rid]: end index in keep_data for roll rid
        - keep_data: flattened array of keep options
        - trans_starts[rid, keep_idx]: start in trans_data
        - trans_ends[rid, keep_idx]: end in trans_data
        - trans_next: next roll ids
        - trans_prob: transition probabilities
    """
    from dice import enumerate_rolls
    from transitions import get_keep_options, get_transition_dist, get_initial_roll_dist, precompute_all

    precompute_all()

    # Initial roll distribution
    init_dist = get_initial_roll_dist()
    initial_rolls = np.array([(rid, prob) for rid, prob in init_dist], dtype=np.float64)

    # Build keep options and transitions
    all_keeps = []
    keep_starts = np.zeros(NUM_ROLLS, dtype=np.int32)
    keep_ends = np.zeros(NUM_ROLLS, dtype=np.int32)

    all_trans_next = []
    all_trans_prob = []
    trans_starts = []
    trans_ends = []

    for rid in range(NUM_ROLLS):
        keeps = get_keep_options(rid)
        keep_starts[rid] = len(all_keeps)

        rid_trans_starts = []
        rid_trans_ends = []

        for keep in keeps:
            all_keeps.append(keep)
            dist = get_transition_dist(rid, keep)

            rid_trans_starts.append(len(all_trans_next))
            for next_rid, prob in dist:
                all_trans_next.append(next_rid)
                all_trans_prob.append(prob)
            rid_trans_ends.append(len(all_trans_next))

        keep_ends[rid] = len(all_keeps)
        trans_starts.append(rid_trans_starts)
        trans_ends.append(rid_trans_ends)

    # Flatten keeps (we just need count, not the actual values for now)
    num_keeps = np.array([keep_ends[i] - keep_starts[i] for i in range(NUM_ROLLS)], dtype=np.int32)

    # Build 2D arrays for transitions
    max_keeps = max(num_keeps)
    trans_starts_arr = np.zeros((NUM_ROLLS, max_keeps), dtype=np.int32)
    trans_ends_arr = np.zeros((NUM_ROLLS, max_keeps), dtype=np.int32)

    for rid in range(NUM_ROLLS):
        for k, (s, e) in enumerate(zip(trans_starts[rid], trans_ends[rid])):
            trans_starts_arr[rid, k] = s
            trans_ends_arr[rid, k] = e

    return {
        'initial_rolls': initial_rolls,
        'num_keeps': num_keeps,
        'trans_starts': trans_starts_arr,
        'trans_ends': trans_ends_arr,
        'trans_next': np.array(all_trans_next, dtype=np.int32),
        'trans_prob': np.array(all_trans_prob, dtype=np.float64),
    }


@njit(cache=True)
def compute_v3_for_mask(mask, score_table, ev_remaining, v3_out, best_cat_out):
    """Compute v3 for all rolls and upper values for a given mask."""
    # Find legal categories
    legal_cats = []
    for c in range(NUM_CATS):
        if not (mask & (1 << c)):
            legal_cats.append(c)
    n_legal = len(legal_cats)

    for upper in range(MAX_UPPER + 1):
        for rid in range(NUM_ROLLS):
            best_ev = -1e9
            best_c = 0

            for i in range(n_legal):
                cat = legal_cats[i]
                pts = score_table[rid, cat]
                new_mask = mask | (1 << cat)
                new_upper = upper + pts if cat < 6 else upper
                if new_upper > MAX_UPPER:
                    new_upper = MAX_UPPER

                ev = pts + ev_remaining[new_mask, new_upper]
                if ev > best_ev:
                    best_ev = ev
                    best_c = cat

            v3_out[rid, upper] = best_ev
            best_cat_out[rid, upper] = best_c


@njit(cache=True)
def compute_v2_for_mask(v3, num_keeps, trans_starts, trans_ends, trans_next, trans_prob, v2_out):
    """Compute v2 for all rolls and upper values for a given mask."""
    for upper in range(MAX_UPPER + 1):
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
                    ev += prob * v3[next_rid, upper]

                if ev > best_ev:
                    best_ev = ev

            v2_out[rid, upper] = best_ev


@njit(cache=True)
def compute_v1_for_mask(v2, num_keeps, trans_starts, trans_ends, trans_next, trans_prob, v1_out):
    """Compute v1 for all rolls and upper values for a given mask."""
    for upper in range(MAX_UPPER + 1):
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
                    ev += prob * v2[next_rid, upper]

                if ev > best_ev:
                    best_ev = ev

            v1_out[rid, upper] = best_ev


@njit(cache=True)
def compute_turn_ev(v1, initial_rolls, turn_ev_out):
    """Compute expected turn value for all upper values."""
    n_init = len(initial_rolls)

    for upper in range(MAX_UPPER + 1):
        ev = 0.0
        for i in range(n_init):
            rid = int(initial_rolls[i, 0])
            prob = initial_rolls[i, 1]
            ev += prob * v1[rid, upper]
        turn_ev_out[upper] = ev


def precompute_fast(verbose=True):
    """
    Fast precomputation using numba.
    """
    from scoring import get_score_table

    if verbose:
        print("=" * 60)
        print("FAST PRECOMPUTATION (Numba JIT)")
        print("=" * 60)
        print(f"\nCache file: {CACHE_FILE}")
        sys.stdout.flush()

    # Step 1: Build transition arrays
    if verbose:
        print("\n[1/3] Building transition arrays...")
        sys.stdout.flush()
    start = time.time()
    trans = build_transition_arrays()
    if verbose:
        print(f"      Done in {time.time()-start:.1f}s")

    # Step 2: Get score table
    if verbose:
        print("[2/3] Loading score table...")
        sys.stdout.flush()
    score_table = np.array(get_score_table(), dtype=np.int32)

    # Step 3: Allocate arrays
    if verbose:
        print("[3/3] Computing optimal values...")
        print("      (First run compiles JIT - subsequent runs are faster)")
        sys.stdout.flush()

    ev_remaining = np.zeros((FULL_MASK + 1, MAX_UPPER + 1), dtype=np.float64)
    v3_temp = np.zeros((NUM_ROLLS, MAX_UPPER + 1), dtype=np.float64)
    v2_temp = np.zeros((NUM_ROLLS, MAX_UPPER + 1), dtype=np.float64)
    v1_temp = np.zeros((NUM_ROLLS, MAX_UPPER + 1), dtype=np.float64)
    best_cat_temp = np.zeros((NUM_ROLLS, MAX_UPPER + 1), dtype=np.int8)
    turn_ev_temp = np.zeros(MAX_UPPER + 1, dtype=np.float64)

    # Store best_cat for all masks (needed for recommendations)
    best_cat_all = np.zeros((NUM_ROLLS, FULL_MASK + 1, MAX_UPPER + 1), dtype=np.int8)

    # Base case: full mask
    for upper in range(MAX_UPPER + 1):
        ev_remaining[FULL_MASK, upper] = UPPER_BONUS if upper >= UPPER_THRESHOLD else 0.0

    # Group masks by popcount
    masks_by_bits = [[] for _ in range(NUM_CATS + 1)]
    for mask in range(FULL_MASK + 1):
        bits = bin(mask).count('1')
        masks_by_bits[bits].append(mask)

    total_masks = sum(len(m) for m in masks_by_bits[:-1])
    completed = 0
    start_time = time.time()
    last_update = start_time

    # Process from most filled to least filled
    for num_filled in range(NUM_CATS - 1, -1, -1):
        masks = masks_by_bits[num_filled]

        for mask in masks:
            # Compute v3
            compute_v3_for_mask(mask, score_table, ev_remaining, v3_temp, best_cat_temp)
            best_cat_all[:, mask, :] = best_cat_temp

            # Compute v2
            compute_v2_for_mask(v3_temp, trans['num_keeps'],
                               trans['trans_starts'], trans['trans_ends'],
                               trans['trans_next'], trans['trans_prob'], v2_temp)

            # Compute v1
            compute_v1_for_mask(v2_temp, trans['num_keeps'],
                               trans['trans_starts'], trans['trans_ends'],
                               trans['trans_next'], trans['trans_prob'], v1_temp)

            # Compute turn EV
            compute_turn_ev(v1_temp, trans['initial_rolls'], turn_ev_temp)

            # Store in ev_remaining
            ev_remaining[mask, :] = turn_ev_temp

            completed += 1

            # Progress
            if verbose:
                now = time.time()
                if now - last_update >= 0.5 or completed == total_masks:
                    elapsed = now - start_time
                    pct = 100.0 * completed / total_masks
                    rate = completed / elapsed if elapsed > 0 else 1
                    eta = (total_masks - completed) / rate if rate > 0 else 0

                    bar_width = 30
                    filled_bar = int(bar_width * completed / total_masks)
                    bar = "█" * filled_bar + "░" * (bar_width - filled_bar)

                    print(f"\r      [{bar}] {pct:5.1f}% | "
                          f"Elapsed: {elapsed:.0f}s | ETA: {eta:.0f}s   ", end="")
                    sys.stdout.flush()
                    last_update = now

    total_time = time.time() - start_time

    if verbose:
        print(f"\n\n      Done in {total_time:.1f} seconds!")
        print(f"      Fresh game EV: {ev_remaining[0, 0]:.2f}")

    return {
        'ev_remaining': ev_remaining,
        'best_cat': best_cat_all,
        'score_table': score_table,
    }


def save_cache(tables, filepath=CACHE_FILE):
    """Save computed tables to disk."""
    print(f"\nSaving cache to {filepath}...")
    with open(filepath, 'wb') as f:
        pickle.dump(tables, f, protocol=pickle.HIGHEST_PROTOCOL)
    size_mb = os.path.getsize(filepath) / 1e6
    print(f"Saved! ({size_mb:.1f} MB)")


def load_cache(filepath=CACHE_FILE):
    """Load computed tables from disk."""
    if not filepath.exists():
        return None
    with open(filepath, 'rb') as f:
        return pickle.load(f)


def get_tables(force_recompute=False, verbose=True):
    """Get tables, computing if necessary."""
    if not force_recompute and CACHE_FILE.exists():
        if verbose:
            print(f"Loading cached tables from {CACHE_FILE}...")
        tables = load_cache()
        if verbose:
            print(f"Loaded! Fresh game EV: {tables['ev_remaining'][0, 0]:.2f}")
        return tables

    tables = precompute_fast(verbose=verbose)
    save_cache(tables)
    return tables


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Fast precompute Yahtzee EV tables")
    parser.add_argument("--force", action="store_true", help="Force recomputation")
    args = parser.parse_args()

    tables = get_tables(force_recompute=args.force)

    print("\n" + "=" * 60)
    print("VALIDATION")
    print("=" * 60)
    ev = tables['ev_remaining'][0, 0]
    print(f"Expected score from fresh game: {ev:.2f}")
    print(f"(Literature value: ~254-255)")

    if 250 < ev < 260:
        print("Status: LOOKS CORRECT!")
    else:
        print(f"Status: WARNING - value {ev:.2f} outside expected range 250-260")
