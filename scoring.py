"""
Yahtzee scoring: the 13 boxes, the 252 x 13 score table and the Joker score table.

The game rules that depend on state (Joker forcing, the 100 point Yahtzee bonus, which boxes
are legal) live in ONE place, engine._fill_options. This module only says what a roll is worth
in a box: score() under the normal rules, and get_joker_score_table() for a Yahtzee rolled after
the Yahtzee box is filled (Full House 25, Small Straight 30, Large Straight 40).
"""

from typing import List, Dict
from enum import IntEnum
import numpy as np
from dice import Counts, enumerate_rolls, id_to_roll, roll_id

# Category enumeration
class Category(IntEnum):
    """The 13 Yahtzee categories."""
    # Upper section (0-5)
    ONES = 0
    TWOS = 1
    THREES = 2
    FOURS = 3
    FIVES = 4
    SIXES = 5
    # Lower section (6-12)
    THREE_OF_A_KIND = 6
    FOUR_OF_A_KIND = 7
    FULL_HOUSE = 8
    SMALL_STRAIGHT = 9
    LARGE_STRAIGHT = 10
    YAHTZEE = 11
    CHANCE = 12


CATEGORY_NAMES = [
    "Ones", "Twos", "Threes", "Fours", "Fives", "Sixes",
    "Three of a Kind", "Four of a Kind", "Full House",
    "Small Straight", "Large Straight", "Yahtzee", "Chance"
]

NUM_CATEGORIES = 13
UPPER_CATEGORIES = set(range(6))
LOWER_CATEGORIES = set(range(6, 13))
UPPER_BONUS_THRESHOLD = 63
UPPER_BONUS = 35
YAHTZEE_SCORE = 50


def _dice_sum(counts: Counts) -> int:
    """Calculate sum of all dice."""
    return sum((face + 1) * count for face, count in enumerate(counts))


def _has_n_of_a_kind(counts: Counts, n: int) -> bool:
    """Check if there are n or more of any single face."""
    return any(c >= n for c in counts)


def _is_full_house(counts: Counts) -> bool:
    """Check for full house: exactly one pair and one triple."""
    sorted_counts = sorted(counts, reverse=True)
    return sorted_counts[0] == 3 and sorted_counts[1] == 2


def _is_yahtzee(counts: Counts) -> bool:
    """Check for Yahtzee: all 5 dice the same."""
    return 5 in counts


def _has_small_straight(counts: Counts) -> bool:
    """
    Check for small straight: 4 consecutive faces.
    Valid patterns: 1-2-3-4, 2-3-4-5, 3-4-5-6
    """
    # Convert counts to presence (1 if any, 0 otherwise)
    presence = tuple(1 if c > 0 else 0 for c in counts)

    # Check for 4 consecutive
    # 1-2-3-4: positions 0,1,2,3
    if presence[0] and presence[1] and presence[2] and presence[3]:
        return True
    # 2-3-4-5: positions 1,2,3,4
    if presence[1] and presence[2] and presence[3] and presence[4]:
        return True
    # 3-4-5-6: positions 2,3,4,5
    if presence[2] and presence[3] and presence[4] and presence[5]:
        return True
    return False


def _has_large_straight(counts: Counts) -> bool:
    """
    Check for large straight: 5 consecutive faces.
    Valid patterns: 1-2-3-4-5 or 2-3-4-5-6
    """
    presence = tuple(1 if c > 0 else 0 for c in counts)

    # 1-2-3-4-5: positions 0,1,2,3,4
    if presence[0] and presence[1] and presence[2] and presence[3] and presence[4]:
        return True
    # 2-3-4-5-6: positions 1,2,3,4,5
    if presence[1] and presence[2] and presence[3] and presence[4] and presence[5]:
        return True
    return False


def score(cat: int, counts: Counts) -> int:
    """
    Points for scoring the roll `counts` in box `cat` under the normal rules.

    A natural Yahtzee scores 0 in Full House and in the straights here. The Joker rule that
    lets it count in full once the Yahtzee box is filled lives in engine._fill_options, which
    reads get_joker_score_table() for those cases.
    """
    if cat in UPPER_CATEGORIES:
        return counts[cat] * (cat + 1)
    if cat == Category.THREE_OF_A_KIND:
        return _dice_sum(counts) if _has_n_of_a_kind(counts, 3) else 0
    if cat == Category.FOUR_OF_A_KIND:
        return _dice_sum(counts) if _has_n_of_a_kind(counts, 4) else 0
    if cat == Category.FULL_HOUSE:
        return 25 if _is_full_house(counts) else 0
    if cat == Category.SMALL_STRAIGHT:
        return 30 if _has_small_straight(counts) else 0
    if cat == Category.LARGE_STRAIGHT:
        return 40 if _has_large_straight(counts) else 0
    if cat == Category.YAHTZEE:
        return YAHTZEE_SCORE if _is_yahtzee(counts) else 0
    if cat == Category.CHANCE:
        return _dice_sum(counts)
    return 0


def precompute_score_table(rolls: List[Counts] = None) -> List[List[int]]:
    """
    Precompute scores for all roll/category combinations.

    Returns:
        2D list: score_table[roll_id][category] = score
    """
    if rolls is None:
        rolls = enumerate_rolls()

    score_table = []
    for counts in rolls:
        row = []
        for cat in range(NUM_CATEGORIES):
            row.append(score(cat, counts))
        score_table.append(row)

    return score_table


def get_legal_categories(mask: int) -> List[int]:
    """
    Get list of unfilled (legal) categories from a bitmask.

    Args:
        mask: 13-bit integer where bit i=1 means category i is filled

    Returns:
        List of category indices that are still available
    """
    return [cat for cat in range(NUM_CATEGORIES) if not (mask & (1 << cat))]


def is_upper_category(cat: int) -> bool:
    """Check if category is in upper section."""
    return cat in UPPER_CATEGORIES


def calculate_upper_subtotal(filled_cats: Dict[int, int]) -> int:
    """
    Calculate upper section subtotal from filled categories.

    Args:
        filled_cats: Dict mapping category -> score for filled categories

    Returns:
        Sum of upper section scores (before bonus)
    """
    return sum(filled_cats.get(cat, 0) for cat in UPPER_CATEGORIES)


# Precomputed score table (lazy initialization)
_SCORE_TABLE: List[List[int]] = None


def get_score_table() -> List[List[int]]:
    """Get the precomputed score table, computing if necessary."""
    global _SCORE_TABLE
    if _SCORE_TABLE is None:
        _SCORE_TABLE = precompute_score_table()
    return _SCORE_TABLE


# ============================================================================
# JOKER MODE FUNCTIONS
# ============================================================================

NUM_ROLLS = 252  # Total unique 5-dice multisets


def is_yahtzee_roll(roll_idx: int) -> bool:
    """
    Check if a roll (by index) is a Yahtzee (all 5 dice the same).

    Args:
        roll_idx: Roll index (0-251)

    Returns:
        True if the roll is a Yahtzee
    """
    counts = id_to_roll(roll_idx)
    return max(counts) == 5


def get_yahtzee_face(roll_idx: int) -> int:
    """
    For a Yahtzee roll, return which face (0-5 for dice values 1-6).

    Args:
        roll_idx: Roll index (0-251)

    Returns:
        Face index (0-5) if Yahtzee, -1 if not a Yahtzee
    """
    counts = id_to_roll(roll_idx)
    for face, count in enumerate(counts):
        if count == 5:
            return face
    return -1  # Not a yahtzee


def get_joker_score_table() -> np.ndarray:
    """
    Get precomputed score table with joker exception rules.

    For Yahtzee rolls used as jokers, special scoring applies:
    - Full House = 25 (even though it's 5-of-a-kind)
    - Small Straight = 30 (even though no straight)
    - Large Straight = 40 (even though no straight)
    - Three/Four of a Kind, Chance = sum of dice

    Returns:
        numpy array of shape (252, 13) with joker scores
    """
    table = np.zeros((NUM_ROLLS, NUM_CATEGORIES), dtype=np.int32)
    rolls = enumerate_rolls()

    for roll_idx, counts in enumerate(rolls):
        is_ytz = max(counts) == 5

        for cat in range(NUM_CATEGORIES):
            if is_ytz:
                # Joker scoring exceptions
                if cat == Category.FULL_HOUSE:
                    table[roll_idx, cat] = 25
                elif cat == Category.SMALL_STRAIGHT:
                    table[roll_idx, cat] = 30
                elif cat == Category.LARGE_STRAIGHT:
                    table[roll_idx, cat] = 40
                else:
                    # Normal scoring for other categories
                    table[roll_idx, cat] = score(cat, counts)
            else:
                # Non-yahtzee: normal scoring
                table[roll_idx, cat] = score(cat, counts)

    return table


if __name__ == "__main__":
    from dice import dice_list_to_counts

    # Test various scoring scenarios
    test_cases = [
        ([1, 1, 1, 1, 1], "Five ones (Yahtzee)"),
        ([1, 2, 3, 4, 5], "Small straight / Large straight"),
        ([2, 3, 4, 5, 6], "Large straight"),
        ([1, 1, 1, 2, 2], "Full house"),
        ([3, 3, 3, 3, 5], "Four of a kind"),
        ([2, 2, 2, 4, 6], "Three of a kind"),
        ([1, 3, 4, 5, 6], "Small straight only"),
    ]

    print("Scoring tests:")
    print("-" * 60)
    for dice, description in test_cases:
        counts = dice_list_to_counts(dice)
        print(f"\nDice: {dice} - {description}")
        for cat in range(NUM_CATEGORIES):
            s = score(cat, counts)
            if s > 0:
                print(f"  {CATEGORY_NAMES[cat]}: {s}")

    # Verify precomputed table
    print("\n" + "=" * 60)
    print("Precomputed score table verification:")
    table = precompute_score_table()
    print(f"Table size: {len(table)} rolls x {len(table[0])} categories")

    # Check a known roll
    yahtzee_counts = dice_list_to_counts([6, 6, 6, 6, 6])
    rid = roll_id(yahtzee_counts)
    print(f"\nYahtzee of 6s (roll_id={rid}):")
    for cat in range(NUM_CATEGORIES):
        if table[rid][cat] > 0:
            print(f"  {CATEGORY_NAMES[cat]}: {table[rid][cat]}")
