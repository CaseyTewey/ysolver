"""Bounded, independent PMF and match regressions (no fresh-game recursion)."""
import math
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pmf_solver as traditional
import pmf_solver_joker as joker
import match
from dice import dice_list_to_counts, roll_id
from ev_solver import (
    FULL_MASK, YAHTZEE_UNFILLED, YAHTZEE_SCRATCHED, YAHTZEE_SCORED,
    ev_remaining, ev_remaining_joker,
)


def open_mask(*categories):
    return FULL_MASK ^ sum(1 << category for category in categories)


def independent_convolution(a, b):
    result = {}
    for x, px in a.items():
        for y, py in b.items():
            result[x + y] = result.get(x + y, 0.0) + px * py
    return result


def compare_by_pairs(a, b):
    result = [0.0, 0.0, 0.0]
    for sa, pa in a.items():
        for sb, pb in b.items():
            result[0 if sa > sb else 1 if sa == sb else 2] += pa * pb
    return result


class PMFAssertions(unittest.TestCase):
    def assert_distribution(self, pmf):
        self.assertTrue(pmf)
        self.assertAlmostEqual(sum(pmf.values()), 1.0, places=12)
        self.assertTrue(all(math.isfinite(p) and 0 <= p <= 1 for p in pmf.values()))

    def assert_same_distribution(self, actual, expected):
        self.assertEqual(set(actual), set(expected))
        for outcome, probability in expected.items():
            self.assertAlmostEqual(actual[outcome], probability, places=11, msg=str(outcome))


class TestPMFAnalyticalOracles(PMFAssertions):
    def test_last_ones_is_binomial_after_three_attempts_per_die(self):
        success = 1 - (5 / 6) ** 3
        expected = {k: math.comb(5, k) * success**k * (1-success)**(5-k) for k in range(6)}
        for solve in (lambda: traditional.pmf_remaining(open_mask(0), 0),
                      lambda: joker.pmf_remaining_joker(open_mask(0), 0, YAHTZEE_SCRATCHED)):
            actual = solve()
            self.assert_distribution(actual)
            self.assert_same_distribution(actual, expected)

    def test_last_chance_is_sum_of_five_independently_optimized_dice(self):
        # Keep 5/6 on roll one, 4/5/6 on roll two; roll the rest again.
        die = {1: 1/18, 2: 1/18, 3: 1/18, 4: 1/6, 5: 1/3, 6: 1/3}
        expected = {0: 1.0}
        for _ in range(5):
            expected = independent_convolution(expected, die)
        for solve in (lambda: traditional.pmf_remaining(open_mask(12), 0),
                      lambda: joker.pmf_remaining_joker(open_mask(12), 0, YAHTZEE_SCRATCHED)):
            actual = solve()
            self.assert_distribution(actual)
            self.assert_same_distribution(actual, expected)
            self.assertAlmostEqual(sum(s*p for s, p in actual.items()), 70/3, places=11)

    def test_upper_threshold_awards_bonus_once(self):
        # Ones remain and 62 upper points are already locked in. Any hit earns 35.
        success = 1 - (5/6)**3
        expected = {(k + (35 if k else 0)): math.comb(5,k)*success**k*(1-success)**(5-k)
                    for k in range(6)}
        self.assert_same_distribution(traditional.pmf_remaining(open_mask(0), 62), expected)
        self.assert_same_distribution(
            joker.pmf_remaining_joker(open_mask(0), 62, YAHTZEE_SCRATCHED), expected)
        for upper in (63, 100):
            self.assertEqual(traditional.pmf_remaining(FULL_MASK, upper), {35: 1.0})
            self.assertEqual(joker.pmf_remaining_joker(FULL_MASK, upper, YAHTZEE_SCORED), {35: 1.0})
        self.assertEqual(traditional.pmf_remaining(FULL_MASK, 62), {0: 1.0})

    def test_turn_mass_preserved_even_when_individual_paths_are_tiny(self):
        for eps in (0, 1e-7, .1):
            distribution = joker.compute_turn_pmf_joker(open_mask(12), 0, YAHTZEE_SCRATCHED, eps=eps)
            self.assert_distribution(distribution)
            self.assertAlmostEqual(sum(key[0]*p for key,p in distribution.items()), 70/3, places=11)

    def test_pmf_mean_matches_bellman_ev_for_late_states(self):
        for categories, upper, status in [((12,),0,1), ((0,12),60,1), ((11,12),45,0), ((8,12),63,2)]:
            mask = open_mask(*categories)
            with self.subTest(categories=categories, upper=upper, status=status):
                pmf = joker.pmf_remaining_joker(mask,upper,status)
                self.assert_distribution(pmf)
                self.assertAlmostEqual(sum(s*p for s,p in pmf.items()),
                                       ev_remaining_joker(mask,upper,status), places=9)
                pmf = traditional.pmf_remaining(mask,upper)
                self.assert_distribution(pmf)
                self.assertAlmostEqual(sum(s*p for s,p in pmf.items()), ev_remaining(mask,upper), places=9)

    def test_all_last_categories_at_upper_bonus_boundaries(self):
        for category in range(13):
            mask = open_mask(category)
            for upper in (0, 60, 62, 63):
                for status in ([YAHTZEE_UNFILLED] if category == 11 else [YAHTZEE_SCRATCHED, YAHTZEE_SCORED]):
                    with self.subTest(category=category, upper=upper, status=status):
                        pmf = joker.pmf_remaining_joker(mask, upper, status)
                        self.assert_distribution(pmf)
                        self.assertAlmostEqual(sum(s*p for s,p in pmf.items()),
                                               ev_remaining_joker(mask,upper,status), places=9)

    def test_terminal_turn_and_outs_are_defined(self):
        self.assertEqual(traditional.compute_turn_score_dist(FULL_MASK,63), {0:1.0})
        self.assertEqual(traditional.compute_category_hit_probs(FULL_MASK,63), {})
        result = traditional.get_outs_analysis(FULL_MASK,63,200,235)
        self.assertEqual(result['prob_reach_target'],1)
        self.assertEqual(result['category_probs'],[])
        self.assertEqual(result['turn_score_stats']['mean'],0)


class TestJokerScoreOutcomes(PMFAssertions):
    def test_bonus_and_forced_category_rules(self):
        tables = joker._load_joker_tables()
        sixes = roll_id(dice_list_to_counts([6]*5))
        # Additional Yahtzee must fill the matching upper category first.
        for status, bonus in ((YAHTZEE_SCRATCHED,0),(YAHTZEE_SCORED,100)):
            with self.subTest(status=status):
                result = joker._get_best_category_joker_full(sixes,open_mask(5,8),40,status,tables)
                self.assertEqual(result,(5,30+bonus,63,status))
                # If that upper category is filled, lower section precedes other uppers.
                result = joker._get_best_category_joker_full(sixes,open_mask(0,8),40,status,tables)
                self.assertEqual(result,(8,25+bonus,40,status))
                # With no lower box remaining, a different upper box scores zero.
                result = joker._get_best_category_joker_full(sixes,open_mask(0),40,status,tables)
                self.assertEqual(result,(0,bonus,40,status))
        result = joker._get_best_category_joker_full(sixes,open_mask(11),40,YAHTZEE_UNFILLED,tables)
        self.assertEqual(result,(11,50,40,YAHTZEE_SCORED))
        mixed = roll_id(dice_list_to_counts([1,2,3,4,6]))
        result = joker._get_best_category_joker_full(mixed,open_mask(11),40,YAHTZEE_UNFILLED,tables)
        self.assertEqual(result,(11,0,40,YAHTZEE_SCRATCHED))


class TestPMFCacheAndHelpers(PMFAssertions):
    def test_precision_options_do_not_reuse_another_distribution(self):
        for clear,solve in (
            (traditional.clear_pmf_cache,lambda **kw: traditional.pmf_remaining(open_mask(0),0,**kw)),
            (joker.clear_pmf_joker_cache,lambda **kw: joker.pmf_remaining_joker(open_mask(0),0,1,**kw)),
        ):
            clear()
            self.assertEqual(len(solve(topk=1)),1)
            self.assertEqual(len(solve(topk=6)),6)
            self.assertEqual(len(solve(eps=.99)),1)
            self.assertEqual(len(solve(eps=0)),6)

    def test_caller_cannot_mutate_cached_results(self):
        for solve in (lambda: traditional.pmf_remaining(FULL_MASK,63),
                      lambda: joker.pmf_remaining_joker(FULL_MASK,63,1)):
            result = solve()
            result[999] = .5
            result[35] = 0
            self.assertEqual(solve(),{35:1.0})

    def test_concurrent_clear_compute_and_eviction(self):
        def exercise(index):
            if index % 4 == 0:
                joker.clear_pmf_joker_cache()
                traditional.clear_pmf_cache()
            upper = index % 64
            a = traditional.pmf_remaining(FULL_MASK,upper)
            b = joker.pmf_remaining_joker(FULL_MASK,upper,YAHTZEE_SCORED)
            self.assertEqual(a,b)
            self.assert_distribution(a)
        with patch.object(joker,'_PMF_CACHE_MAX_SIZE',4), patch.object(traditional,'_PMF_CACHE_MAX_SIZE',4):
            joker.clear_pmf_joker_cache()
            traditional.clear_pmf_cache()
            with ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(exercise,range(256)))
            self.assertLessEqual(joker.get_pmf_cache_size(),4)
            self.assertLessEqual(len(traditional._PMF_CACHE),4)

    def test_invalid_inputs_fail_before_accessing_solver_tables(self):
        for mask,upper in ((-1,0),(FULL_MASK+1,0),(0,-1),(True,0),(0,1.5)):
            with self.subTest(mask=mask,upper=upper), self.assertRaises(ValueError):
                traditional.pmf_remaining(mask,upper)
        for status in (-1,3,True,.5,1.0):
            with self.assertRaises(ValueError):
                joker.pmf_remaining_joker(FULL_MASK,0,status)
        for mask,status in ((FULL_MASK,0),(open_mask(11),1),(open_mask(11),2)):
            with self.assertRaises(ValueError):
                joker.pmf_remaining_joker(mask,0,status)
        for kwargs in ({'eps':-1},{'eps':math.nan},{'topk':0},{'topk':1.5}):
            with self.assertRaises(ValueError):
                traditional.pmf_remaining(FULL_MASK,0,**kwargs)

    def test_fft_matches_direct_convolution_for_sparse_negative_scores(self):
        a = {i-20: (i+1)/820 for i in range(40)}
        b = {3*i-45: (30-i)/465 for i in range(30)}
        expected = independent_convolution(a,b)
        self.assert_same_distribution(traditional.convolve_pmf(a,b),expected)
        self.assert_distribution(traditional.convolve_pmf(a,b))

    def test_aggressive_pruning_never_returns_empty_distribution(self):
        self.assertEqual(traditional.prune_pmf({1:.4,2:.6},eps=.9),{2:1.0})
        for distribution in ({1:-.1,2:1.1},{1:math.nan},{1:0}):
            with self.assertRaises(ValueError):
                traditional.prune_pmf(distribution)


class TestMatchProbabilities(PMFAssertions):
    def test_terminal_win_loss_and_tie(self):
        for score_a,score_b,expected in ((1,0,(1,0,0)),(0,0,(0,1,0)),(0,1,(0,0,1))):
            a=match.PlayerState(score_a,FULL_MASK,0)
            b=match.PlayerState(score_b,FULL_MASK,0)
            self.assertEqual(tuple(match.compute_win_probs_fast(a,b).values()),expected)
            self.assertEqual(tuple(match.compute_win_probs(a,b).values()),expected)
            self.assertEqual(joker.compute_win_probability_exact(
                score_a,FULL_MASK,0,1,score_b,FULL_MASK,0,1),expected)

    def test_roundoff_cannot_make_win_probability_exceed_one(self):
        a = match.PlayerState(2000, FULL_MASK, 0)
        for category in range(13):
            b = match.PlayerState(0, open_mask(category), 0)
            probabilities = match.compute_win_probs_fast(a, b)
            self.assert_distribution(probabilities)
            self.assertAlmostEqual(probabilities["win_prob"], 1.0, places=13)

    def test_fast_cdf_matches_independent_pairs_between_support_points(self):
        cases=[({-5:.1,0:.2,2:.3,10:.4},{-4:.3,0:.1,4:.6}),
               ({100:1.0},{1:.1,2:.2,3:.7}),
               ({0:.25,100:.75},{0:.25,100:.75})]
        a=match.PlayerState(0,open_mask(0),0)
        b=match.PlayerState(0,open_mask(1),0)
        for pa,pb in cases:
            expected=compare_by_pairs(pa,pb)
            with patch.object(match,'pmf_remaining',side_effect=[pa,pb]):
                actual=match.compute_win_probs_fast(a,b)
            self.assert_distribution(actual)
            for x,y in zip(actual.values(),expected):
                self.assertAlmostEqual(x,y,places=13)

    def test_comeback_integrates_opponent_distribution(self):
        a=match.PlayerState(0,open_mask(0),0)
        b=match.PlayerState(0,open_mask(1),0)
        # P(A >= B)=.5; comparing A=5 against E[B]=50 would incorrectly give 0.
        distributions={a.mask:{5:1.0},b.mask:{0:.5,100:.5}}
        with patch.object(match,'pmf_remaining',side_effect=lambda mask,upper:distributions[mask]):
            self.assertEqual(match.get_comeback_analysis(a,b)['prob_catch_up_or_win'],.5)

    def test_upper_bonus_locked_contract(self):
        # Category points 200+35 beat 220; passing already-bonused totals would
        # double-count the upper bonus, so callers pass raw category points.
        result=joker.compute_win_probability_exact(200,FULL_MASK,63,1,220,FULL_MASK,62,1)
        self.assertEqual(result,(1.0,0.0,0.0))

    def test_real_late_game_symmetry_and_score_monotonicity(self):
        mask=open_mask(12)
        wins,ties,losses=joker.compute_win_probability_exact(100,mask,0,1,100,mask,0,1)
        self.assertAlmostEqual(wins,losses,places=12)
        self.assertAlmostEqual(wins+ties+losses,1,places=12)
        ahead=joker.compute_win_probability_exact(110,mask,0,1,100,mask,0,1)
        self.assertGreater(ahead[0],wins)
        self.assertLess(ahead[2],losses)


if __name__=='__main__':
    unittest.main()
