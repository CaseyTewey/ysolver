#!/usr/bin/env python3
"""
Joker Mode Precomputation using Numba JIT compilation.

This computes all Yahtzee Joker Mode optimal values.
State space is 3x larger due to yahtzee_status variable.

Estimated runtime: 30-60 minutes on modern hardware.
Output: ev_cache_joker.pkl (~400 MB)
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

# Joker-specific constants
YAHTZEE_UNFILLED = 0
YAHTZEE_SCRATCHED = 1
YAHTZEE_SCORED = 2
YAHTZEE_BONUS = 100
YAHTZEE_CATEGORY = 11
NUM_YAHTZEE_STATUS = 3

CACHE_FILE = Path(__file__).parent / "ev_cache_joker.pkl"


def build_joker_arrays():
    """
    Build arrays for joker-specific computations.

    Returns:
        - is_yahtzee: bool array[252] - True if roll is a Yahtzee
        - yahtzee_face: int8 array[252] - Face (0-5) if Yahtzee, -1 otherwise
        - score_table: int32 array[252, 13] - Normal scores
        - joker_score_table: int32 array[252, 13] - Joker exception scores
    """
    from dice import enumerate_rolls, id_to_roll
    from scoring import score, get_joker_score_table, Category

    rolls = enumerate_rolls()

    # Yahtzee detection arrays
    is_yahtzee = np.zeros(NUM_ROLLS, dtype=np.bool_)
    yahtzee_face = np.full(NUM_ROLLS, -1, dtype=np.int8)

    for i, counts in enumerate(rolls):
        if max(counts) == 5:
            is_yahtzee[i] = True
            for face, count in enumerate(counts):
                if count == 5:
                    yahtzee_face[i] = face
                    break

    # Score tables
    score_table = np.zeros((NUM_ROLLS, NUM_CATS), dtype=np.int32)
    for i, counts in enumerate(rolls):
        for cat in range(NUM_CATS):
            score_table[i, cat] = score(cat, counts)

    joker_score_table = get_joker_score_table().astype(np.int32)

    return {
        'is_yahtzee': is_yahtzee,
        'yahtzee_face': yahtzee_face,
        'score_table': score_table,
        'joker_score_table': joker_score_table,
    }


@njit(cache=True)
def compute_v3_joker_for_mask(mask, upper, yahtzee_status,
                               score_table, joker_score_table,
                               ev_remaining, is_yahtzee, yahtzee_face,
                               v3_out, best_cat_out):
    """Compute v3 for all rolls for a given (mask, upper, yahtzee_status)."""
    # Find legal categories
    legal_cats_arr = np.zeros(NUM_CATS, dtype=np.int32)
    n_legal = 0
    for c in range(NUM_CATS):
        if not (mask & (1 << c)):
            legal_cats_arr[n_legal] = c
            n_legal += 1

    for rid in range(NUM_ROLLS):
        is_ytz = is_yahtzee[rid]
        ytz_face = yahtzee_face[rid]

        # Joker bonus
        joker_bonus = YAHTZEE_BONUS if (is_ytz and yahtzee_status == YAHTZEE_SCORED) else 0

        # Check forced category (only when eligible for joker bonus)
        forced_cat = -1
        if is_ytz and yahtzee_status == YAHTZEE_SCORED and ytz_face >= 0:
            upper_cat = ytz_face
            if not (mask & (1 << upper_cat)):
                forced_cat = upper_cat

        best_ev = -1e9
        best_c = 0

        for i in range(n_legal):
            cat = legal_cats_arr[i]

            # Skip if forced to different category
            if forced_cat >= 0 and cat != forced_cat:
                continue

            # Get score using appropriate table
            if is_ytz and yahtzee_status == YAHTZEE_SCORED:
                pts = joker_score_table[rid, cat]
            else:
                pts = score_table[rid, cat]

            new_mask = mask | (1 << cat)
            new_upper = upper + pts if cat < 6 else upper
            if new_upper > MAX_UPPER:
                new_upper = MAX_UPPER

            # Update yahtzee status if scoring in yahtzee category
            new_ys = yahtzee_status
            if cat == YAHTZEE_CATEGORY:
                new_ys = YAHTZEE_SCORED if pts == 50 else YAHTZEE_SCRATCHED

            ev = pts + joker_bonus + ev_remaining[new_mask, new_upper, new_ys]
            if ev > best_ev:
                best_ev = ev
                best_c = cat

        v3_out[rid] = best_ev
        best_cat_out[rid] = best_c


@njit(cache=True)
def compute_v2_joker(v3, num_keeps, trans_starts, trans_ends, trans_next, trans_prob, v2_out):
    """Compute v2 for all rolls given v3 values."""
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
                ev += prob * v3[next_rid]

            if ev > best_ev:
                best_ev = ev

        v2_out[rid] = best_ev


@njit(cache=True)
def compute_v1_joker(v2, num_keeps, trans_starts, trans_ends, trans_next, trans_prob, v1_out):
    """Compute v1 for all rolls given v2 values."""
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
                ev += prob * v2[next_rid]

            if ev > best_ev:
                best_ev = ev

        v1_out[rid] = best_ev


@njit(cache=True)
def compute_turn_ev_joker(v1, initial_rolls):
    """Compute expected turn value."""
    n_init = len(initial_rolls)
    ev = 0.0
    for i in range(n_init):
        rid = int(initial_rolls[i, 0])
        prob = initial_rolls[i, 1]
        ev += prob * v1[rid]
    return ev


def precompute_joker(verbose=True):
    """
    Precompute joker mode EV tables using Numba JIT.

    State space: 8192 masks x 64 upper values x 3 yahtzee_status = 1,572,864 states
    """
    from precompute_fast import build_transition_arrays

    if verbose:
        print("=" * 60)
        print("JOKER MODE PRECOMPUTATION (Numba JIT)")
        print("=" * 60)
        print(f"\nCache file: {CACHE_FILE}")
        print(f"State space: {FULL_MASK + 1} x {MAX_UPPER + 1} x {NUM_YAHTZEE_STATUS}")
        sys.stdout.flush()

    # Step 1: Build arrays
    if verbose:
        print("\n[1/4] Building joker arrays...")
        sys.stdout.flush()
    start = time.time()
    joker_arrays = build_joker_arrays()
    if verbose:
        print(f"      Done in {time.time()-start:.1f}s")
        print(f"      Yahtzee rolls found: {joker_arrays['is_yahtzee'].sum()}")

    # Step 2: Build transition arrays
    if verbose:
        print("[2/4] Building transition arrays...")
        sys.stdout.flush()
    start = time.time()
    trans = build_transition_arrays()
    if verbose:
        print(f"      Done in {time.time()-start:.1f}s")

    # Step 3: Allocate arrays
    if verbose:
        print("[3/4] Allocating memory...")
        sys.stdout.flush()

    # Main EV array: (mask, upper, yahtzee_status)
    ev_remaining = np.zeros((FULL_MASK + 1, MAX_UPPER + 1, NUM_YAHTZEE_STATUS), dtype=np.float64)

    # Temporary arrays for single state computation
    v3_temp = np.zeros(NUM_ROLLS, dtype=np.float64)
    v2_temp = np.zeros(NUM_ROLLS, dtype=np.float64)
    v1_temp = np.zeros(NUM_ROLLS, dtype=np.float64)
    best_cat_temp = np.zeros(NUM_ROLLS, dtype=np.int8)

    # Base case: full mask
    for upper in range(MAX_UPPER + 1):
        for ys in range(NUM_YAHTZEE_STATUS):
            ev_remaining[FULL_MASK, upper, ys] = UPPER_BONUS if upper >= UPPER_THRESHOLD else 0.0

    # Group masks by popcount
    masks_by_bits = [[] for _ in range(NUM_CATS + 1)]
    for mask in range(FULL_MASK + 1):
        bits = bin(mask).count('1')
        masks_by_bits[bits].append(mask)

    # Total states to compute (excluding full mask)
    total_states = sum(len(m) for m in masks_by_bits[:-1]) * (MAX_UPPER + 1) * NUM_YAHTZEE_STATUS
    completed = 0

    if verbose:
        print(f"[4/4] Computing optimal values ({total_states:,} states)...")
        print("      (First run compiles JIT - subsequent runs are faster)")
        sys.stdout.flush()

    start_time = time.time()
    last_update = start_time

    # Process from most filled to least filled
    for num_filled in range(NUM_CATS - 1, -1, -1):
        masks = masks_by_bits[num_filled]

        for mask in masks:
            for upper in range(MAX_UPPER + 1):
                for yahtzee_status in range(NUM_YAHTZEE_STATUS):
                    # Compute v3
                    compute_v3_joker_for_mask(
                        mask, upper, yahtzee_status,
                        joker_arrays['score_table'],
                        joker_arrays['joker_score_table'],
                        ev_remaining,
                        joker_arrays['is_yahtzee'],
                        joker_arrays['yahtzee_face'],
                        v3_temp, best_cat_temp
                    )

                    # Compute v2
                    compute_v2_joker(
                        v3_temp, trans['num_keeps'],
                        trans['trans_starts'], trans['trans_ends'],
                        trans['trans_next'], trans['trans_prob'],
                        v2_temp
                    )

                    # Compute v1
                    compute_v1_joker(
                        v2_temp, trans['num_keeps'],
                        trans['trans_starts'], trans['trans_ends'],
                        trans['trans_next'], trans['trans_prob'],
                        v1_temp
                    )

                    # Compute turn EV
                    turn_ev = compute_turn_ev_joker(v1_temp, trans['initial_rolls'])

                    # Store in ev_remaining
                    ev_remaining[mask, upper, yahtzee_status] = turn_ev

                    completed += 1

                    # Progress update
                    if verbose:
                        now = time.time()
                        if now - last_update >= 1.0 or completed == total_states:
                            elapsed = now - start_time
                            pct = 100.0 * completed / total_states
                            rate = completed / elapsed if elapsed > 0 else 1
                            eta = (total_states - completed) / rate if rate > 0 else 0

                            bar_width = 30
                            filled_bar = int(bar_width * completed / total_states)
                            bar = "█" * filled_bar + "░" * (bar_width - filled_bar)

                            print(f"\r      [{bar}] {pct:5.1f}% | "
                                  f"Elapsed: {elapsed/60:.1f}m | ETA: {eta/60:.1f}m   ", end="")
                            sys.stdout.flush()
                            last_update = now

    total_time = time.time() - start_time

    if verbose:
        print(f"\n\n      Done in {total_time/60:.1f} minutes!")
        print(f"      Fresh game EV (joker, unfilled): {ev_remaining[0, 0, 0]:.2f}")
        print(f"      Fresh game EV (joker, scored):   {ev_remaining[0, 0, 2]:.2f}")

    return {
        'version': '2.0-joker',
        'mode': 'joker',
        'ev_remaining': ev_remaining,
        'score_table': joker_arrays['score_table'],
        'joker_score_table': joker_arrays['joker_score_table'],
        'is_yahtzee': joker_arrays['is_yahtzee'],
        'yahtzee_face': joker_arrays['yahtzee_face'],
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


def get_joker_tables(force_recompute=False, verbose=True):
    """Get joker tables, computing if necessary."""
    if not force_recompute and CACHE_FILE.exists():
        if verbose:
            print(f"Loading cached joker tables from {CACHE_FILE}...")
        tables = load_cache()
        if verbose:
            print(f"Loaded! Fresh game EV (joker): {tables['ev_remaining'][0, 0, 0]:.2f}")
        return tables

    tables = precompute_joker(verbose=verbose)
    save_cache(tables)
    return tables


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Precompute Yahtzee Joker Mode EV tables")
    parser.add_argument("--force", action="store_true", help="Force recomputation")
    args = parser.parse_args()

    tables = get_joker_tables(force_recompute=args.force)

    print("\n" + "=" * 60)
    print("VALIDATION")
    print("=" * 60)
    ev_unfilled = tables['ev_remaining'][0, 0, YAHTZEE_UNFILLED]
    ev_scored = tables['ev_remaining'][0, 0, YAHTZEE_SCORED]

    print(f"Expected score from fresh game (yahtzee unfilled): {ev_unfilled:.2f}")
    print(f"Expected score from fresh game (yahtzee scored):   {ev_scored:.2f}")
    print(f"(Literature value for traditional: ~254-255)")
    print(f"(Joker mode should be slightly higher due to bonus potential)")

    if 250 < ev_unfilled < 270:
        print("\nStatus: LOOKS CORRECT!")
    else:
        print(f"\nStatus: WARNING - value {ev_unfilled:.2f} outside expected range 250-270")
