#!/usr/bin/env python3
"""
Web UI for 2-player Yahtzee solver.
Run with: python web_app.py
Then open: http://localhost:5000
"""

from flask import Flask, render_template, jsonify, request
import json
import math
import os
from datetime import datetime

# Game results file path
GAME_RESULTS_FILE = os.path.join(os.path.dirname(__file__), 'game_results.json')

# Import solver components
from ev_solver import (
    get_recommendation, ev_remaining, get_expected_score_fresh_game,
    get_recommendation_joker, ev_remaining_joker, get_expected_score_fresh_game_joker,
    YAHTZEE_UNFILLED, YAHTZEE_SCRATCHED, YAHTZEE_SCORED, YAHTZEE_BONUS
)
from dice import dice_list_to_counts, roll_id
from scoring import (
    CATEGORY_NAMES, get_score_table, NUM_CATEGORIES,
    is_yahtzee_roll, get_forced_category_joker
)
from match import compute_win_probs, PlayerState
from pmf_solver import clear_pmf_cache
from pmf_solver_joker import (
    compute_win_probability_exact as compute_win_probability_joker_exact,
    clear_pmf_joker_cache
)

app = Flask(__name__)


# High-variance categories (bimodal distributions)
HIGH_VARIANCE_CATEGORIES = {
    10,  # Large Straight (0 or 40)
    11,  # Yahtzee (0 or 50)
}
MEDIUM_VARIANCE_CATEGORIES = {
    8,   # Full House (0 or 25)
    9,   # Small Straight (0 or 30)
}


def detect_edge_cases(unfilled1, unfilled2, upper1, upper2, ev_diff, cats_remaining):
    """
    Detect edge cases where normal approximation may be inaccurate.

    Returns:
        dict with 'has_edge_case', 'reasons', 'suggest_exact'
    """
    reasons = []

    # Check for high-variance categories
    p1_high_var = unfilled1 & HIGH_VARIANCE_CATEGORIES
    p2_high_var = unfilled2 & HIGH_VARIANCE_CATEGORIES

    if p1_high_var or p2_high_var:
        cats = []
        if 11 in p1_high_var or 11 in p2_high_var:
            cats.append("Yahtzee")
        if 10 in p1_high_var or 10 in p2_high_var:
            cats.append("Large Straight")
        reasons.append(f"High-variance categories remaining: {', '.join(cats)}")

    # Check for upper bonus cliff
    # Player could swing 35 points based on upper section outcome
    p1_upper_remaining = sum(1 for c in unfilled1 if c < 6)
    p2_upper_remaining = sum(1 for c in unfilled2 if c < 6)

    p1_max_upper_gain = sum((c + 1) * 5 for c in unfilled1 if c < 6)  # Max possible upper points
    p2_max_upper_gain = sum((c + 1) * 5 for c in unfilled2 if c < 6)

    # Near bonus threshold with upper categories remaining
    if p1_upper_remaining > 0 and 45 <= upper1 < 63 and upper1 + p1_max_upper_gain >= 63:
        reasons.append(f"P1 upper bonus uncertain ({upper1}/63, {p1_upper_remaining} upper cats left)")
    if p2_upper_remaining > 0 and 45 <= upper2 < 63 and upper2 + p2_max_upper_gain >= 63:
        reasons.append(f"P2 upper bonus uncertain ({upper2}/63, {p2_upper_remaining} upper cats left)")

    # Close game with variance remaining
    if abs(ev_diff) < 20 and cats_remaining >= 3:
        reasons.append(f"Close game (EV diff: {ev_diff:.1f}) with {cats_remaining} categories left")

    # Asymmetric remaining categories
    p1_var_count = len(unfilled1 & (HIGH_VARIANCE_CATEGORIES | MEDIUM_VARIANCE_CATEGORIES))
    p2_var_count = len(unfilled2 & (HIGH_VARIANCE_CATEGORIES | MEDIUM_VARIANCE_CATEGORIES))
    if abs(p1_var_count - p2_var_count) >= 2:
        reasons.append(f"Asymmetric variance (P1: {p1_var_count}, P2: {p2_var_count} high-variance cats)")

    has_edge_case = len(reasons) > 0
    # Only suggest exact if it's feasible (≤5 categories each)
    suggest_exact = has_edge_case and cats_remaining <= 5

    return {
        'has_edge_case': has_edge_case,
        'reasons': reasons,
        'suggest_exact': suggest_exact,
        'exact_feasible': cats_remaining <= 5
    }


def normal_cdf(x):
    """Standard normal CDF approximation."""
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


# Maximum possible score for each category
MAX_CATEGORY_SCORES = {
    0: 5,    # Ones (5x1)
    1: 10,   # Twos (5x2)
    2: 15,   # Threes (5x3)
    3: 20,   # Fours (5x4)
    4: 25,   # Fives (5x5)
    5: 30,   # Sixes (5x6)
    6: 30,   # Three of a Kind (5x6)
    7: 30,   # Four of a Kind (5x6)
    8: 25,   # Full House
    9: 30,   # Small Straight
    10: 40,  # Large Straight
    11: 50,  # Yahtzee
    12: 30,  # Chance (5x6)
}


def compute_max_remaining(unfilled_categories, current_upper_score,
                          is_joker_mode=False, yahtzee_status=0):
    """
    Compute the maximum possible remaining score.

    Args:
        unfilled_categories: set of unfilled category indices (0-12)
        current_upper_score: current upper section subtotal
        is_joker_mode: whether joker rules are in effect
        yahtzee_status: 0=unfilled, 1=scratched, 2=scored 50

    Returns:
        Maximum possible points from remaining categories + potential bonuses
    """
    max_remaining = 0
    max_upper_remaining = 0

    for cat in unfilled_categories:
        max_remaining += MAX_CATEGORY_SCORES[cat]
        if cat < 6:  # Upper section
            max_upper_remaining += MAX_CATEGORY_SCORES[cat]

    # Check if upper bonus is still achievable
    if current_upper_score + max_upper_remaining >= 63:
        # Could still get the bonus (35 points)
        max_remaining += 35

    # In joker mode, if yahtzee was scored (status=2), each remaining turn
    # could potentially roll another yahtzee for +100 bonus
    if is_joker_mode and yahtzee_status == YAHTZEE_SCORED:
        num_remaining_turns = len(unfilled_categories)
        # Theoretically could get a joker bonus on every remaining turn
        max_remaining += num_remaining_turns * YAHTZEE_BONUS

    return max_remaining


def compute_win_probability(score1, ev1, cats_remaining1, score2, ev2, cats_remaining2,
                            unfilled1=None, unfilled2=None, upper1=0, upper2=0,
                            is_joker_mode=False, yahtzee_status1=0, yahtzee_status2=0):
    """
    Compute approximate win probability using normal distribution model.

    The key insight: Yahtzee scores have variance that depends on categories remaining.
    We model the final score as Normal(current + ev_remaining, sigma).
    Sigma decreases as more categories are filled (less uncertainty).

    Only returns 0.0% if player is mathematically eliminated (max possible < opponent's current).
    """
    # Check for mathematical elimination first
    if unfilled1 is not None and unfilled2 is not None:
        max1 = score1 + compute_max_remaining(unfilled1, upper1, is_joker_mode, yahtzee_status1)
        max2 = score2 + compute_max_remaining(unfilled2, upper2, is_joker_mode, yahtzee_status2)

        # Player 1 eliminated: even max possible can't beat opponent's current
        if max1 < score2:
            return 0.0, 0.0, 1.0

        # Player 2 eliminated
        if max2 < score1:
            return 1.0, 0.0, 0.0

    # Expected final scores
    expected1 = score1 + ev1
    expected2 = score2 + ev2

    # Standard deviation per remaining category (empirically ~6-8 points)
    std_per_cat = 7.0

    # Total std deviation (decreases as game progresses)
    # Using sqrt because variances add, not std devs
    std1 = std_per_cat * math.sqrt(max(cats_remaining1, 0.1))
    std2 = std_per_cat * math.sqrt(max(cats_remaining2, 0.1))

    # Combined std deviation for the difference
    combined_std = math.sqrt(std1**2 + std2**2)

    if combined_std < 0.1:
        # Game essentially over, use deterministic comparison
        if expected1 > expected2:
            return 1.0, 0.0, 0.0
        elif expected1 < expected2:
            return 0.0, 0.0, 1.0
        else:
            return 0.5, 0.0, 0.5

    # P(Player1 wins) = P(Score1 > Score2) = P(Score1 - Score2 > 0)
    # Score1 - Score2 ~ Normal(expected1 - expected2, combined_std)
    diff = expected1 - expected2

    # P(X > 0) where X ~ Normal(diff, combined_std)
    # = P(Z > -diff/std) where Z ~ Normal(0,1)
    # = 1 - P(Z < -diff/std)
    # = 1 - Phi(-diff/std)
    z = diff / combined_std
    p1_win = normal_cdf(z)
    p2_win = 1.0 - p1_win

    # Ensure we don't show 0.0% unless truly eliminated (handled above)
    # Use a minimum probability floor for display
    MIN_PROB = 0.001  # 0.1%
    if p1_win < MIN_PROB and p1_win > 0:
        p1_win = MIN_PROB
        p2_win = 1.0 - MIN_PROB
    elif p2_win < MIN_PROB and p2_win > 0:
        p2_win = MIN_PROB
        p1_win = 1.0 - MIN_PROB

    # Ties are essentially impossible with continuous distribution
    p_tie = 0.0

    return p1_win, p_tie, p2_win

# Preload solver on startup
print("Loading solver...")
_ = get_expected_score_fresh_game()
print(f"Solver ready! Fresh game EV: {_:.2f}")

SCORE_TABLE = get_score_table()


def compute_mask(filled_categories):
    """Convert list of filled category indices to bitmask."""
    mask = 0
    for cat in filled_categories:
        mask |= (1 << cat)
    return mask


def compute_upper_total(scores):
    """Compute upper section total from scores dict."""
    total = 0
    for cat in range(6):  # Categories 0-5 are upper section
        if scores.get(str(cat)) is not None:
            total += scores[str(cat)]
    return min(total, 63)  # Cap at 63


@app.route('/')
def index():
    return render_template('index.html', categories=CATEGORY_NAMES)


@app.route('/api/recommend', methods=['POST'])
def recommend():
    """Get recommendation for current game state."""
    data = request.json

    dice = data.get('dice', [1, 1, 1, 1, 1])
    rolls_remaining = data.get('rolls_remaining', 2)
    player_scores = data.get('scores', {})

    # NEW: Joker mode parameters
    mode = data.get('mode', 'traditional')
    yahtzee_status = data.get('yahtzee_status', YAHTZEE_UNFILLED)
    yahtzee_bonuses = data.get('yahtzee_bonuses', 0)

    # Compute mask and upper from scores - filter out invalid keys
    filled = []
    for k, v in player_scores.items():
        if v is not None and k not in ('undefined', 'null', ''):
            try:
                filled.append(int(k))
            except ValueError:
                pass  # Skip invalid keys
    mask = compute_mask(filled)
    upper = compute_upper_total(player_scores)

    # Get recommendation based on mode
    if mode == 'joker':
        rec = get_recommendation_joker(dice, mask, upper, rolls_remaining, yahtzee_status)
        rec['yahtzee_bonuses'] = yahtzee_bonuses
    else:
        rec = get_recommendation(dice, mask, upper, rolls_remaining)
        rec['mode'] = 'traditional'

    # Format response
    response = {
        'dice': dice,
        'rolls_remaining': rolls_remaining,
        'mask': mask,
        'upper': upper,
        'action': rec['action'],
        'expected_value': round(rec['expected_value'], 2),
        'mode': rec.get('mode', 'traditional'),
    }

    # Add joker-specific fields
    if mode == 'joker':
        response['yahtzee_status'] = yahtzee_status
        response['yahtzee_bonuses'] = yahtzee_bonuses
        response['is_yahtzee_roll'] = bool(rec.get('is_yahtzee_roll', False))
        response['joker_bonus_available'] = bool(rec.get('joker_bonus_available', False))
        if rec.get('forced_category') is not None:
            response['forced_category'] = rec['forced_category']
            response['forced_category_name'] = rec.get('forced_category_name')
        if rec.get('joker_bonus'):
            response['joker_bonus'] = rec['joker_bonus']

    if rec['action'] == 'keep':
        # Calculate which dice to reroll (remove kept dice from original roll)
        keep_list = list(rec['keep_dice'])
        reroll = []
        for d in dice:
            if d in keep_list:
                keep_list.remove(d)
            else:
                reroll.append(d)
        response['keep_dice'] = rec['keep_dice']
        response['reroll'] = reroll
    else:
        response['category'] = rec['category']
        response['category_name'] = rec['category_name']
        response['points'] = rec['points']

    # Add all category options (convert numpy types to Python types for JSON)
    response['category_options'] = [
        {
            'category': int(opt['category']),
            'name': opt['name'],
            'points': int(opt['points']),
            'expected_value': float(opt['expected_value']),
            'is_forced': bool(opt.get('is_forced', False)),
        }
        for opt in rec['category_options'][:8]  # Top 8
    ]

    return jsonify(response)


@app.route('/api/score_options', methods=['POST'])
def score_options():
    """Get scoring options for current dice."""
    data = request.json
    dice = data.get('dice', [1, 1, 1, 1, 1])

    counts = dice_list_to_counts(dice)
    rid = roll_id(counts)

    options = []
    for cat in range(NUM_CATEGORIES):
        pts = SCORE_TABLE[rid][cat]
        options.append({
            'category': cat,
            'name': CATEGORY_NAMES[cat],
            'points': pts
        })

    return jsonify({'options': options})


@app.route('/api/game_ev', methods=['POST'])
def game_ev():
    """Get expected remaining value for a game state."""
    data = request.json
    player_scores = data.get('scores', {})
    mode = data.get('mode', 'traditional')
    yahtzee_status = data.get('yahtzee_status', YAHTZEE_UNFILLED)

    filled = [int(k) for k, v in player_scores.items() if v is not None]
    mask = compute_mask(filled)
    upper = compute_upper_total(player_scores)

    if mode == 'joker':
        ev = ev_remaining_joker(mask, upper, yahtzee_status)
    else:
        ev = ev_remaining(mask, upper)

    response = {
        'ev_remaining': round(ev, 2),
        'mask': mask,
        'upper': upper,
        'categories_filled': len(filled),
        'categories_remaining': 13 - len(filled),
        'mode': mode,
    }

    if mode == 'joker':
        response['yahtzee_status'] = yahtzee_status

    return jsonify(response)


@app.route('/api/modes', methods=['GET'])
def get_available_modes():
    """Return list of available game modes."""
    return jsonify({
        'modes': [
            {
                'id': 'traditional',
                'name': 'Traditional',
                'description': 'Standard Yahtzee rules without joker bonus'
            },
            {
                'id': 'joker',
                'name': 'Joker Mode',
                'description': 'With Yahtzee bonus chips (+100 for each additional Yahtzee)'
            },
        ],
        'default': 'traditional'
    })


@app.route('/api/win_probability', methods=['POST'])
def win_probability():
    """Compute win probability for both players based on current game state."""
    data = request.json

    p1_scores = data.get('player1_scores', {})
    p2_scores = data.get('player2_scores', {})

    # Joker mode support
    mode = data.get('mode', 'traditional')
    p1_yahtzee_status = data.get('player1_yahtzee_status', YAHTZEE_UNFILLED)
    p2_yahtzee_status = data.get('player2_yahtzee_status', YAHTZEE_UNFILLED)
    p1_yahtzee_bonuses = data.get('player1_yahtzee_bonuses', 0)
    p2_yahtzee_bonuses = data.get('player2_yahtzee_bonuses', 0)

    # Compute current totals
    def get_current_total(scores):
        total = 0
        upper = 0
        for cat, pts in scores.items():
            if pts is not None:
                total += pts
                if int(cat) < 6:
                    upper += pts
        # Add bonus if earned
        if upper >= 63:
            total += 35
        return total, upper

    p1_total, p1_upper = get_current_total(p1_scores)
    p2_total, p2_upper = get_current_total(p2_scores)

    # Compute EV remaining for each player
    p1_filled = [int(k) for k, v in p1_scores.items() if v is not None]
    p2_filled = [int(k) for k, v in p2_scores.items() if v is not None]

    p1_mask = compute_mask(p1_filled)
    p2_mask = compute_mask(p2_filled)

    # Clamp upper for bonus calculation
    p1_upper_clamped = min(p1_upper, 63)
    p2_upper_clamped = min(p2_upper, 63)

    if mode == 'joker':
        p1_ev = ev_remaining_joker(p1_mask, p1_upper_clamped, p1_yahtzee_status)
        p2_ev = ev_remaining_joker(p2_mask, p2_upper_clamped, p2_yahtzee_status)
    else:
        p1_ev = ev_remaining(p1_mask, p1_upper_clamped)
        p2_ev = ev_remaining(p2_mask, p2_upper_clamped)

    # Categories remaining
    p1_remaining = 13 - len(p1_filled)
    p2_remaining = 13 - len(p2_filled)

    # Unfilled categories (for elimination check)
    all_cats = set(range(13))
    p1_unfilled = all_cats - set(p1_filled)
    p2_unfilled = all_cats - set(p2_filled)

    # Compute win probability with elimination check
    is_joker = (mode == 'joker')
    p1_win, tie, p2_win = compute_win_probability(
        p1_total, p1_ev, p1_remaining,
        p2_total, p2_ev, p2_remaining,
        unfilled1=p1_unfilled, unfilled2=p2_unfilled,
        upper1=p1_upper, upper2=p2_upper,
        is_joker_mode=is_joker,
        yahtzee_status1=p1_yahtzee_status,
        yahtzee_status2=p2_yahtzee_status
    )

    # Detect edge cases
    ev_diff = (p1_total + p1_ev) - (p2_total + p2_ev)
    max_remaining = max(p1_remaining, p2_remaining)
    edge_case_info = detect_edge_cases(
        p1_unfilled, p2_unfilled,
        p1_upper, p2_upper,
        ev_diff, max_remaining
    )

    response = {
        'player1': {
            'current_score': p1_total,
            'ev_remaining': round(p1_ev, 2),
            'expected_final': round(p1_total + p1_ev, 2),
            'categories_remaining': p1_remaining,
            'win_probability': round(p1_win * 100, 1)
        },
        'player2': {
            'current_score': p2_total,
            'ev_remaining': round(p2_ev, 2),
            'expected_final': round(p2_total + p2_ev, 2),
            'categories_remaining': p2_remaining,
            'win_probability': round(p2_win * 100, 1)
        },
        'tie_probability': round(tie * 100, 1),
        'mode': mode,
        'approximation': {
            'method': 'normal',
            'has_edge_case': edge_case_info['has_edge_case'],
            'reasons': edge_case_info['reasons'],
            'suggest_exact': edge_case_info['suggest_exact'],
            'exact_feasible': edge_case_info['exact_feasible']
        }
    }

    # Add joker-specific info
    if mode == 'joker':
        response['player1']['yahtzee_status'] = p1_yahtzee_status
        response['player1']['yahtzee_bonuses'] = p1_yahtzee_bonuses
        response['player1']['bonus_points'] = p1_yahtzee_bonuses * YAHTZEE_BONUS
        response['player2']['yahtzee_status'] = p2_yahtzee_status
        response['player2']['yahtzee_bonuses'] = p2_yahtzee_bonuses
        response['player2']['bonus_points'] = p2_yahtzee_bonuses * YAHTZEE_BONUS

        # Adjust totals to include joker bonuses
        response['player1']['current_score'] += p1_yahtzee_bonuses * YAHTZEE_BONUS
        response['player1']['expected_final'] += p1_yahtzee_bonuses * YAHTZEE_BONUS
        response['player2']['current_score'] += p2_yahtzee_bonuses * YAHTZEE_BONUS
        response['player2']['expected_final'] += p2_yahtzee_bonuses * YAHTZEE_BONUS

    return jsonify(response)


@app.route('/api/win_probability_exact', methods=['POST'])
def win_probability_exact():
    """
    Compute EXACT win probability using PMF convolution.

    WARNING: This is slow! Only use when ≤5 categories remaining per player.
    Returns error if too many categories remaining.

    Uses joker PMF solver for joker mode (models yahtzee_status and joker bonuses).
    Uses traditional PMF solver for traditional mode.
    """
    data = request.json

    p1_scores = data.get('player1_scores', {})
    p2_scores = data.get('player2_scores', {})

    # Joker mode parameters
    mode = data.get('mode', 'traditional')
    p1_yahtzee_bonuses = data.get('player1_yahtzee_bonuses', 0)
    p2_yahtzee_bonuses = data.get('player2_yahtzee_bonuses', 0)
    p1_yahtzee_status = data.get('player1_yahtzee_status', YAHTZEE_UNFILLED)
    p2_yahtzee_status = data.get('player2_yahtzee_status', YAHTZEE_UNFILLED)

    # Compute current totals and state
    def get_state(scores):
        total = 0
        upper = 0
        filled = []
        for cat, pts in scores.items():
            if pts is not None:
                total += pts
                filled.append(int(cat))
                if int(cat) < 6:
                    upper += pts
        # Add bonus if earned
        if upper >= 63:
            total += 35
        mask = sum(1 << c for c in filled)
        return total, upper, mask, filled

    p1_total, p1_upper, p1_mask, p1_filled = get_state(p1_scores)
    p2_total, p2_upper, p2_mask, p2_filled = get_state(p2_scores)

    # Add joker bonuses to current totals (already earned bonuses)
    if mode == 'joker':
        p1_total += p1_yahtzee_bonuses * YAHTZEE_BONUS
        p2_total += p2_yahtzee_bonuses * YAHTZEE_BONUS

    p1_remaining = 13 - len(p1_filled)
    p2_remaining = 13 - len(p2_filled)

    # Check if computation is feasible (2-3 cats: ~10s, 4 cats: ~30s)
    MAX_CATS_FOR_EXACT = 4
    if p1_remaining > MAX_CATS_FOR_EXACT or p2_remaining > MAX_CATS_FOR_EXACT:
        return jsonify({
            'error': f'Too many categories remaining for exact calculation. Max: {MAX_CATS_FOR_EXACT}, P1: {p1_remaining}, P2: {p2_remaining}',
            'feasible': False
        }), 400

    try:
        if mode == 'joker':
            # Use joker PMF solver (models yahtzee_status and future joker bonuses)
            clear_pmf_joker_cache()
            p1_win, tie_prob, p2_win = compute_win_probability_joker_exact(
                p1_locked=p1_total, p1_mask=p1_mask, p1_upper=min(p1_upper, 63), p1_yahtzee_status=p1_yahtzee_status,
                p2_locked=p2_total, p2_mask=p2_mask, p2_upper=min(p2_upper, 63), p2_yahtzee_status=p2_yahtzee_status
            )
            method = 'exact_pmf_joker'
        else:
            # Use traditional PMF solver
            clear_pmf_cache()
            state1 = PlayerState(score=p1_total, mask=p1_mask, upper=min(p1_upper, 63))
            state2 = PlayerState(score=p2_total, mask=p2_mask, upper=min(p2_upper, 63))
            result = compute_win_probs(state1, state2)
            p1_win = result['win_prob']
            tie_prob = result['tie_prob']
            p2_win = result['lose_prob']
            method = 'exact_pmf_traditional'

        return jsonify({
            'player1': {
                'current_score': p1_total,
                'categories_remaining': p1_remaining,
                'win_probability': round(p1_win * 100, 2)
            },
            'player2': {
                'current_score': p2_total,
                'categories_remaining': p2_remaining,
                'win_probability': round(p2_win * 100, 2)
            },
            'tie_probability': round(tie_prob * 100, 2),
            'method': method,
            'feasible': True
        })
    except Exception as e:
        return jsonify({
            'error': f'PMF computation failed: {str(e)}',
            'feasible': False
        }), 500


def load_game_results():
    """Load game results from file."""
    if os.path.exists(GAME_RESULTS_FILE):
        try:
            with open(GAME_RESULTS_FILE, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return []
    return []


def save_game_results(results):
    """Save game results to file."""
    with open(GAME_RESULTS_FILE, 'w') as f:
        json.dump(results, f, indent=2)


@app.route('/api/save_game', methods=['POST'])
def save_game():
    """Save a completed game to the results file."""
    data = request.json

    # Load existing results
    results = load_game_results()

    # Add game ID
    data['game_id'] = len(results) + 1

    # Append new game
    results.append(data)

    # Save back to file
    save_game_results(results)

    return jsonify({
        'success': True,
        'game_id': data['game_id'],
        'total_games': len(results)
    })


@app.route('/api/game_history', methods=['GET'])
def game_history():
    """Get all saved game results."""
    results = load_game_results()

    # Return summary of each game for listing
    summaries = []
    for game in results:
        summaries.append({
            'game_id': game.get('game_id'),
            'timestamp': game.get('timestamp'),
            'player1_score': game.get('player1_score'),
            'player2_score': game.get('player2_score'),
            'winner': game.get('winner'),
            'total_turns': len(game.get('turns', [])),
            'stats': game.get('stats', {})
        })

    return jsonify(summaries)


@app.route('/api/game_details/<int:game_id>', methods=['GET'])
def game_details(game_id):
    """Get detailed results for a specific game."""
    results = load_game_results()

    for game in results:
        if game.get('game_id') == game_id:
            return jsonify(game)

    return jsonify({'error': 'Game not found'}), 404


if __name__ == '__main__':
    print("\n" + "=" * 50)
    print("YAHTZEE SOLVER WEB UI")
    print("=" * 50)
    print("Open http://localhost:8080 in your browser")
    print("=" * 50 + "\n")
    app.run(debug=True, host='127.0.0.1', port=8080)
