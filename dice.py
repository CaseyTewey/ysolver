"""
Dice multiset enumeration and multinomial probability calculations.

This module handles:
- Enumeration of all 252 unique 5-dice multisets
- Mapping between dice counts and indices
- Multinomial probability calculations for rerolls
"""

from typing import Tuple, List, Dict
from functools import lru_cache
from math import factorial
from numbers import Integral

# Type alias for dice counts: (count_of_1s, count_of_2s, ..., count_of_6s)
Counts = Tuple[int, int, int, int, int, int]

# Global caches populated on module load
_ALL_ROLLS: List[Counts] = []
_ROLL_TO_ID: Dict[Counts, int] = {}


def _generate_compositions(n: int, k: int = 6) -> List[Counts]:
    """
    Generate all compositions of n into k non-negative parts.
    For n=5 dice and k=6 faces, this gives C(10,5) = 252 unique multisets.
    """
    if k == 1:
        return [(n,)]

    result = []
    for i in range(n + 1):
        for rest in _generate_compositions(n - i, k - 1):
            result.append((i,) + rest)
    return result


def _initialize_rolls():
    """Initialize the global roll enumeration tables."""
    global _ALL_ROLLS, _ROLL_TO_ID

    if _ALL_ROLLS:
        return  # Already initialized

    _ALL_ROLLS = _generate_compositions(5, 6)
    _ROLL_TO_ID = {counts: idx for idx, counts in enumerate(_ALL_ROLLS)}


def enumerate_rolls() -> List[Counts]:
    """Return list of all 252 unique 5-dice multisets."""
    _initialize_rolls()
    return _ALL_ROLLS.copy()


def roll_id(counts: Counts) -> int:
    """Convert a dice count tuple to its canonical index (0-251)."""
    _initialize_rolls()
    return _ROLL_TO_ID[counts]


def id_to_roll(i: int) -> Counts:
    """Convert an index (0-251) back to its dice count tuple."""
    _initialize_rolls()
    return _ALL_ROLLS[i]


def compositions(n: int, k: int = 6) -> List[Counts]:
    """
    Generate all ways to distribute n dice across k faces.
    Returns list of count tuples.
    """
    return _generate_compositions(n, k)


@lru_cache(maxsize=1024)
def multinomial_prob(x: Counts) -> float:
    """
    Calculate probability of rolling exactly the counts in x.

    For r = sum(x) dice, probability is:
    r! / (x1! * x2! * ... * x6!) * (1/6)^r
    """
    r = sum(x)
    if r == 0:
        return 1.0

    # Multinomial coefficient: r! / (x1! * ... * x6!)
    numerator = factorial(r)
    denominator = 1
    for count in x:
        denominator *= factorial(count)

    coeff = numerator / denominator
    prob = coeff * ((1/6) ** r)

    return prob


def dice_list_to_counts(dice: List[int]) -> Counts:
    """
    Convert a list of dice values [1-6] to a counts tuple.
    Example: [1, 1, 3, 5, 6] -> (2, 0, 1, 0, 1, 1)
    """
    counts = [0, 0, 0, 0, 0, 0]
    for d in dice:
        if isinstance(d, bool) or not isinstance(d, Integral) or not 1 <= d <= 6:
            raise ValueError("Dice values must be integers from 1 to 6")
        counts[d - 1] += 1
    return tuple(counts)


def counts_to_dice_list(counts: Counts) -> List[int]:
    """
    Convert a counts tuple to a sorted list of dice values.
    Example: (2, 0, 1, 0, 1, 1) -> [1, 1, 3, 5, 6]
    """
    result = []
    for face, count in enumerate(counts, 1):
        result.extend([face] * count)
    return result


def initial_roll_distribution() -> List[Tuple[int, float]]:
    """
    Get the probability distribution for the initial roll of 5 dice.
    Returns list of (roll_id, probability) pairs.
    """
    _initialize_rolls()
    result = []
    for idx, counts in enumerate(_ALL_ROLLS):
        prob = multinomial_prob(counts)
        result.append((idx, prob))
    return result


# Initialize on import
_initialize_rolls()


if __name__ == "__main__":
    # Quick sanity check
    rolls = enumerate_rolls()
    print(f"Number of unique 5-dice rolls: {len(rolls)}")

    # Verify probabilities sum to 1
    total_prob = sum(multinomial_prob(r) for r in rolls)
    print(f"Total probability: {total_prob:.10f}")

    # Example conversions
    dice = [1, 1, 3, 5, 6]
    counts = dice_list_to_counts(dice)
    print(f"Dice {dice} -> Counts {counts}")
    print(f"Counts {counts} -> Dice {counts_to_dice_list(counts)}")
    print(f"Roll ID: {roll_id(counts)}")
