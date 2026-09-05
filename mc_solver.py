"""Reproducible Monte Carlo match estimates under optimal expected-score play.

Each sample pairs two independent complete games. The solver chooses keeps and
categories from exact Bellman continuation values; it does not use a normal
approximation or optimize match-winning probability. Wilson intervals describe
sampling uncertainty for each outcome separately, not model/policy uncertainty.

``locked`` includes recorded category scores and earned Yahtzee bonuses, but
excludes the upper bonus. The simulation adds that bonus at the terminal state.
Only immutable solver inputs are cached here; callers own request caching and
admission control.
"""

from functools import lru_cache
import hashlib
import json
import math
from numbers import Integral

import numpy as np
from numba import njit

from ev_solver import _load_joker_tables, validate_solver_state
from precompute_fast import build_reroll_lattice
from precompute_joker import CACHE_VERSION, compute_v3_joker_for_mask

MC_VERSION = 'score-optimal-mc-v1:' + CACHE_VERSION
DEFAULT_SAMPLE_COUNT = 10_000
MAX_SAMPLE_COUNT = 100_000
CONFIDENCE_LEVEL = 0.95
_Z_95 = 1.959963984540054


def _integer(value, label, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, Integral) or not minimum <= value <= maximum:
        raise ValueError(f'{label} must be an integer from {minimum} to {maximum}')
    return int(value)


def _state(locked, mask, upper, status):
    locked = _integer(locked, 'locked', 0, 1540)
    mask = _integer(mask, 'mask', 0, 8191)
    upper = _integer(upper, 'upper', 0, 105)
    status = _integer(status, 'yahtzee_status', 0, 2)
    validate_solver_state(mask, upper, status)
    return locked, mask, min(upper, 63), status


@lru_cache(maxsize=1)
def _runtime_arguments():
    """One immutable snapshot of the validated tables and partial-hand graph."""
    tables = _load_joker_tables()
    arrays = [tables[key] for key in ('score_table', 'joker_score_table',
              'ev_remaining', 'is_yahtzee', 'yahtzee_face')]
    children, parents, full_start = build_reroll_lattice()
    result = []
    for array in arrays + [children, parents]:
        readonly = np.array(array, copy=True)
        readonly.setflags(write=False)
        result.append(readonly)
    return (*result, full_start)


def _canonical_seeds(first, second, sample_count):
    """Stable across processes, hash seeds, request order, and Python versions."""
    payload = json.dumps([MC_VERSION, sample_count, first, second], separators=(',', ':'))
    digest = hashlib.sha256(payload.encode('ascii')).digest()
    first_seed = int.from_bytes(digest[:4], 'big')
    second_seed = int.from_bytes(digest[4:8], 'big')
    if second_seed == first_seed:
        second_seed ^= 0x9E3779B9
    return first_seed, second_seed


@njit(cache=True, nogil=True)
def _optimal_keeps(values, children, parents, full_start, out_values, out_keeps):
    """Propagate exact reroll expectations and their chosen kept partial hand."""
    expected = np.empty(children.shape[0], dtype=np.float64)
    best_keep = np.arange(children.shape[0], dtype=np.int32)
    expected[full_start:] = values
    for node in range(full_start - 1, -1, -1):
        total = 0.0
        for face in range(6):
            total += expected[children[node, face]]
        expected[node] = total / 6.0
    for node in range(1, len(expected)):
        for face in range(6):
            parent = parents[node, face]
            if parent >= 0 and expected[parent] > expected[node]:
                expected[node] = expected[parent]
                best_keep[node] = best_keep[parent]
    out_values[:] = expected[full_start:]
    out_keeps[:] = best_keep[full_start:]


@njit(cache=True, nogil=True)
def _roll_from_keep(keep_node, children, full_start):
    node = keep_node
    while node < full_start:
        # Each edge adds one independent, uniformly distributed physical die.
        node = children[node, np.random.randint(0, 6)]
    return node - full_start


@njit(cache=True, nogil=True)
def _simulate_player(n, seed, initial_mask, initial_upper, initial_status, locked,
                     score_table, joker_score_table, continuation, is_yahtzee,
                     yahtzee_face, children, parents, full_start):
    """Generate actual final scores, releasing the GIL throughout computation."""
    np.random.seed(seed)
    totals = np.empty(n, dtype=np.int32)
    v3 = np.empty(252, dtype=np.float64)
    v2 = np.empty(252, dtype=np.float64)
    v1 = np.empty(252, dtype=np.float64)
    categories = np.empty(252, dtype=np.int8)
    keep1 = np.empty(252, dtype=np.int32)
    keep2 = np.empty(252, dtype=np.int32)
    for game in range(n):
        mask, upper, status, total = initial_mask, initial_upper, initial_status, locked
        while mask != 8191:
            compute_v3_joker_for_mask(mask, upper, status, score_table,
                joker_score_table, continuation, is_yahtzee, yahtzee_face, v3, categories)
            _optimal_keeps(v3, children, parents, full_start, v2, keep2)
            _optimal_keeps(v2, children, parents, full_start, v1, keep1)
            roll1 = _roll_from_keep(0, children, full_start)
            roll2 = _roll_from_keep(keep1[roll1], children, full_start)
            roll3 = _roll_from_keep(keep2[roll2], children, full_start)
            category = int(categories[roll3])
            joker_active = is_yahtzee[roll3] and status != 0
            points = int(joker_score_table[roll3, category] if joker_active
                         else score_table[roll3, category])
            if is_yahtzee[roll3] and status == 2:
                total += 100
            total += points
            mask |= 1 << category
            if category < 6:
                upper = min(63, upper + points)
            if category == 11:
                status = 2 if points == 50 else 1
        totals[game] = total + (35 if upper == 63 else 0)
    return totals


def _wilson_interval(count, sample_count):
    probability = count / sample_count
    z2 = _Z_95 * _Z_95
    denominator = 1 + z2 / sample_count
    center = (probability + z2 / (2 * sample_count)) / denominator
    radius = _Z_95 * math.sqrt(probability * (1-probability) / sample_count
                              + z2 / (4*sample_count*sample_count)) / denominator
    return max(0.0, center-radius), min(1.0, center+radius)


def simulate_match(p1_locked, p1_mask, p1_upper, p1_status,
                   p2_locked, p2_mask, p2_upper, p2_status,
                   sample_count=DEFAULT_SAMPLE_COUNT):
    """Estimate (player-one win, tie, player-two win), with 95% intervals.

    Distinct player states are canonicalized before seed selection and sampling,
    so reversing a match exactly reverses its estimates and confidence bounds.
    Equal states use distinct random streams, including when both are fresh.
    The default 10,000 independent paired samples bounds the largest reported
    Wilson endpoint distance below one percentage point for every outcome.
    """
    sample_count = _integer(sample_count, 'sample_count', 1, MAX_SAMPLE_COUNT)
    first = _state(p1_locked, p1_mask, p1_upper, p1_status)
    second = _state(p2_locked, p2_mask, p2_upper, p2_status)
    reverse = first > second
    if reverse:
        first, second = second, first
    seeds = _canonical_seeds(first, second, sample_count)
    runtime = _runtime_arguments()
    first_scores = _simulate_player(sample_count, seeds[0], first[1], first[2], first[3], first[0], *runtime)
    second_scores = _simulate_player(sample_count, seeds[1], second[1], second[2], second[3], second[0], *runtime)
    if reverse:
        first_scores, second_scores = second_scores, first_scores
        seeds = seeds[::-1]
    counts = (int(np.count_nonzero(first_scores > second_scores)),
              int(np.count_nonzero(first_scores == second_scores)),
              int(np.count_nonzero(first_scores < second_scores)))
    probabilities = tuple(count / sample_count for count in counts)
    intervals = tuple(_wilson_interval(count, sample_count) for count in counts)
    margin = 100 * max(max(probability-low, high-probability)
                       for probability, (low, high) in zip(probabilities, intervals))
    return {
        'probabilities': probabilities,
        'counts': counts,
        'intervals': intervals,
        'sample_count': sample_count,
        'confidence_level': CONFIDENCE_LEVEL,
        'max_margin_percentage_points': margin,
        'seeds': seeds,
        'simulation_version': MC_VERSION,
        'means': (float(first_scores.mean()), float(second_scores.mean())),
        'standard_deviations': (float(first_scores.std()), float(second_scores.std())),
    }
