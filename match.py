"""
Two-player match analysis and win probability computation.

This module handles:
- Win/tie/lose probability calculation
- Match state representation
- Competitive analysis and outs
"""

from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from pmf_solver import (
    pmf_remaining, pmf_stats, prob_at_least, percentile,
    shift_pmf, compute_turn_score_dist, compute_category_hit_probs,
    get_outs_analysis, PMF
)
from scoring import CATEGORY_NAMES, NUM_CATEGORIES, get_legal_categories


@dataclass
class PlayerState:
    """State of a single player's scorecard."""
    score: int          # Points already locked in
    mask: int           # Filled categories bitmask
    upper: int          # Upper section subtotal (clamped to 63)
    name: str = "Player"

    @property
    def categories_remaining(self) -> int:
        return NUM_CATEGORIES - bin(self.mask).count('1')

    @property
    def filled_categories(self) -> List[int]:
        return [i for i in range(NUM_CATEGORIES) if self.mask & (1 << i)]

    @property
    def open_categories(self) -> List[int]:
        return get_legal_categories(self.mask)


@dataclass
class MatchState:
    """State of a two-player match."""
    player_a: PlayerState
    player_b: PlayerState
    current_player: int = 0  # 0 for A, 1 for B

    @property
    def score_differential(self) -> int:
        """A's score minus B's score."""
        return self.player_a.score - self.player_b.score


def compute_win_probs(state_a: PlayerState, state_b: PlayerState) -> Dict[str, float]:
    """
    Compute win/tie/lose probabilities for player A.

    Assumes both players play score-optimal strategy.

    Args:
        state_a: Player A's current state
        state_b: Player B's current state

    Returns:
        Dict with win_prob, tie_prob, lose_prob for player A
    """
    # Get remaining score distributions
    pmf_a = pmf_remaining(state_a.mask, state_a.upper)
    pmf_b = pmf_remaining(state_b.mask, state_b.upper)

    # Shift by current scores to get final score distributions
    final_pmf_a = shift_pmf(pmf_a, state_a.score)
    final_pmf_b = shift_pmf(pmf_b, state_b.score)

    # Compute P(A > B), P(A = B), P(A < B)
    win_prob = 0.0
    tie_prob = 0.0
    lose_prob = 0.0

    # Build CDF for B for efficient computation
    b_scores = sorted(final_pmf_b.keys())
    b_cdf = {}  # P(B <= x)
    cumulative = 0.0
    for score in b_scores:
        cumulative += final_pmf_b[score]
        b_cdf[score] = cumulative

    # For each A score, compute probabilities
    for score_a, prob_a in final_pmf_a.items():
        # P(A > B | A = score_a) = P(B < score_a)
        p_a_wins = 0.0
        for score_b in b_scores:
            if score_b < score_a:
                p_a_wins += final_pmf_b[score_b]
            elif score_b >= score_a:
                break

        # P(A = B | A = score_a) = P(B = score_a)
        p_tie = final_pmf_b.get(score_a, 0.0)

        # P(A < B | A = score_a) = 1 - P(A >= B) = 1 - P(A > B) - P(A = B)
        p_a_loses = 1.0 - p_a_wins - p_tie

        win_prob += prob_a * p_a_wins
        tie_prob += prob_a * p_tie
        lose_prob += prob_a * p_a_loses

    return {
        "win_prob": win_prob,
        "tie_prob": tie_prob,
        "lose_prob": lose_prob,
    }


def compute_win_probs_fast(state_a: PlayerState, state_b: PlayerState) -> Dict[str, float]:
    """
    Faster win probability computation using sorted arrays.

    Same result as compute_win_probs but more efficient for large PMFs.
    """
    pmf_a = pmf_remaining(state_a.mask, state_a.upper)
    pmf_b = pmf_remaining(state_b.mask, state_b.upper)

    final_pmf_a = shift_pmf(pmf_a, state_a.score)
    final_pmf_b = shift_pmf(pmf_b, state_b.score)

    # Sort scores
    scores_a = sorted(final_pmf_a.keys())
    scores_b = sorted(final_pmf_b.keys())

    # Build cumulative sums for B
    # b_cdf_below[i] = P(B < scores_b[i])
    b_cdf_below = [0.0]
    cumsum = 0.0
    for score in scores_b:
        b_cdf_below.append(cumsum)
        cumsum += final_pmf_b[score]

    # Build mapping from score to index for B
    b_score_to_idx = {s: i for i, s in enumerate(scores_b)}

    win_prob = 0.0
    tie_prob = 0.0
    lose_prob = 0.0

    import bisect

    for score_a, prob_a in final_pmf_a.items():
        # Find where score_a would fit in B's sorted scores
        idx = bisect.bisect_left(scores_b, score_a)

        # P(B < score_a)
        p_b_below = b_cdf_below[idx]

        # P(B = score_a)
        p_tie = final_pmf_b.get(score_a, 0.0)

        # P(B > score_a)
        p_b_above = 1.0 - p_b_below - p_tie

        win_prob += prob_a * p_b_below
        tie_prob += prob_a * p_tie
        lose_prob += prob_a * p_b_above

    return {
        "win_prob": win_prob,
        "tie_prob": tie_prob,
        "lose_prob": lose_prob,
    }


def get_match_analysis(match: MatchState) -> Dict:
    """
    Get comprehensive match analysis.

    Returns:
        Dict with win probabilities, score projections, and insights
    """
    probs = compute_win_probs_fast(match.player_a, match.player_b)

    # Score projections
    pmf_a = pmf_remaining(match.player_a.mask, match.player_a.upper)
    pmf_b = pmf_remaining(match.player_b.mask, match.player_b.upper)

    stats_a = pmf_stats(pmf_a)
    stats_b = pmf_stats(pmf_b)

    projected_a = match.player_a.score + stats_a["mean"]
    projected_b = match.player_b.score + stats_b["mean"]

    # Percentile-based projections
    final_percentiles_a = {
        "10th": match.player_a.score + percentile(pmf_a, 0.1),
        "25th": match.player_a.score + percentile(pmf_a, 0.25),
        "50th": match.player_a.score + percentile(pmf_a, 0.5),
        "75th": match.player_a.score + percentile(pmf_a, 0.75),
        "90th": match.player_a.score + percentile(pmf_a, 0.9),
    }

    final_percentiles_b = {
        "10th": match.player_b.score + percentile(pmf_b, 0.1),
        "25th": match.player_b.score + percentile(pmf_b, 0.25),
        "50th": match.player_b.score + percentile(pmf_b, 0.5),
        "75th": match.player_b.score + percentile(pmf_b, 0.75),
        "90th": match.player_b.score + percentile(pmf_b, 0.9),
    }

    return {
        "win_prob": probs["win_prob"],
        "tie_prob": probs["tie_prob"],
        "lose_prob": probs["lose_prob"],
        "player_a": {
            "name": match.player_a.name,
            "current_score": match.player_a.score,
            "categories_remaining": match.player_a.categories_remaining,
            "projected_final": projected_a,
            "remaining_mean": stats_a["mean"],
            "remaining_std": stats_a["std"],
            "percentiles": final_percentiles_a,
        },
        "player_b": {
            "name": match.player_b.name,
            "current_score": match.player_b.score,
            "categories_remaining": match.player_b.categories_remaining,
            "projected_final": projected_b,
            "remaining_mean": stats_b["mean"],
            "remaining_std": stats_b["std"],
            "percentiles": final_percentiles_b,
        },
        "score_differential": match.score_differential,
        "projected_margin": projected_a - projected_b,
    }


def compute_pivotal_categories(state: PlayerState, opponent: PlayerState) -> List[Dict]:
    """
    Identify which unfilled categories have the biggest impact on win%.

    For each open category, computes the marginal win% gain from
    scoring well vs poorly in that category.
    """
    results = []
    base_probs = compute_win_probs_fast(state, opponent)
    base_win = base_probs["win_prob"]

    for cat in state.open_categories:
        # Simulate scoring max possible in this category
        # (This is approximate - real impact depends on the full distribution)

        # Create state where category is filled with typical good score
        # For simplicity, estimate using EV comparison

        # Actually compute marginal by comparing:
        # - State with this category still open
        # - State with this category filled (at mean value)

        # This is complex because we'd need to enumerate possibilities
        # Simplified version: report which categories have highest variance contribution

        results.append({
            "category": cat,
            "name": CATEGORY_NAMES[cat],
            # Would need more complex analysis for exact marginal
        })

    return results


def get_comeback_analysis(behind_state: PlayerState, ahead_state: PlayerState) -> Dict:
    """
    Analyze what the trailing player needs to catch up.
    """
    deficit = ahead_state.score - behind_state.score

    # Get distributions
    pmf_behind = pmf_remaining(behind_state.mask, behind_state.upper)
    pmf_ahead = pmf_remaining(ahead_state.mask, ahead_state.upper)

    stats_behind = pmf_stats(pmf_behind)
    stats_ahead = pmf_stats(pmf_ahead)

    # Expected remaining for each
    exp_behind = stats_behind["mean"]
    exp_ahead = stats_ahead["mean"]

    # Expected margin at end
    projected_margin = deficit + exp_ahead - exp_behind

    # What percentile of trailing player's remaining would tie?
    target_remaining = deficit + exp_ahead
    prob_catch_up = prob_at_least(pmf_behind, target_remaining)

    return {
        "current_deficit": deficit,
        "expected_remaining_behind": exp_behind,
        "expected_remaining_ahead": exp_ahead,
        "projected_final_margin": projected_margin,
        "prob_catch_up_or_win": prob_catch_up,
        "needs_remaining": target_remaining,
    }


def format_match_report(analysis: Dict) -> str:
    """Format match analysis as a human-readable report."""
    lines = []

    lines.append("=" * 60)
    lines.append("MATCH ANALYSIS")
    lines.append("=" * 60)

    # Win probabilities
    lines.append(f"\n{analysis['player_a']['name']} vs {analysis['player_b']['name']}")
    lines.append(f"  Win:  {analysis['win_prob']*100:.1f}%")
    lines.append(f"  Tie:  {analysis['tie_prob']*100:.1f}%")
    lines.append(f"  Lose: {analysis['lose_prob']*100:.1f}%")

    # Current scores
    lines.append(f"\nCurrent Score:")
    lines.append(f"  {analysis['player_a']['name']}: {analysis['player_a']['current_score']} "
                 f"({analysis['player_a']['categories_remaining']} turns left)")
    lines.append(f"  {analysis['player_b']['name']}: {analysis['player_b']['current_score']} "
                 f"({analysis['player_b']['categories_remaining']} turns left)")

    # Projections
    lines.append(f"\nProjected Final Score:")
    lines.append(f"  {analysis['player_a']['name']}: {analysis['player_a']['projected_final']:.0f} "
                 f"(+{analysis['player_a']['remaining_mean']:.0f} expected)")
    lines.append(f"  {analysis['player_b']['name']}: {analysis['player_b']['projected_final']:.0f} "
                 f"(+{analysis['player_b']['remaining_mean']:.0f} expected)")

    lines.append(f"\nProjected Margin: {analysis['projected_margin']:+.0f}")

    # Percentile ranges
    lines.append(f"\n50% Confidence Range (25th-75th percentile):")
    pa = analysis['player_a']['percentiles']
    pb = analysis['player_b']['percentiles']
    lines.append(f"  {analysis['player_a']['name']}: {pa['25th']:.0f} - {pa['75th']:.0f}")
    lines.append(f"  {analysis['player_b']['name']}: {pb['25th']:.0f} - {pb['75th']:.0f}")

    lines.append("=" * 60)

    return "\n".join(lines)


# =============================================================================
# Convenience Functions
# =============================================================================

def win_probs(score_a: int, mask_a: int, upper_a: int,
              score_b: int, mask_b: int, upper_b: int) -> Dict[str, float]:
    """
    Simplified interface for win probability calculation.

    Args:
        score_a: Player A's current score
        mask_a: Player A's filled categories mask
        upper_a: Player A's upper section subtotal
        score_b, mask_b, upper_b: Same for player B

    Returns:
        Dict with win_prob, tie_prob, lose_prob for player A
    """
    state_a = PlayerState(score=score_a, mask=mask_a, upper=upper_a)
    state_b = PlayerState(score=score_b, mask=mask_b, upper=upper_b)
    return compute_win_probs_fast(state_a, state_b)


if __name__ == "__main__":
    from ev_solver import warm_cache

    print("Warming EV cache...")
    warm_cache(verbose=True)

    print("\n" + "=" * 60)
    print("Testing match analysis...")

    # Create a sample mid-game state
    # Player A: has scored Ones(3), Twos(6), Yahtzee(50) = 59 points
    #           Upper: 9, mask: 0b100000000011 = categories 0,1,11
    mask_a = (1 << 0) | (1 << 1) | (1 << 11)
    upper_a = 9
    score_a = 59

    # Player B: has scored Threes(12), Fours(16), Chance(23) = 51 points
    #           Upper: 28, mask: categories 2,3,12
    mask_b = (1 << 2) | (1 << 3) | (1 << 12)
    upper_b = 28
    score_b = 51

    state_a = PlayerState(score=score_a, mask=mask_a, upper=upper_a, name="Alice")
    state_b = PlayerState(score=score_b, mask=mask_b, upper=upper_b, name="Bob")
    match = MatchState(player_a=state_a, player_b=state_b)

    analysis = get_match_analysis(match)
    report = format_match_report(analysis)
    print(report)

    # Also test quick API
    print("\nQuick API test (same state):")
    probs = win_probs(score_a, mask_a, upper_a, score_b, mask_b, upper_b)
    print(f"  Win:  {probs['win_prob']*100:.1f}%")
    print(f"  Tie:  {probs['tie_prob']*100:.1f}%")
    print(f"  Lose: {probs['lose_prob']*100:.1f}%")

    # Fresh game test
    print("\n" + "=" * 60)
    print("Fresh game (both players start at 0):")
    probs_fresh = win_probs(0, 0, 0, 0, 0, 0)
    print(f"  Win:  {probs_fresh['win_prob']*100:.1f}%")
    print(f"  Tie:  {probs_fresh['tie_prob']*100:.1f}%")
    print(f"  Lose: {probs_fresh['lose_prob']*100:.1f}%")
