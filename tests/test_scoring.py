"""scoring.py: category scores and the Joker score table (the rules themselves live in engine)."""
import pytest

from dice import dice_list_to_counts, roll_id
from scoring import (
    NUM_CATEGORIES, Category, get_joker_score_table, get_yahtzee_face, is_yahtzee_roll,
    precompute_score_table, score,
)

C = dice_list_to_counts


def _yahtzee_rid(face: int) -> int:
    counts = [0] * 6
    counts[face] = 5
    return roll_id(tuple(counts))


class TestScoring:
    def test_upper_section(self):
        counts = C([1, 1, 1, 2, 3])
        assert score(Category.ONES, counts) == 3
        assert score(Category.TWOS, counts) == 2
        assert score(Category.THREES, counts) == 3
        assert score(Category.FOURS, counts) == 0
        assert score(Category.SIXES, C([6, 6, 6, 6, 5])) == 24

    def test_three_of_a_kind(self):
        assert score(Category.THREE_OF_A_KIND, C([3, 3, 3, 2, 1])) == 12
        assert score(Category.THREE_OF_A_KIND, C([1, 2, 3, 4, 5])) == 0
        assert score(Category.THREE_OF_A_KIND, C([6, 6, 6, 6, 6])) == 30

    def test_four_of_a_kind(self):
        assert score(Category.FOUR_OF_A_KIND, C([4, 4, 4, 4, 1])) == 17
        assert score(Category.FOUR_OF_A_KIND, C([3, 3, 3, 2, 1])) == 0

    def test_full_house(self):
        assert score(Category.FULL_HOUSE, C([2, 2, 3, 3, 3])) == 25
        assert score(Category.FULL_HOUSE, C([2, 2, 2, 3, 3])) == 25
        assert score(Category.FULL_HOUSE, C([1, 1, 1, 1, 1])) == 0   # a Yahtzee is not a Full House
        assert score(Category.FULL_HOUSE, C([2, 2, 2, 2, 3])) == 0

    def test_small_straight(self):
        assert score(Category.SMALL_STRAIGHT, C([1, 2, 3, 4, 6])) == 30
        assert score(Category.SMALL_STRAIGHT, C([2, 3, 4, 5, 5])) == 30
        assert score(Category.SMALL_STRAIGHT, C([3, 4, 5, 6, 6])) == 30
        assert score(Category.SMALL_STRAIGHT, C([1, 2, 3, 5, 6])) == 0

    def test_large_straight(self):
        assert score(Category.LARGE_STRAIGHT, C([1, 2, 3, 4, 5])) == 40
        assert score(Category.LARGE_STRAIGHT, C([2, 3, 4, 5, 6])) == 40
        assert score(Category.LARGE_STRAIGHT, C([1, 2, 3, 4, 6])) == 0

    def test_yahtzee(self):
        assert score(Category.YAHTZEE, C([5, 5, 5, 5, 5])) == 50
        assert score(Category.YAHTZEE, C([5, 5, 5, 5, 4])) == 0

    def test_chance(self):
        assert score(Category.CHANCE, C([1, 2, 3, 4, 5])) == 15
        assert score(Category.CHANCE, C([6, 6, 6, 6, 6])) == 30

    def test_score_table_dimensions(self):
        table = precompute_score_table()
        assert len(table) == 252
        assert all(len(row) == NUM_CATEGORIES for row in table)
        rid = roll_id(C([6, 6, 6, 6, 6]))
        assert table[rid] == [0, 0, 0, 0, 0, 30, 30, 30, 0, 0, 0, 50, 30]


class TestJokerScoring:
    def test_yahtzee_detection(self):
        for face in range(6):
            rid = _yahtzee_rid(face)
            assert is_yahtzee_roll(rid)
            assert get_yahtzee_face(rid) == face
        for counts in [(4, 1, 0, 0, 0, 0), (3, 2, 0, 0, 0, 0), (1, 1, 1, 1, 1, 0), (2, 2, 1, 0, 0, 0)]:
            rid = roll_id(counts)
            assert not is_yahtzee_roll(rid)
            assert get_yahtzee_face(rid) == -1

    @pytest.mark.parametrize("cat, value", [(Category.FULL_HOUSE, 25), (Category.SMALL_STRAIGHT, 30),
                                            (Category.LARGE_STRAIGHT, 40)])
    def test_joker_values_for_every_yahtzee(self, cat, value):
        table = get_joker_score_table()
        for face in range(6):
            assert table[_yahtzee_rid(face), cat] == value

    def test_joker_upper_section_and_sums(self):
        table = get_joker_score_table()
        for face in range(6):
            rid = _yahtzee_rid(face)
            assert table[rid, face] == (face + 1) * 5
            for other in range(6):
                if other != face:
                    assert table[rid, other] == 0
            for cat in (Category.THREE_OF_A_KIND, Category.FOUR_OF_A_KIND, Category.CHANCE):
                assert table[rid, cat] == (face + 1) * 5
            assert table[rid, Category.YAHTZEE] == 50

    def test_non_yahtzee_rows_use_normal_scoring(self):
        table = get_joker_score_table()
        for dice in ([1, 2, 3, 4, 5], [2, 2, 3, 3, 3], [3, 3, 3, 4, 5], [6, 6, 6, 6, 1]):
            counts = C(dice)
            rid = roll_id(counts)
            for cat in range(NUM_CATEGORIES):
                assert table[rid, cat] == score(cat, counts)
