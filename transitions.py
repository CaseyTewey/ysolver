"""
Dice transition probabilities for Yahtzee rerolls.

This module handles:
- Enumerating all possible "keep" decisions from a roll
- Computing reroll outcome distributions
- Precomputing transition tables for fast DP
"""

from typing import List, Dict, Tuple
from dice import (
    Counts, enumerate_rolls, roll_id, id_to_roll,
    compositions, multinomial_prob
)

# Type aliases
KeepOption = Counts  # Which dice to keep (as counts)
TransitionDist = List[Tuple[int, float]]  # List of (roll_id, probability)


def enumerate_keeps(counts: Counts) -> List[KeepOption]:
    """
    Enumerate all possible keep decisions for a given roll.

    A keep is valid if 0 <= keep[i] <= counts[i] for all faces.
    This includes keeping all (reroll none) and keeping none (reroll all).

    Args:
        counts: Current dice counts

    Returns:
        List of all valid keep options (as count tuples)
    """
    keeps = []

    def generate(face: int, current: List[int]):
        if face == 6:
            keeps.append(tuple(current))
            return

        # For this face, we can keep 0 to counts[face] dice
        for k in range(counts[face] + 1):
            current.append(k)
            generate(face + 1, current)
            current.pop()

    generate(0, [])
    return keeps


def count_keeps(counts: Counts) -> int:
    """Count number of possible keep decisions without enumerating."""
    result = 1
    for c in counts:
        result *= (c + 1)
    return result


# Cache reroll outcomes for each number of dice (0-5)
_REROLL_OUTCOMES: Dict[int, List[Tuple[Counts, float]]] = {}


def get_reroll_outcomes(num_dice: int) -> List[Tuple[Counts, float]]:
    """
    Get all possible outcomes when rolling num_dice dice.

    Args:
        num_dice: Number of dice to roll (0-5)

    Returns:
        List of (outcome_counts, probability) pairs
    """
    if num_dice in _REROLL_OUTCOMES:
        return _REROLL_OUTCOMES[num_dice]

    if num_dice == 0:
        # No dice to roll - deterministic "outcome" of all zeros
        _REROLL_OUTCOMES[0] = [((0, 0, 0, 0, 0, 0), 1.0)]
        return _REROLL_OUTCOMES[0]

    # Generate all compositions of num_dice into 6 faces
    outcomes = compositions(num_dice, 6)
    result = [(outcome, multinomial_prob(outcome)) for outcome in outcomes]
    _REROLL_OUTCOMES[num_dice] = result
    return result


def compute_next_roll_dist(keep: KeepOption) -> TransitionDist:
    """
    Compute distribution of next roll state given a keep decision.

    Args:
        keep: Dice counts to keep

    Returns:
        List of (next_roll_id, probability) pairs
    """
    num_kept = sum(keep)
    num_reroll = 5 - num_kept

    reroll_outcomes = get_reroll_outcomes(num_reroll)

    result = []
    for reroll_counts, prob in reroll_outcomes:
        # Combined counts = kept + rerolled
        next_counts = tuple(k + r for k, r in zip(keep, reroll_counts))
        next_id = roll_id(next_counts)
        result.append((next_id, prob))

    return result


# Precomputed transition table
# Maps (current_roll_id, keep_option) -> List[(next_roll_id, probability)]
_TRANSITIONS: Dict[Tuple[int, KeepOption], TransitionDist] = None

# Maps roll_id -> List[keep_options]
_KEEP_OPTIONS: Dict[int, List[KeepOption]] = None


def _initialize_transitions():
    """Precompute all transition tables."""
    global _TRANSITIONS, _KEEP_OPTIONS

    if _TRANSITIONS is not None:
        return

    _TRANSITIONS = {}
    _KEEP_OPTIONS = {}

    all_rolls = enumerate_rolls()

    for roll_idx, counts in enumerate(all_rolls):
        keeps = enumerate_keeps(counts)
        _KEEP_OPTIONS[roll_idx] = keeps

        for keep in keeps:
            dist = compute_next_roll_dist(keep)
            _TRANSITIONS[(roll_idx, keep)] = dist


def get_keep_options(roll_idx: int) -> List[KeepOption]:
    """Get all possible keep decisions for a roll state."""
    _initialize_transitions()
    return _KEEP_OPTIONS[roll_idx]


def get_transition_dist(roll_idx: int, keep: KeepOption) -> TransitionDist:
    """Get the probability distribution of next states given keep decision."""
    _initialize_transitions()
    return _TRANSITIONS[(roll_idx, keep)]


def precompute_all():
    """Force precomputation of all tables (useful for startup)."""
    _initialize_transitions()

    # Also precompute reroll outcomes for all dice counts
    for n in range(6):
        get_reroll_outcomes(n)


# Statistics about the precomputed tables
def get_stats() -> Dict:
    """Get statistics about precomputed tables."""
    _initialize_transitions()

    total_keeps = sum(len(keeps) for keeps in _KEEP_OPTIONS.values())
    total_transitions = sum(len(dist) for dist in _TRANSITIONS.values())

    return {
        "num_roll_states": len(_KEEP_OPTIONS),
        "total_keep_options": total_keeps,
        "avg_keeps_per_roll": total_keeps / len(_KEEP_OPTIONS),
        "total_transition_entries": total_transitions,
    }


# Initial roll distribution (rolling 5 fresh dice)
_INITIAL_ROLL_DIST: TransitionDist = None


def get_initial_roll_dist() -> TransitionDist:
    """Get probability distribution for rolling 5 fresh dice."""
    global _INITIAL_ROLL_DIST

    if _INITIAL_ROLL_DIST is not None:
        return _INITIAL_ROLL_DIST

    # Rolling 5 dice is equivalent to keeping nothing
    empty_keep = (0, 0, 0, 0, 0, 0)
    _INITIAL_ROLL_DIST = compute_next_roll_dist(empty_keep)
    return _INITIAL_ROLL_DIST


if __name__ == "__main__":
    from dice import dice_list_to_counts, counts_to_dice_list

    print("Precomputing transitions...")
    precompute_all()
    stats = get_stats()
    print(f"Statistics:")
    for k, v in stats.items():
        print(f"  {k}: {v}")

    # Test keep enumeration
    test_dice = [1, 1, 3, 5, 6]
    test_counts = dice_list_to_counts(test_dice)
    test_id = roll_id(test_counts)

    keeps = get_keep_options(test_id)
    print(f"\nDice {test_dice} has {len(keeps)} possible keep options")

    # Show a few examples
    print("\nSample keep options:")
    for keep in keeps[:5]:
        kept_dice = counts_to_dice_list(keep)
        print(f"  Keep {kept_dice} (counts: {keep})")

    # Test transition for keeping pair of 1s
    keep_ones = (2, 0, 0, 0, 0, 0)  # Keep two 1s
    if keep_ones in keeps:
        dist = get_transition_dist(test_id, keep_ones)
        print(f"\nKeeping two 1s gives {len(dist)} possible outcomes")
        print("Top 5 most likely outcomes:")
        sorted_dist = sorted(dist, key=lambda x: -x[1])[:5]
        for next_id, prob in sorted_dist:
            next_counts = id_to_roll(next_id)
            next_dice = counts_to_dice_list(next_counts)
            print(f"  {next_dice}: {prob:.4f}")

    # Verify probability sums
    print("\nVerifying probability sums...")
    for keep in keeps[:3]:
        dist = get_transition_dist(test_id, keep)
        total = sum(p for _, p in dist)
        print(f"  Keep {keep}: total prob = {total:.10f}")
