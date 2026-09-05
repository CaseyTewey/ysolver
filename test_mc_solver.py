"""Monte Carlo engine correctness, reproducibility, and precision regressions."""
from concurrent.futures import ThreadPoolExecutor
from collections import defaultdict
import json
import math
import os
import subprocess
import sys
import unittest
from unittest.mock import patch

import numpy as np

import mc_solver as mc
from dice import compositions
from ev_solver import FULL_MASK, ev_remaining_joker
from pmf_solver import _final_roll_distribution
from pmf_solver_joker import compute_turn_pmf_joker, pmf_remaining_joker
from precompute_joker import compute_v3_joker_for_mask


def mask_with_open(category):
    return FULL_MASK ^ (1 << category)


def mc_policy_turn_distribution(mask, upper, status):
    """Exactly propagate the MC-selected policy, without sampling any dice."""
    runtime = mc._runtime_arguments()
    score_table, joker_table, _, is_yahtzee, _ = runtime[:5]
    partial_hands = [hand for size in range(6) for hand in compositions(size)]
    final_values, second_values, first_values = (np.empty(252) for _ in range(3))
    categories = np.empty(252, dtype=np.int8)
    first_keeps, second_keeps = (np.empty(252, dtype=np.int32) for _ in range(2))
    compute_v3_joker_for_mask(mask, upper, status, *runtime[:5], final_values, categories)
    mc._optimal_keeps(final_values, *runtime[5:], second_values, second_keeps)
    mc._optimal_keeps(second_values, *runtime[5:], first_values, first_keeps)
    result = defaultdict(float)
    # The independent PMF path enumerates physical reroll probabilities for
    # these chosen hands; it does not use the MC lattice's expectation values.
    final_rolls = _final_roll_distribution(
        [partial_hands[k] for k in first_keeps],
        [partial_hands[k] for k in second_keeps])
    for roll, probability in final_rolls.items():
        category = int(categories[roll])
        table = joker_table if is_yahtzee[roll] and status else score_table
        points = int(table[roll, category])
        next_upper = min(63, upper + points) if category < 6 else upper
        next_status = (2 if points == 50 else 1) if category == 11 else status
        bonus = 100 if is_yahtzee[roll] and status == 2 else 0
        outcome = (points + bonus, mask | (1 << category), next_upper, next_status)
        result[outcome] += probability
    return dict(result)


class TestMCContract(unittest.TestCase):
    def test_rejects_invalid_values_before_loading_runtime(self):
        valid = [50, 2048, 0, 2, 0, 0, 0, 0]
        bad_fields = {
            0: [-1, 1541, True, 1.0],
            1: [-1, 8192, True, 1.0],
            2: [-1, 106, True, 1.0],
            3: [-1, 3, True, 1.0, 0],
            4: [-1, 1541, False, 1.0],
            5: [-1, 8192, False, 1.0],
            6: [-1, 106, False, 1.0],
            7: [-1, 3, False, 1.0, 1, 2],
        }
        with patch.object(mc, '_runtime_arguments', side_effect=AssertionError('loaded invalid state')):
            for index, values in bad_fields.items():
                for value in values:
                    args = valid.copy(); args[index] = value
                    with self.subTest(index=index, value=value), self.assertRaises(ValueError):
                        mc.simulate_match(*args)
            for value in (0, -1, 100001, True, 1.0, '10000'):
                with self.subTest(sample_count=value), self.assertRaises(ValueError):
                    mc.simulate_match(*valid, sample_count=value)

    def test_terminal_state_counts_upper_bonus_once(self):
        result = mc.simulate_match(42, FULL_MASK, 63, 1, 77, FULL_MASK, 0, 1)
        self.assertEqual(result['probabilities'], (0.0, 1.0, 0.0))
        self.assertEqual(result['counts'], (0, 10000, 0))
        self.assertEqual(result['means'], (77.0, 77.0))
        self.assertEqual(result['standard_deviations'], (0.0, 0.0))
        self.assertLess(result['max_margin_percentage_points'], 1)

    def test_swap_is_exactly_symmetric_and_reproducible(self):
        first = (0, mask_with_open(12), 0, 1)
        second = (20, mask_with_open(0), 0, 1)
        result = mc.simulate_match(*first, *second, sample_count=2000)
        reversed_result = mc.simulate_match(*second, *first, sample_count=2000)
        for key in ('probabilities', 'counts', 'intervals', 'seeds', 'means', 'standard_deviations'):
            self.assertEqual(result[key], reversed_result[key][::-1])
        self.assertEqual(result, mc.simulate_match(*first, *second, sample_count=2000))
        self.assertEqual(sum(result['counts']), 2000)
        self.assertAlmostEqual(sum(result['probabilities']), 1)

    def test_equal_fresh_players_use_independent_streams(self):
        result = mc.simulate_match(0, 0, 0, 0, 0, 0, 0, 0, sample_count=256)
        self.assertNotEqual(*result['seeds'])
        self.assertLess(result['probabilities'][1], 0.1)
        self.assertGreater(result['probabilities'][0], 0.3)
        self.assertGreater(result['probabilities'][2], 0.3)

    def test_upper_above_threshold_is_the_same_canonical_state(self):
        state = (100, mask_with_open(12), 63, 1)
        equivalent = (100, mask_with_open(12), 105, 1)
        opponent = (110, FULL_MASK, 0, 1)
        self.assertEqual(mc.simulate_match(*state, *opponent, sample_count=100),
                         mc.simulate_match(*equivalent, *opponent, sample_count=100))

    def test_seeds_do_not_depend_on_python_hash_seed(self):
        statement = ('import json,mc_solver as m; '
                     'print(json.dumps(m._canonical_seeds((0,0,0,0),(50,2048,0,2),10000)))')
        values = []
        for hash_seed in ('1', '9999'):
            values.append(subprocess.check_output([sys.executable, '-c', statement],
                env={**os.environ, 'PYTHONHASHSEED': hash_seed}, text=True).strip())
        self.assertEqual(values[0], values[1])
        self.assertEqual(tuple(json.loads(values[0])),
                         mc._canonical_seeds((0,0,0,0), (50,2048,0,2), 10000))

    def test_every_wilson_endpoint_is_within_one_percentage_point_at_10k(self):
        maximum = 0
        for count in range(10001):
            low, high = mc._wilson_interval(count, 10000)
            p = count / 10000
            self.assertTrue(0 <= low <= p <= high <= 1)
            maximum = max(maximum, (p-low)*100, (high-p)*100)
        self.assertLess(maximum, 1)
        self.assertGreater(maximum, .97)

    def test_runtime_arrays_are_readonly_and_compiled_loop_releases_gil(self):
        runtime = mc._runtime_arguments()
        self.assertIs(runtime, mc._runtime_arguments())
        for array in runtime[:-1]:
            self.assertFalse(array.flags.writeable)
        self.assertTrue(mc._simulate_player.targetoptions['nogil'])
        self.assertTrue(mc._optimal_keeps.targetoptions['nogil'])

    def test_thread_local_rng_is_reproducible_during_concurrent_calls(self):
        args = (0, mask_with_open(12), 0, 1, 20, mask_with_open(0), 0, 1)
        expected = mc.simulate_match(*args, sample_count=1000)
        with ThreadPoolExecutor(max_workers=2) as executor:
            jobs = [executor.submit(mc.simulate_match, *args, sample_count=1000) for _ in range(2)]
            for job in jobs:
                self.assertEqual(job.result(), expected)


class TestMCAgainstExactDistributions(unittest.TestCase):
    def test_selected_policy_matches_exact_turn_outcomes_at_rule_branches(self):
        # Compare complete point/status transitions, not just equal means.
        # Matching upper is forced first, otherwise lower is forced, and a
        # different upper is a zero only when all lower boxes are filled.
        states = (((5, 8), 60, 1), ((5, 8), 60, 2),
                  ((0, 8), 62, 1), ((0, 8), 62, 2),
                  ((0,), 62, 1), ((0,), 62, 2),
                  ((8, 11), 63, 0), ((0, 5), 59, 2))
        for open_categories, upper, status in states:
            mask = FULL_MASK ^ sum(1 << category for category in open_categories)
            with self.subTest(open_categories=open_categories, upper=upper, status=status):
                actual = mc_policy_turn_distribution(mask, upper, status)
                expected = compute_turn_pmf_joker(mask, upper, status)
                self.assertEqual(set(actual), set(expected))
                self.assertAlmostEqual(sum(actual.values()), 1, places=12)
                for outcome in expected:
                    self.assertAlmostEqual(actual[outcome], expected[outcome], places=12,
                                           msg=str(outcome))

    def test_late_states_match_exact_support_mean_and_cdf(self):
        runtime = mc._runtime_arguments()
        states = ((mask_with_open(0), 0, 1, 0),
                  (mask_with_open(0), 62, 1, 7),
                  (mask_with_open(12), 63, 1, 10),
                  (mask_with_open(8), 0, 2, 50),
                  (mask_with_open(11), 0, 0, 0))
        for i, (mask, upper, status, locked) in enumerate(states):
            with self.subTest(mask=mask, upper=upper, status=status):
                scores = mc._simulate_player(10000, 73101+i, mask, upper, status, locked, *runtime)
                pmf = pmf_remaining_joker(mask, upper, status)
                self.assertTrue(set(map(int,scores)) <= {locked+x for x in pmf})
                exact_mean = locked + sum(x*p for x,p in pmf.items())
                standard_error = scores.std(ddof=1) / math.sqrt(len(scores))
                self.assertLess(abs(scores.mean()-exact_mean), 4.5*standard_error)
                exact_cdf = 0
                for score in sorted(pmf):
                    exact_cdf += pmf[score]
                    self.assertLess(abs(np.mean(scores <= locked+score)-exact_cdf), .025)


class TestOpeningYahtzeeBenchmark(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # One full 10k run is reused for probability, variance, and mean checks.
        cls.result = mc.simulate_match(50, 2048, 0, 2, 0, 0, 0, 0)

    def test_matches_independent_200k_benchmark(self):
        self.assertAlmostEqual(self.result['probabilities'][0], .753805, delta=.02)
        self.assertLess(self.result['probabilities'][1], .012)
        self.assertLess(self.result['max_margin_percentage_points'], 1)
        self.assertEqual(self.result['sample_count'], 10000)
        self.assertEqual(self.result['confidence_level'], .95)

    def test_sample_means_match_exact_bellman_values(self):
        exact_means = (50+ev_remaining_joker(2048,0,2), ev_remaining_joker(0,0,0))
        for mean, sd, exact_mean in zip(self.result['means'], self.result['standard_deviations'], exact_means):
            self.assertLess(abs(mean-exact_mean), 4*sd/100)

    def test_preserves_large_actual_score_variance(self):
        self.assertAlmostEqual(self.result['standard_deviations'][0], 83.127, delta=6)
        self.assertAlmostEqual(self.result['standard_deviations'][1], 59.565, delta=6)


if __name__ == '__main__':
    unittest.main()
