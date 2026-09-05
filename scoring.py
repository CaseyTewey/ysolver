"""
Yahtzee scoring functions and precomputation.

This module handles:
- Scoring each of the 13 categories
- Precomputing score tables for all 252 roll states
- Category enumeration and metadata
"""

from typing import List, Dict, Tuple, Optional
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


def score(cat: int, counts: Counts, joker_rules: bool = False,
          yahtzee_filled: bool = False, has_yahtzee_bonus: bool = False) -> int:
    """
    Calculate score for a given category and dice counts.

    Args:
        cat: Category index (0-12)
        counts: Tuple of counts for faces 1-6
        joker_rules: Whether to apply Yahtzee joker rules
        yahtzee_filled: Whether Yahtzee box is already filled
        has_yahtzee_bonus: Whether player has scored a Yahtzee (bonus eligibility;
            Joker category scores also apply after a scratched Yahtzee)

    Returns:
        Score for that category (0 if invalid)
    """
    # Handle Yahtzee joker rules
    is_yahtzee = _is_yahtzee(counts)

    if joker_rules and is_yahtzee and yahtzee_filled:
        # Yahtzee joker: can score in any category with special rules
        # Upper section: must use corresponding face
        if cat in UPPER_CATEGORIES:
            face_value = cat + 1
            if counts[cat] == 5:
                return face_value * 5
            else:
                # Forced to use upper section but wrong face
                return 0

        # Lower section with joker
        if cat == Category.THREE_OF_A_KIND:
            return _dice_sum(counts)
        elif cat == Category.FOUR_OF_A_KIND:
            return _dice_sum(counts)
        elif cat == Category.FULL_HOUSE:
            return 25  # Always scores 25 as joker
        elif cat == Category.SMALL_STRAIGHT:
            return 30  # Always scores 30 as joker
        elif cat == Category.LARGE_STRAIGHT:
            return 40  # Always scores 40 as joker
        elif cat == Category.CHANCE:
            return _dice_sum(counts)

    # Standard scoring rules
    if cat in UPPER_CATEGORIES:
        # Upper section: sum of matching face value
        face_value = cat + 1
        return counts[cat] * face_value

    elif cat == Category.THREE_OF_A_KIND:
        if _has_n_of_a_kind(counts, 3):
            return _dice_sum(counts)
        return 0

    elif cat == Category.FOUR_OF_A_KIND:
        if _has_n_of_a_kind(counts, 4):
            return _dice_sum(counts)
        return 0

    elif cat == Category.FULL_HOUSE:
        if _is_full_house(counts):
            return 25
        return 0

    elif cat == Category.SMALL_STRAIGHT:
        if _has_small_straight(counts):
            return 30
        return 0

    elif cat == Category.LARGE_STRAIGHT:
        if _has_large_straight(counts):
            return 40
        return 0

    elif cat == Category.YAHTZEE:
        if is_yahtzee:
            return YAHTZEE_SCORE
        return 0

    elif cat == Category.CHANCE:
        return _dice_sum(counts)

    return 0


def precompute_score_table(rolls: List[Counts] = None,
                           joker_rules: bool = False) -> List[List[int]]:
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
            row.append(score(cat, counts, joker_rules=joker_rules))
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


def get_legal_categories_joker(roll_idx: int, mask: int,
                             yahtzee_status: int) -> List[int]:
    """Apply Hasbro's forced Joker placement, including a scratched Yahtzee.

    Once the Yahtzee box is filled, five equal dice must use their matching
    upper box, then an open lower box, then another upper box for zero.
    Only status 2 earns the separate 100-point bonus.
    """
    legal = get_legal_categories(mask)
    if yahtzee_status == 0 or not is_yahtzee_roll(roll_idx):
        return legal
    forced = get_forced_category_joker(roll_idx, mask)
    if forced is not None:
        return [forced]
    lower = [cat for cat in legal if cat >= 6]
    return lower or legal


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


def get_score_table(joker_rules: bool = False) -> List[List[int]]:
    """Get the precomputed score table, computing if necessary."""
    global _SCORE_TABLE
    if _SCORE_TABLE is None:
        _SCORE_TABLE = precompute_score_table(joker_rules=joker_rules)
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


def get_forced_category_joker(roll_idx: int, mask: int) -> Optional[int]:
    """
    For joker rules, determine if there's a forced category.

    When a player rolls a Yahtzee and has already scored in the Yahtzee
    category with 50 points, they must use the corresponding upper section
    category if it's still available.

    Args:
        roll_idx: Roll index (0-251)
        mask: 13-bit filled category mask (bit i=1 means category i is filled)

    Returns:
        Category index if forced, None if player has free choice
    """
    if not is_yahtzee_roll(roll_idx):
        return None

    face = get_yahtzee_face(roll_idx)
    if face < 0:
        return None

    upper_cat = face  # Categories 0-5 correspond to faces 1-6 (0-indexed)

    # Must use upper section if available
    if not (mask & (1 << upper_cat)):
        return upper_cat

    return None  # Upper section filled, free to choose from lower section


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


# Precomputed joker score table (lazy initialization)
_JOKER_SCORE_TABLE: np.ndarray = None


def get_joker_score_table_cached() -> np.ndarray:
    """Get the precomputed joker score table, computing if necessary."""
    global _JOKER_SCORE_TABLE
    if _JOKER_SCORE_TABLE is None:
        _JOKER_SCORE_TABLE = get_joker_score_table()
    return _JOKER_SCORE_TABLE


# Precomputed yahtzee detection arrays (lazy initialization)
_IS_YAHTZEE: np.ndarray = None
_YAHTZEE_FACE: np.ndarray = None


def get_yahtzee_detection_arrays() -> Tuple[np.ndarray, np.ndarray]:
    """
    Get precomputed arrays for fast yahtzee detection.

    Returns:
        Tuple of (is_yahtzee, yahtzee_face) arrays:
        - is_yahtzee[roll_idx] = True if roll is a Yahtzee
        - yahtzee_face[roll_idx] = face (0-5) if Yahtzee, -1 otherwise
    """
    global _IS_YAHTZEE, _YAHTZEE_FACE

    if _IS_YAHTZEE is None:
        _IS_YAHTZEE = np.array(
            [is_yahtzee_roll(i) for i in range(NUM_ROLLS)],
            dtype=np.bool_
        )
        _YAHTZEE_FACE = np.array(
            [get_yahtzee_face(i) for i in range(NUM_ROLLS)],
            dtype=np.int8
        )

    return _IS_YAHTZEE, _YAHTZEE_FACE


if __name__ == "__main__":
    from dice import dice_list_to_counts, roll_id

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
