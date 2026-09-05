#!/usr/bin/env python3
"""
Unit tests for the Yahtzee solver.

Run with: python -m pytest tests.py -v
Or simply: python tests.py
"""

import unittest
from math import isclose


class TestDice(unittest.TestCase):
    """Tests for dice.py module."""

    def test_enumerate_rolls_count(self):
        """Should have exactly 252 unique 5-dice multisets."""
        from dice import enumerate_rolls
        rolls = enumerate_rolls()
        self.assertEqual(len(rolls), 252)

    def test_enumerate_rolls_uniqueness(self):
        """All rolls should be unique."""
        from dice import enumerate_rolls
        rolls = enumerate_rolls()
        self.assertEqual(len(rolls), len(set(rolls)))

    def test_roll_id_bijection(self):
        """roll_id and id_to_roll should be inverses."""
        from dice import enumerate_rolls, roll_id, id_to_roll
        rolls = enumerate_rolls()
        for i, counts in enumerate(rolls):
            self.assertEqual(roll_id(counts), i)
            self.assertEqual(id_to_roll(i), counts)

    def test_multinomial_prob_sums_to_one(self):
        """Probabilities over all 5-dice rolls should sum to 1."""
        from dice import enumerate_rolls, multinomial_prob
        total = sum(multinomial_prob(r) for r in enumerate_rolls())
        self.assertTrue(isclose(total, 1.0, rel_tol=1e-9))

    def test_multinomial_specific_values(self):
        """Test known probability values."""
        from dice import multinomial_prob

        # Yahtzee (5 of same): 6 * (1/6)^5 = 6/7776 ≈ 0.00077
        yahtzee_prob = multinomial_prob((5, 0, 0, 0, 0, 0))
        self.assertTrue(isclose(yahtzee_prob, 1/7776, rel_tol=1e-9))

        # All different (1,2,3,4,5): 5!/6^5 = 120/7776
        all_diff = multinomial_prob((1, 1, 1, 1, 1, 0))
        self.assertTrue(isclose(all_diff, 120/7776, rel_tol=1e-9))

    def test_dice_list_conversion(self):
        """Test conversion between dice lists and counts."""
        from dice import dice_list_to_counts, counts_to_dice_list

        dice = [1, 1, 3, 5, 6]
        counts = dice_list_to_counts(dice)
        self.assertEqual(counts, (2, 0, 1, 0, 1, 1))

        back = counts_to_dice_list(counts)
        self.assertEqual(sorted(back), sorted(dice))


class TestScoring(unittest.TestCase):
    """Tests for scoring.py module."""

    def setUp(self):
        from dice import dice_list_to_counts
        self.to_counts = dice_list_to_counts

    def test_upper_section_scoring(self):
        """Test upper section (Ones through Sixes)."""
        from scoring import score, Category

        # [1,1,1,2,3] should score 3 in Ones
        counts = self.to_counts([1, 1, 1, 2, 3])
        self.assertEqual(score(Category.ONES, counts), 3)
        self.assertEqual(score(Category.TWOS, counts), 2)
        self.assertEqual(score(Category.THREES, counts), 3)

        # [6,6,6,6,5] should score 24 in Sixes
        counts = self.to_counts([6, 6, 6, 6, 5])
        self.assertEqual(score(Category.SIXES, counts), 24)

    def test_three_of_a_kind(self):
        """Test three of a kind scoring."""
        from scoring import score, Category

        # [3,3,3,2,1] should score 12 (sum)
        counts = self.to_counts([3, 3, 3, 2, 1])
        self.assertEqual(score(Category.THREE_OF_A_KIND, counts), 12)

        # [1,2,3,4,5] should score 0
        counts = self.to_counts([1, 2, 3, 4, 5])
        self.assertEqual(score(Category.THREE_OF_A_KIND, counts), 0)

    def test_four_of_a_kind(self):
        """Test four of a kind scoring."""
        from scoring import score, Category

        # [4,4,4,4,1] should score 17
        counts = self.to_counts([4, 4, 4, 4, 1])
        self.assertEqual(score(Category.FOUR_OF_A_KIND, counts), 17)

        # [3,3,3,2,1] should score 0
        counts = self.to_counts([3, 3, 3, 2, 1])
        self.assertEqual(score(Category.FOUR_OF_A_KIND, counts), 0)

    def test_full_house(self):
        """Test full house scoring."""
        from scoring import score, Category

        # [2,2,3,3,3] should score 25
        counts = self.to_counts([2, 2, 3, 3, 3])
        self.assertEqual(score(Category.FULL_HOUSE, counts), 25)

        # [2,2,2,3,3] should also score 25
        counts = self.to_counts([2, 2, 2, 3, 3])
        self.assertEqual(score(Category.FULL_HOUSE, counts), 25)

        # [1,1,1,1,1] (Yahtzee) is NOT a full house in standard rules
        counts = self.to_counts([1, 1, 1, 1, 1])
        self.assertEqual(score(Category.FULL_HOUSE, counts), 0)

    def test_small_straight(self):
        """Test small straight scoring."""
        from scoring import score, Category

        # [1,2,3,4,6] should score 30
        counts = self.to_counts([1, 2, 3, 4, 6])
        self.assertEqual(score(Category.SMALL_STRAIGHT, counts), 30)

        # [2,3,4,5,5] should score 30
        counts = self.to_counts([2, 3, 4, 5, 5])
        self.assertEqual(score(Category.SMALL_STRAIGHT, counts), 30)

        # [1,2,3,5,6] should score 0
        counts = self.to_counts([1, 2, 3, 5, 6])
        self.assertEqual(score(Category.SMALL_STRAIGHT, counts), 0)

    def test_large_straight(self):
        """Test large straight scoring."""
        from scoring import score, Category

        # [1,2,3,4,5] should score 40
        counts = self.to_counts([1, 2, 3, 4, 5])
        self.assertEqual(score(Category.LARGE_STRAIGHT, counts), 40)

        # [2,3,4,5,6] should score 40
        counts = self.to_counts([2, 3, 4, 5, 6])
        self.assertEqual(score(Category.LARGE_STRAIGHT, counts), 40)

        # [1,2,3,4,6] should score 0
        counts = self.to_counts([1, 2, 3, 4, 6])
        self.assertEqual(score(Category.LARGE_STRAIGHT, counts), 0)

    def test_yahtzee(self):
        """Test Yahtzee scoring."""
        from scoring import score, Category

        # [5,5,5,5,5] should score 50
        counts = self.to_counts([5, 5, 5, 5, 5])
        self.assertEqual(score(Category.YAHTZEE, counts), 50)

        # [5,5,5,5,4] should score 0
        counts = self.to_counts([5, 5, 5, 5, 4])
        self.assertEqual(score(Category.YAHTZEE, counts), 0)

    def test_chance(self):
        """Test Chance scoring (always sum of dice)."""
        from scoring import score, Category

        counts = self.to_counts([1, 2, 3, 4, 5])
        self.assertEqual(score(Category.CHANCE, counts), 15)

        counts = self.to_counts([6, 6, 6, 6, 6])
        self.assertEqual(score(Category.CHANCE, counts), 30)

    def test_score_table_dimensions(self):
        """Precomputed score table should have correct dimensions."""
        from scoring import precompute_score_table, NUM_CATEGORIES
        from dice import enumerate_rolls

        table = precompute_score_table()
        self.assertEqual(len(table), 252)  # All rolls
        self.assertEqual(len(table[0]), NUM_CATEGORIES)  # 13 categories


class TestJokerScoring(unittest.TestCase):
    """Tests for joker mode scoring functions in scoring.py."""

    def test_yahtzee_detection(self):
        """Test is_yahtzee_roll() correctly identifies Yahtzees."""
        from scoring import is_yahtzee_roll, get_yahtzee_face
        from dice import roll_id

        # Test all 6 yahtzee rolls
        for face in range(6):
            counts = [0, 0, 0, 0, 0, 0]
            counts[face] = 5
            roll = roll_id(tuple(counts))
            self.assertTrue(is_yahtzee_roll(roll),
                          f"Five {face+1}s should be a Yahtzee")
            self.assertEqual(get_yahtzee_face(roll), face,
                           f"Five {face+1}s should have face={face}")

        # Test non-yahtzee rolls
        non_yahtzee_rolls = [
            (4, 1, 0, 0, 0, 0),  # Four 1s and one 2
            (3, 2, 0, 0, 0, 0),  # Full house
            (1, 1, 1, 1, 1, 0),  # Large straight
            (2, 2, 1, 0, 0, 0),  # Random
        ]
        for counts in non_yahtzee_rolls:
            roll = roll_id(counts)
            self.assertFalse(is_yahtzee_roll(roll),
                           f"{counts} should NOT be a Yahtzee")
            self.assertEqual(get_yahtzee_face(roll), -1,
                           f"Non-yahtzee should have face=-1")

    def test_joker_score_full_house(self):
        """Yahtzee scored as Full House should be 25 (joker rule)."""
        from scoring import get_joker_score_table, Category
        from dice import roll_id

        table = get_joker_score_table()
        for face in range(6):
            counts = [0, 0, 0, 0, 0, 0]
            counts[face] = 5
            roll = roll_id(tuple(counts))
            self.assertEqual(table[roll, Category.FULL_HOUSE], 25,
                           f"Five {face+1}s as Full House should be 25")

    def test_joker_score_small_straight(self):
        """Yahtzee scored as Small Straight should be 30 (joker rule)."""
        from scoring import get_joker_score_table, Category
        from dice import roll_id

        table = get_joker_score_table()
        for face in range(6):
            counts = [0, 0, 0, 0, 0, 0]
            counts[face] = 5
            roll = roll_id(tuple(counts))
            self.assertEqual(table[roll, Category.SMALL_STRAIGHT], 30,
                           f"Five {face+1}s as Small Straight should be 30")

    def test_joker_score_large_straight(self):
        """Yahtzee scored as Large Straight should be 40 (joker rule)."""
        from scoring import get_joker_score_table, Category
        from dice import roll_id

        table = get_joker_score_table()
        for face in range(6):
            counts = [0, 0, 0, 0, 0, 0]
            counts[face] = 5
            roll = roll_id(tuple(counts))
            self.assertEqual(table[roll, Category.LARGE_STRAIGHT], 40,
                           f"Five {face+1}s as Large Straight should be 40")

    def test_joker_upper_section_score(self):
        """Yahtzee in upper section should score face*5."""
        from scoring import get_joker_score_table
        from dice import roll_id

        table = get_joker_score_table()
        for face in range(6):
            counts = [0, 0, 0, 0, 0, 0]
            counts[face] = 5
            roll = roll_id(tuple(counts))
            expected = (face + 1) * 5  # 5, 10, 15, 20, 25, 30
            self.assertEqual(table[roll, face], expected,
                           f"Five {face+1}s in upper section should be {expected}")

    def test_joker_forcing_rule(self):
        """Must use upper section if corresponding category is open."""
        from scoring import get_forced_category_joker
        from dice import roll_id

        # Test each face
        for face in range(6):
            counts = [0, 0, 0, 0, 0, 0]
            counts[face] = 5
            roll = roll_id(tuple(counts))

            # With no categories filled, must use upper section
            self.assertEqual(get_forced_category_joker(roll, 0), face,
                           f"Five {face+1}s should force category {face}")

            # With upper section filled, free choice
            mask_upper_filled = 1 << face
            self.assertIsNone(get_forced_category_joker(roll, mask_upper_filled),
                            f"With cat {face} filled, should have free choice")

    def test_forcing_rule_non_yahtzee(self):
        """Non-yahtzee rolls should never be forced."""
        from scoring import get_forced_category_joker
        from dice import roll_id

        non_yahtzee = roll_id((3, 2, 0, 0, 0, 0))  # Full house
        self.assertIsNone(get_forced_category_joker(non_yahtzee, 0))
        self.assertIsNone(get_forced_category_joker(non_yahtzee, 0b1111111111111))

    def test_yahtzee_detection_arrays(self):
        """Test precomputed yahtzee detection arrays."""
        from scoring import get_yahtzee_detection_arrays, NUM_ROLLS

        is_ytz, ytz_face = get_yahtzee_detection_arrays()

        self.assertEqual(len(is_ytz), NUM_ROLLS)
        self.assertEqual(len(ytz_face), NUM_ROLLS)

        # Should have exactly 6 yahtzees
        self.assertEqual(is_ytz.sum(), 6)

        # Faces should be 0-5 for yahtzees, -1 for others
        for i in range(NUM_ROLLS):
            if is_ytz[i]:
                self.assertIn(ytz_face[i], range(6))
            else:
                self.assertEqual(ytz_face[i], -1)

    def test_non_yahtzee_normal_scoring(self):
        """Non-yahtzee rolls should use normal scoring in joker table."""
        from scoring import get_joker_score_table, score, Category
        from dice import roll_id, dice_list_to_counts

        table = get_joker_score_table()

        # Test that non-yahtzee rolls have normal scoring
        test_cases = [
            [1, 2, 3, 4, 5],  # Large straight
            [2, 2, 3, 3, 3],  # Full house
            [3, 3, 3, 4, 5],  # Three of a kind
        ]

        for dice in test_cases:
            counts = dice_list_to_counts(dice)
            roll = roll_id(counts)
            for cat in range(13):
                expected = score(cat, counts)
                self.assertEqual(table[roll, cat], expected,
                               f"Non-yahtzee {dice} cat {cat} should match normal score")


class TestTransitions(unittest.TestCase):
    """Tests for transitions.py module."""

    def test_keep_options_count(self):
        """Number of keep options should match product formula."""
        from transitions import enumerate_keeps, count_keeps
        from dice import dice_list_to_counts

        counts = dice_list_to_counts([1, 1, 3, 5, 6])  # (2,0,1,0,1,1)
        keeps = enumerate_keeps(counts)
        expected = (2+1) * 1 * (1+1) * 1 * (1+1) * (1+1)  # 24
        self.assertEqual(len(keeps), expected)
        self.assertEqual(count_keeps(counts), expected)

    def test_keep_all_option(self):
        """Keeping all dice should always be an option."""
        from transitions import enumerate_keeps
        from dice import dice_list_to_counts

        counts = dice_list_to_counts([3, 3, 3, 4, 4])
        keeps = enumerate_keeps(counts)
        self.assertIn(counts, keeps)

    def test_keep_none_option(self):
        """Keeping no dice should always be an option."""
        from transitions import enumerate_keeps
        from dice import dice_list_to_counts

        counts = dice_list_to_counts([1, 2, 3, 4, 5])
        keeps = enumerate_keeps(counts)
        self.assertIn((0, 0, 0, 0, 0, 0), keeps)

    def test_reroll_probability_sum(self):
        """Reroll outcomes should sum to probability 1."""
        from transitions import get_reroll_outcomes

        for num_dice in range(6):
            outcomes = get_reroll_outcomes(num_dice)
            total = sum(prob for _, prob in outcomes)
            self.assertTrue(isclose(total, 1.0, rel_tol=1e-9),
                          f"Reroll {num_dice} dice: prob sum = {total}")

    def test_transition_dist_probability_sum(self):
        """Transition distribution should sum to 1."""
        from transitions import get_keep_options, get_transition_dist, precompute_all
        from dice import roll_id, dice_list_to_counts

        precompute_all()

        counts = dice_list_to_counts([1, 1, 3, 5, 6])
        rid = roll_id(counts)

        for keep in get_keep_options(rid):
            dist = get_transition_dist(rid, keep)
            total = sum(prob for _, prob in dist)
            self.assertTrue(isclose(total, 1.0, rel_tol=1e-9))

    def test_keep_all_deterministic(self):
        """Keeping all dice should give deterministic outcome."""
        from transitions import get_transition_dist
        from dice import roll_id, dice_list_to_counts

        counts = dice_list_to_counts([2, 2, 2, 3, 3])
        rid = roll_id(counts)

        # Keep all
        dist = get_transition_dist(rid, counts)
        self.assertEqual(len(dist), 1)
        self.assertEqual(dist[0][0], rid)  # Same roll
        self.assertTrue(isclose(dist[0][1], 1.0, rel_tol=1e-9))


class TestEVSolver(unittest.TestCase):
    """Tests for ev_solver.py module."""

    @classmethod
    def setUpClass(cls):
        """Warm cache once for all EV tests."""
        from ev_solver import warm_cache
        warm_cache(verbose=False)

    def test_ev_full_mask_with_bonus(self):
        """Full mask with upper >= 63 should return bonus."""
        from ev_solver import ev_remaining, FULL_MASK, UPPER_BONUS

        ev = ev_remaining(FULL_MASK, 63)
        self.assertEqual(ev, UPPER_BONUS)

    def test_ev_full_mask_no_bonus(self):
        """Full mask with upper < 63 should return 0."""
        from ev_solver import ev_remaining, FULL_MASK

        ev = ev_remaining(FULL_MASK, 62)
        self.assertEqual(ev, 0)

    def test_ev_fresh_game_reasonable(self):
        """Expected score from fresh game should be reasonable."""
        from ev_solver import get_expected_score_fresh_game

        ev = get_expected_score_fresh_game()
        # Literature suggests optimal EV is around 254-255
        self.assertGreater(ev, 200)
        self.assertLess(ev, 300)

    def test_ev_monotonicity(self):
        """More filled categories should generally give lower remaining EV."""
        from ev_solver import ev_remaining

        # Empty vs having one category filled
        ev_empty = ev_remaining(0, 0)
        ev_one_filled = ev_remaining(1, 0)  # Ones filled

        self.assertGreater(ev_empty, ev_one_filled)

    def test_best_category_legal(self):
        """Best category should be among legal categories."""
        from ev_solver import best_category
        from scoring import get_legal_categories
        from dice import roll_id, dice_list_to_counts

        counts = dice_list_to_counts([1, 2, 3, 4, 5])
        rid = roll_id(counts)
        mask = (1 << 0) | (1 << 10)  # Ones and Large Straight filled

        cat, _ = best_category(rid, mask, 0)
        self.assertIn(cat, get_legal_categories(mask))


class TestPMFSolver(unittest.TestCase):
    """Tests for pmf_solver.py module."""

    @classmethod
    def setUpClass(cls):
        """Warm cache once for all PMF tests."""
        from ev_solver import warm_cache
        warm_cache(verbose=False)

    def test_pmf_probabilities_sum_to_one(self):
        """PMF probabilities should sum to approximately 1."""
        from pmf_solver import pmf_remaining

        # Exercise a real policy distribution without expanding all 13 turns.
        pmf = pmf_remaining(8191 ^ (1 << 12), 0)
        total = sum(pmf.values())
        self.assertTrue(isclose(total, 1.0, rel_tol=1e-3))

    def test_pmf_mean_matches_ev(self):
        """PMF mean should approximately match EV."""
        from pmf_solver import pmf_remaining, pmf_stats
        from ev_solver import ev_remaining

        mask = 8191 ^ (1 << 12)
        pmf = pmf_remaining(mask, 0)
        stats = pmf_stats(pmf)
        ev = ev_remaining(mask, 0)

        # Should be close (within 1 point due to pruning)
        self.assertTrue(abs(stats['mean'] - ev) < 1.0)

    def test_pmf_full_mask_with_bonus(self):
        """Full mask PMF should be deterministic."""
        from pmf_solver import pmf_remaining
        from ev_solver import FULL_MASK
        from scoring import UPPER_BONUS

        pmf = pmf_remaining(FULL_MASK, 63)
        self.assertEqual(len(pmf), 1)
        self.assertIn(UPPER_BONUS, pmf)


class TestMatch(unittest.TestCase):
    """Tests for match.py module."""

    @classmethod
    def setUpClass(cls):
        """Warm cache once for all match tests."""
        from ev_solver import warm_cache
        warm_cache(verbose=False)

    def test_win_probs_sum_to_one(self):
        """Win + tie + lose probabilities should sum to 1."""
        from match import win_probs

        mask = 8191 ^ (1 << 12)
        probs = win_probs(0, mask, 0, 0, mask, 0)
        total = probs['win_prob'] + probs['tie_prob'] + probs['lose_prob']
        self.assertTrue(isclose(total, 1.0, rel_tol=1e-6))

    def test_symmetric_game(self):
        """Equal states should give ~50% win probability."""
        from match import win_probs

        mask = 8191 ^ (1 << 12)
        probs = win_probs(0, mask, 0, 0, mask, 0)
        # Should be close to 50% (symmetric)
        self.assertTrue(isclose(probs['win_prob'], probs['lose_prob'], rel_tol=0.01))

    def test_ahead_means_higher_win_prob(self):
        """Player with higher score should have higher win probability."""
        from match import win_probs

        # A is ahead by 50 points, same state otherwise
        mask = 8191 ^ (1 << 12)
        probs = win_probs(100, mask, 15, 50, mask, 15)
        self.assertGreater(probs['win_prob'], 0.5)

    def test_more_turns_left_matters(self):
        """Player with more turns left has more variance."""
        from match import PlayerState, MatchState, get_match_analysis

        # A has one turn left, B has finished.
        # With same score, A has more opportunity to catch up or fall behind
        state_a = PlayerState(score=100, mask=8191 ^ (1 << 12), upper=15)
        state_b = PlayerState(score=100, mask=8191, upper=15)

        analysis = get_match_analysis(MatchState(state_a, state_b))
        # A has more remaining score (more turns)
        self.assertGreater(
            analysis['player_a']['remaining_mean'],
            analysis['player_b']['remaining_mean']
        )


class TestIntegration(unittest.TestCase):
    """Integration tests for the complete solver."""

    @classmethod
    def setUpClass(cls):
        """Warm cache once for all integration tests."""
        from ev_solver import warm_cache
        warm_cache(verbose=False)

    def test_recommendation_flow(self):
        """Test complete recommendation flow."""
        from ev_solver import get_recommendation

        # First roll of game
        rec = get_recommendation([1, 1, 3, 5, 6], mask=0, upper=0, rolls_remaining=2)

        self.assertIn('action', rec)
        self.assertIn('expected_value', rec)
        self.assertIn('category_options', rec)

        if rec['action'] == 'keep':
            self.assertIn('keep_dice', rec)
            self.assertIn('keep_counts', rec)
        else:
            self.assertIn('category', rec)
            self.assertIn('points', rec)

    def test_mid_game_scenario(self):
        """Test solver with mid-game state."""
        from ev_solver import get_recommendation
        from match import win_probs

        # Mid-game: some categories filled
        mask = (1 << 0) | (1 << 1) | (1 << 11)  # Ones, Twos, Yahtzee
        upper = 9  # 3 + 6 from Ones/Twos

        rec = get_recommendation([4, 4, 4, 5, 5], mask=mask, upper=upper, rolls_remaining=0)

        self.assertEqual(rec['action'], 'score')
        self.assertIsNotNone(rec['category'])

        # Win probability should compute
        # Match distributions are deliberately bounded to a late-game state;
        # the mid-game recommendation above still exercises the full EV table.
        late_mask = 8191 ^ (1 << 12)
        probs = win_probs(109, late_mask, upper, 100, late_mask, upper)
        self.assertTrue(isclose(
            probs['win_prob'] + probs['tie_prob'] + probs['lose_prob'],
            1.0, rel_tol=1e-6
        ))


def run_tests():
    """Run all tests with verbose output."""
    unittest.main(verbosity=2)


if __name__ == '__main__':
    run_tests()
