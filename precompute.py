#!/usr/bin/env python3
"""
Precompute and cache EV tables to disk.

This script computes all optimal Yahtzee values ONCE and saves them.
Subsequent solver runs load instantly from the cache.

The computation uses numpy arrays instead of lru_cache for speed.
"""

import numpy as np
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


def precompute_all_tables(verbose=True):
    """
    Precompute all EV tables using numpy for speed.

    Returns dict with:
    - ev_remaining[mask, upper]: expected remaining score
    - v3[roll, mask, upper]: best EV after final roll
    - best_cat[roll, mask, upper]: best category to score
    """
    from dice import enumerate_rolls, id_to_roll
    from scoring import get_score_table, is_upper_category, NUM_CATEGORIES
    from transitions import get_keep_options, get_transition_dist, get_initial_roll_dist, precompute_all

    if verbose:
        print("=" * 60)
        print("PRECOMPUTING YAHTZEE OPTIMAL PLAY TABLES")
        print("=" * 60)
        print(f"\nThis is a ONE-TIME computation. Results are saved to disk.")
        print(f"Cache file: {CACHE_FILE}\n")

    # Step 1: Precompute transitions
    if verbose:
        print("[1/4] Precomputing dice transitions...")
        sys.stdout.flush()
    precompute_all()
    if verbose:
        print("      Done!")

    # Step 2: Get precomputed data structures
    if verbose:
        print("[2/4] Loading score tables...")
        sys.stdout.flush()

    score_table = np.array(get_score_table(), dtype=np.int32)  # [252, 13]
    all_rolls = enumerate_rolls()
    initial_dist = get_initial_roll_dist()  # [(roll_id, prob), ...]

    # Build transition matrices for each keep decision
    # For speed, we'll compute on-the-fly but cache keep options
    keep_options_by_roll = {}
    for rid in range(NUM_ROLLS):
        keep_options_by_roll[rid] = get_keep_options(rid)

    if verbose:
        print("      Done!")

    # Step 3: Allocate arrays
    if verbose:
        print("[3/4] Allocating arrays...")
        sys.stdout.flush()

    # ev_remaining[mask, upper] - we'll compute this
    ev_remaining = np.zeros((FULL_MASK + 1, MAX_UPPER + 1), dtype=np.float64)

    # v3[roll, mask, upper] - best value after final roll
    v3 = np.zeros((NUM_ROLLS, FULL_MASK + 1, MAX_UPPER + 1), dtype=np.float64)

    # best_cat[roll, mask, upper] - which category to score
    best_cat = np.zeros((NUM_ROLLS, FULL_MASK + 1, MAX_UPPER + 1), dtype=np.int8)

    if verbose:
        print("      Done!")
        print(f"      Memory: ~{(ev_remaining.nbytes + v3.nbytes + best_cat.nbytes) / 1e9:.2f} GB")

    # Step 4: Compute DP tables
    if verbose:
        print("\n[4/4] Computing optimal values...")
        print("      This is the slow part. Progress shown below.\n")
        sys.stdout.flush()

    start_time = time.time()
    last_update = start_time

    # Base case: full mask
    for upper in range(MAX_UPPER + 1):
        ev_remaining[FULL_MASK, upper] = UPPER_BONUS if upper >= UPPER_THRESHOLD else 0.0

    # Count masks by number of bits set (for progress)
    masks_by_bits = [[] for _ in range(NUM_CATS + 1)]
    for mask in range(FULL_MASK + 1):
        bits = bin(mask).count('1')
        masks_by_bits[bits].append(mask)

    total_work = sum(len(masks) for masks in masks_by_bits[:-1])  # Exclude full mask
    completed = 0

    # Process from most filled to least filled
    for num_filled in range(NUM_CATS - 1, -1, -1):
        masks_to_process = masks_by_bits[num_filled]

        for mask in masks_to_process:
            # Legal categories for this mask
            legal_cats = [c for c in range(NUM_CATS) if not (mask & (1 << c))]

            for upper in range(MAX_UPPER + 1):
                # Compute v3 for all rolls
                for rid in range(NUM_ROLLS):
                    best_ev = -1e9
                    best_c = -1

                    for cat in legal_cats:
                        pts = score_table[rid, cat]
                        new_mask = mask | (1 << cat)
                        new_upper = min(MAX_UPPER, upper + pts) if cat < 6 else upper

                        ev = pts + ev_remaining[new_mask, new_upper]
                        if ev > best_ev:
                            best_ev = ev
                            best_c = cat

                    v3[rid, mask, upper] = best_ev
                    best_cat[rid, mask, upper] = best_c

                # Compute v2 for all rolls (max over keeps of E[v3])
                v2_values = np.zeros(NUM_ROLLS, dtype=np.float64)
                for rid in range(NUM_ROLLS):
                    best_ev = -1e9
                    for keep in keep_options_by_roll[rid]:
                        ev = 0.0
                        for next_rid, prob in get_transition_dist(rid, keep):
                            ev += prob * v3[next_rid, mask, upper]
                        if ev > best_ev:
                            best_ev = ev
                    v2_values[rid] = best_ev

                # Compute v1 for all rolls (max over keeps of E[v2])
                v1_values = np.zeros(NUM_ROLLS, dtype=np.float64)
                for rid in range(NUM_ROLLS):
                    best_ev = -1e9
                    for keep in keep_options_by_roll[rid]:
                        ev = 0.0
                        for next_rid, prob in get_transition_dist(rid, keep):
                            ev += prob * v2_values[next_rid]
                        if ev > best_ev:
                            best_ev = ev
                    v1_values[rid] = best_ev

                # Compute ev_remaining (E[v1] over initial roll)
                turn_ev = 0.0
                for rid, prob in initial_dist:
                    turn_ev += prob * v1_values[rid]

                ev_remaining[mask, upper] = turn_ev

            completed += 1

            # Progress update
            if verbose:
                now = time.time()
                if now - last_update >= 1.0 or completed == total_work:
                    elapsed = now - start_time
                    pct = 100.0 * completed / total_work
                    rate = completed / elapsed if elapsed > 0 else 0
                    eta = (total_work - completed) / rate if rate > 0 else 0

                    bar_width = 30
                    filled = int(bar_width * completed / total_work)
                    bar = "█" * filled + "░" * (bar_width - filled)

                    # Show current mask info
                    cats_left = NUM_CATS - num_filled

                    print(f"\r      [{bar}] {pct:5.1f}% | {cats_left} cats left | "
                          f"Elapsed: {elapsed/60:.1f}m | ETA: {eta/60:.1f}m   ", end="")
                    sys.stdout.flush()
                    last_update = now

    total_time = time.time() - start_time

    if verbose:
        print(f"\n\n      Computation complete in {total_time/60:.1f} minutes!")
        print(f"      Fresh game EV: {ev_remaining[0, 0]:.2f}")

    return {
        'ev_remaining': ev_remaining,
        'v3': v3,
        'best_cat': best_cat,
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

    tables = precompute_all_tables(verbose=verbose)
    save_cache(tables)
    return tables


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Precompute Yahtzee EV tables")
    parser.add_argument("--force", action="store_true", help="Force recomputation")
    args = parser.parse_args()

    tables = get_tables(force_recompute=args.force)

    print("\n" + "=" * 60)
    print("VALIDATION")
    print("=" * 60)
    print(f"Expected score from fresh game: {tables['ev_remaining'][0, 0]:.2f}")
    print(f"(Literature value: ~254-255)")

    ev = tables['ev_remaining'][0, 0]
    if 250 < ev < 260:
        print("Status: LOOKS CORRECT!")
    else:
        print("Status: WARNING - outside expected range")
