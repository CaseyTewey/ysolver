"""Independent ordered-dice reference tests for scoring and optimal play.

Run: python -m unittest test_solver_regressions -v
The reference enumerates physical dice and every positional keep subset. It
shares neither the production multinomial formula nor its partial-hand lattice.
"""
from collections import Counter
from functools import lru_cache
from itertools import combinations, product
from math import comb
import pickle
from pathlib import Path
import tempfile
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock
import unittest
from unittest.mock import patch

import numpy as np
from scipy.sparse import csr_matrix

import dice
import ev_solver as solver
import scoring
import transitions
from precompute_fast import build_reroll_lattice, compute_reroll_lattice
from precompute_joker import CACHE_VERSION, load_cache

FULL = (1 << 13) - 1
FACES = range(1, 7)


def counts(hand):
    return tuple(hand.count(face) for face in FACES)


def reference_score(cat, hand, joker=False):
    """Direct scorecard rules expressed using physical die values."""
    freq = Counter(hand)
    if cat < 6:
        return (cat + 1) * freq[cat + 1]
    if cat == 6:
        return sum(hand) if max(freq.values()) >= 3 else 0
    if cat == 7:
        return sum(hand) if max(freq.values()) >= 4 else 0
    if cat == 8:
        return 25 if sorted(freq.values()) == [2, 3] or joker else 0
    if cat == 9:
        return 30 if any(set(range(n, n + 4)) <= set(hand) for n in (1, 2, 3)) or joker else 0
    if cat == 10:
        return 40 if len(freq) == 5 and max(hand) - min(hand) == 4 or joker else 0
    if cat == 11:
        return 50 if len(freq) == 1 else 0
    return sum(hand)


def reference_legal(hand, mask, status):
    available = [cat for cat in range(13) if not mask & (1 << cat)]
    if status in (1, 2) and len(set(hand)) == 1:
        matching = hand[0] - 1
        if matching in available:
            return [matching]
        lower = [cat for cat in available if cat >= 6]
        return lower if lower else available
    return available


class OrderedDiceOracle:
    def __init__(self):
        self.hands = [tuple(dice.counts_to_dice_list(c)) for c in dice.enumerate_rolls()]
        self.hand_ids = {hand: i for i, hand in enumerate(self.hands)}
        self.keeps = sorted({hand[:n] for n in range(6)
                             for hand in product(FACES, repeat=n)
                             if tuple(sorted(hand)) == hand})
        self.keep_ids = {hand: i for i, hand in enumerate(self.keeps)}
        rows, cols, probs = [], [], []
        self.distributions = {}
        for keep_id, keep in enumerate(self.keeps):
            outcomes = Counter(tuple(sorted(keep + rolled))
                               for rolled in product(FACES, repeat=5-len(keep)))
            total = 6 ** (5 - len(keep))
            self.distributions[keep] = {self.hand_ids[h]: n / total for h, n in outcomes.items()}
            for hand, n in outcomes.items():
                rows.append(keep_id)
                cols.append(self.hand_ids[hand])
                probs.append(n / total)
        self.matrix = csr_matrix((probs, (rows, cols)), shape=(len(self.keeps), 252))
        self.options = []
        for hand in self.hands:
            self.options.append([self.keep_ids[k] for k in sorted({tuple(hand[i] for i in subset)
                for n in range(6) for subset in combinations(range(5), n)})])
        self.initial = self.matrix.getrow(self.keep_ids[()]).toarray()[0]

    def reroll(self, values):
        expected = self.matrix @ values
        return np.array([max(expected[choices]) for choices in self.options])

    @lru_cache(maxsize=None)
    def solve(self, mask, upper, status):
        if mask == FULL:
            return (35.0 if upper >= 63 else 0.0), None
        final = np.empty(252)
        for rid, hand in enumerate(self.hands):
            is_joker = status in (1, 2) and len(set(hand)) == 1
            bonus = 100 if status == 2 and is_joker else 0
            options = []
            for cat in reference_legal(hand, mask, status):
                pts = reference_score(cat, hand, is_joker)
                new_status = (2 if pts == 50 else 1) if cat == 11 and status is not None else status
                new_upper = min(63, upper + pts) if cat < 6 else upper
                future, _ = self.solve(mask | (1 << cat), new_upper, new_status)
                options.append(pts + bonus + future)
            final[rid] = max(options)
        second = self.reroll(final)
        first = self.reroll(second)
        return float(self.initial @ first), (first, second, final)


ORACLE = OrderedDiceOracle()


class TestExactDiceAndScoring(unittest.TestCase):
    def test_all_7776_physical_rolls_and_13_categories(self):
        for hand in product(FACES, repeat=5):
            actual = counts(hand)
            for cat in range(13):
                self.assertEqual(scoring.score(cat, actual), reference_score(cat, hand))
        ordered_frequencies = Counter(counts(h) for h in product(FACES, repeat=5))
        self.assertEqual(set(ordered_frequencies), set(dice.enumerate_rolls()))
        for hand, n in ordered_frequencies.items():
            self.assertAlmostEqual(dice.multinomial_prob(hand), n / 7776, places=14)

    def test_every_distinct_keep_against_ordered_outcomes(self):
        self.assertEqual(len(ORACLE.keeps), 462)
        for keep, expected in ORACLE.distributions.items():
            actual = dict(transitions.compute_next_roll_dist(counts(keep)))
            self.assertEqual(set(actual), set(expected))
            for rid in actual:
                self.assertAlmostEqual(actual[rid], expected[rid], places=14)
        for rid, hand in enumerate(ORACLE.hands):
            expected = {counts(ORACLE.keeps[k]) for k in ORACLE.options[rid]}
            self.assertEqual(set(transitions.get_keep_options(rid)), expected)

    def test_new_lattice_matches_independent_enumeration(self):
        lattice = build_reroll_lattice()
        rng = np.random.default_rng(20260904)
        samples = [np.zeros(252), np.full(252, 140.0), np.arange(252)]
        samples += [rng.normal(100, 80, 252) for _ in range(20)]
        for values in samples:
            actual = np.empty(252)
            compute_reroll_lattice(values, *lattice, actual)
            np.testing.assert_allclose(actual, ORACLE.reroll(values), rtol=0, atol=1e-11)

    def test_concurrent_cold_transition_read_never_sees_partial_table(self):
        saved = transitions._TRANSITIONS, transitions._KEEP_OPTIONS
        transitions._TRANSITIONS = transitions._KEEP_OPTIONS = None
        entered, release = Event(), Event()
        lock = Lock()
        first = True
        original = transitions.enumerate_keeps

        def pause_first_builder(hand):
            nonlocal first
            with lock:
                pause = first
                first = False
            if pause:
                entered.set()
                release.wait(timeout=5)
            return original(hand)

        try:
            with patch.object(transitions, 'enumerate_keeps', pause_first_builder):
                with ThreadPoolExecutor(max_workers=1) as executor:
                    initial = executor.submit(transitions.get_keep_options, 0)
                    self.assertTrue(entered.wait(timeout=5))
                    try:
                        self.assertEqual(transitions.get_keep_options(251), original(dice.id_to_roll(251)))
                    finally:
                        release.set()
                    self.assertEqual(initial.result(), original(dice.id_to_roll(0)))
        finally:
            transitions._TRANSITIONS, transitions._KEEP_OPTIONS = saved

    def test_joker_score_requires_filled_box_even_without_bonus(self):
        for face in FACES:
            hand = counts((face,) * 5)
            for cat, points in ((8, 25), (9, 30), (10, 40)):
                self.assertEqual(scoring.score(cat, hand, joker_rules=True), 0)
                for bonus_eligible in (False, True):
                    self.assertEqual(scoring.score(cat, hand, joker_rules=True,
                        yahtzee_filled=True, has_yahtzee_bonus=bonus_eligible), points)

    def test_joker_placement_for_all_masks_and_faces(self):
        # Exhaustive legal-action oracle: 4096 scorecards x 6 Yahtzees x 2 statuses.
        for mask in range(FULL + 1):
            if not mask & (1 << 11):
                continue
            for face in FACES:
                hand = (face,) * 5
                rid = ORACLE.hand_ids[hand]
                for status in (1, 2):
                    self.assertEqual(scoring.get_legal_categories_joker(rid, mask, status),
                                     reference_legal(hand, mask, status))


class TestOptimalPlayOracle(unittest.TestCase):
    def assert_state_matches(self, mask, upper, status):
        expected_ev, expected_arrays = ORACLE.solve(mask, upper, status)
        if status is None:
            actual_ev = solver.ev_remaining(mask, upper)
            actual_arrays = solver._get_v_arrays(mask, upper)
        else:
            actual_ev = solver.ev_remaining_joker(mask, upper, status)
            actual_arrays = solver._get_v_arrays_joker(mask, upper, status)
        self.assertAlmostEqual(actual_ev, expected_ev, places=9,
                               msg=f"mask={mask}, upper={upper}, status={status}")
        np.testing.assert_allclose(actual_arrays, expected_arrays, atol=1e-9, rtol=0)
        for rid in (0, 1, 42, 99, 200, 251):
            if status is None:
                keep1 = solver.best_keep_roll1(rid, mask, upper)
                keep2 = solver.best_keep_roll2(rid, mask, upper)
                cat, category_ev = solver.best_category(rid, mask, upper)
            else:
                keep1 = solver.best_keep_roll1_joker(rid, mask, upper, status)
                keep2 = solver.best_keep_roll2_joker(rid, mask, upper, status)
                cat, category_ev = solver.best_category_joker(rid, mask, upper, status)
            for keep, target, value in ((keep1, expected_arrays[1], expected_arrays[0][rid]),
                                        (keep2, expected_arrays[2], expected_arrays[1][rid])):
                keep_id = ORACLE.keep_ids[tuple(dice.counts_to_dice_list(keep))]
                self.assertIn(keep_id, ORACLE.options[rid])
                self.assertAlmostEqual(float((ORACLE.matrix.getrow(keep_id) @ target)[0]), value, places=9)
            self.assertIn(cat, reference_legal(ORACLE.hands[rid], mask, status))
            self.assertAlmostEqual(category_ev, expected_arrays[2][rid], places=9)

    def test_every_last_category_at_upper_bonus_boundaries(self):
        # 114 independent endgame states, each containing all 252 roll states
        # and both keep decisions, including scratch/bonus transitions.
        for category in range(13):
            mask = FULL ^ (1 << category)
            statuses = (None, 0) if category == 11 else (None, 1, 2)
            for upper in (0, 62, 63):
                for status in statuses:
                    with self.subTest(category=category, upper=upper, status=status):
                        self.assert_state_matches(mask, upper, status)

    def test_multiple_turn_endgames_with_status_and_upper_transitions(self):
        for open_categories, upper, status in (
                ((0, 5), 59, None), ((5, 8), 60, 1), ((0, 10), 61, 2),
                ((8, 11), 63, 0), ((5, 8, 11), 59, 0), ((0, 8, 12), 62, 2)):
            mask = FULL ^ sum(1 << cat for cat in open_categories)
            with self.subTest(open_categories=open_categories, upper=upper, status=status):
                self.assert_state_matches(mask, upper, status)

    def test_upper_only_closed_form(self):
        # Each die gets three chances to match the only scoring face.
        p = 1 - (5 / 6) ** 3
        for category in range(6):
            face = category + 1
            mask = FULL ^ (1 << category)
            for upper in range(64):
                bonus = sum(comb(5, k) * p ** k * (1-p) ** (5-k)
                            for k in range(6) if upper + face * k >= 63) * 35
                expected = 5 * face * p + bonus
                self.assertAlmostEqual(solver.ev_remaining(mask, upper), expected, places=9)

    def test_earned_upper_bonus_counted_once(self):
        for status in (1, 2):
            self.assertEqual(solver.ev_remaining_joker(FULL, 62, status), 0)
            self.assertEqual(solver.ev_remaining_joker(FULL, 63, status), 35)
            self.assertEqual(solver.ev_remaining_joker(FULL, 100, status), 35)
        self.assertAlmostEqual(solver.ev_remaining(FULL ^ (1 << 12), 63),
                               solver.ev_remaining(FULL ^ (1 << 12), 0) + 35)


class TestRegressionBoundaries(unittest.TestCase):
    def test_ev_runtime_caches_are_bounded(self):
        self.assertEqual(solver._get_v_arrays.cache_info().maxsize, 2048)
        self.assertEqual(solver._get_v_arrays_joker.cache_info().maxsize, 2048)

    def test_invalid_public_recommendations(self):
        valid = dict(dice=[1, 2, 3, 4, 5], mask=0, upper=0, rolls_remaining=2)
        for field, values in {'dice': [[0, 2, 3, 4, 5], [7, 2, 3, 4, 5], [True]*5,
                                        [1.0]*5, [], [1]*6],
                              'mask': [-1, 8192, True, FULL],
                              'upper': [-1, 1.5, True],
                              'rolls_remaining': [-1, 3, True, 1.0]}.items():
            for value in values:
                args = {**valid, field: value}
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    solver.get_recommendation(**args)
                with self.assertRaises(ValueError):
                    solver.get_recommendation_joker(**args, yahtzee_status=0)
        for mask, status in ((0, 1), (1 << 11, 0), (0, -1), (0, 3), (0, True)):
            with self.assertRaises(ValueError):
                solver.ev_remaining_joker(mask, 0, status)

    def test_lower_category_clamps_upper_above_threshold(self):
        rid = ORACLE.hand_ids[(1, 2, 3, 4, 5)]
        mask = FULL ^ (1 << 12)
        self.assertEqual(solver.best_category_joker(rid, mask, 100, 1), (12, 50.0))
        self.assertEqual(solver.get_all_category_evs_joker(rid, mask, 100, 1)[0][2], 50.0)

    def test_old_joker_cache_cannot_silently_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'legacy.pkl'
            path.write_bytes(pickle.dumps({'version': '2.0-joker'}))
            self.assertIsNone(load_cache(path))
            path.write_bytes(pickle.dumps({'version': CACHE_VERSION}))
            self.assertIsNone(load_cache(path))
        self.assertEqual(solver._load_joker_tables()['version'], CACHE_VERSION)


if __name__ == '__main__':
    unittest.main()
