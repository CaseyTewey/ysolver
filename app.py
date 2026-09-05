#!/usr/bin/env python3
"""
HTTP API and existing web UI for the 2-player Yahtzee solver.
Run with: python app.py
Then open: http://localhost:8080
"""

from flask import Flask, render_template, jsonify, request
import json
import math
import os
import re
import threading
from datetime import datetime
from functools import lru_cache
from werkzeug.exceptions import HTTPException
from api_state import InvalidState, integer, validate_dice, parse_scorecard
from game_storage import load_games, append_game
from mc_solver import simulate_match

# Game results file path
GAME_RESULTS_FILE = os.environ.get('GAME_RESULTS_FILE', os.path.join(os.path.dirname(__file__), 'game_results.json'))

# Import solver components
from ev_solver import (
    get_recommendation, ev_remaining, get_expected_score_fresh_game,
    get_recommendation_joker, ev_remaining_joker, get_expected_score_fresh_game_joker,
    get_all_category_evs_joker,
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
app.config['MAX_CONTENT_LENGTH'] = 1024 * 1024
MAX_CATS_FOR_EXACT = 4
SIMULATION_SAMPLES = 10_000
_exact_slot = threading.BoundedSemaphore(1)


class ExactCalculationBusy(Exception):
    """The shared per-worker probability computation slot is occupied."""

    def __init__(self, method='exact_pmf_joker'):
        self.method = method
        super().__init__('The solver is busy; retry shortly')


@app.errorhandler(ExactCalculationBusy)
def exact_calculation_busy(error):
    return jsonify(error=str(error), method=error.method,
                   feasible=error.method == 'exact_pmf_joker'), 503, {'Retry-After': '1'}


@lru_cache(maxsize=256)
def _cached_exact_probabilities(p1_locked, p1_mask, p1_upper, p1_status,
                                p2_locked, p2_mask, p2_upper, p2_status):
    """Reuse immutable match results for unchanged scorecards within a worker.

    The LRU checks for a completed result before acquiring the compute slot, so
    cached matches remain available while an unrelated match is calculating.
    Busy/failed calls raise and are never cached or replaced with an estimate.
    """
    if not _exact_slot.acquire(blocking=False):
        raise ExactCalculationBusy()
    try:
        return compute_win_probability_joker_exact(
            p1_locked, p1_mask, p1_upper, p1_status,
            p2_locked, p2_mask, p2_upper, p2_status)
    finally:
        _exact_slot.release()


@lru_cache(maxsize=256)
def _cached_simulation_probabilities(p1_locked, p1_mask, p1_upper, p1_status,
                                     p2_locked, p2_mask, p2_upper, p2_status):
    """Bound repeated work; cached results bypass the shared CPU admission gate.

    Results stay private to this module and are read into fresh response objects.
    A request cannot reduce the server's sample count or change its confidence.
    """
    if not _exact_slot.acquire(blocking=False):
        raise ExactCalculationBusy('monte_carlo')
    try:
        return simulate_match(p1_locked, p1_mask, p1_upper, p1_status,
                              p2_locked, p2_mask, p2_upper, p2_status,
                              sample_count=SIMULATION_SAMPLES)
    finally:
        _exact_slot.release()


def exact_probabilities(p1, p2):
    if p1.remaining == p2.remaining == 0:
        return ((1.0, 0.0, 0.0) if p1.current_total > p2.current_total else
                (0.0, 0.0, 1.0) if p1.current_total < p2.current_total else
                (0.0, 1.0, 0.0))
    return _cached_exact_probabilities(
        p1.locked, p1.mask, min(p1.upper, 63), p1.yahtzee_status,
        p2.locked, p2.mask, min(p2.upper, 63), p2.yahtzee_status)


def request_object():
    data = request.get_json()
    if not isinstance(data, dict):
        raise InvalidState('Request body must be a JSON object')
    try:
        json.dumps(data, allow_nan=False)
    except ValueError:
        raise InvalidState('JSON numbers must be finite')
    return data


@app.errorhandler(InvalidState)
def invalid_state(error):
    return jsonify(error=str(error)), 400


@app.errorhandler(HTTPException)
def http_error(error):
    if request.path.startswith('/api/'):
        return jsonify(error=error.description), error.code
    return error


@app.errorhandler(Exception)
def unexpected_error(error):
    app.logger.exception('Request failed')
    return jsonify(error='Internal server error'), 500


@app.route('/api/health')
def health():
    return jsonify(status='ok', mode='joker', objective='maximize_expected_score')


# High-variance categories (bimodal distributions)
HIGH_VARIANCE_CATEGORIES = {
    10,  # Large Straight (0 or 40)
    11,  # Yahtzee (0 or 50)
}
MEDIUM_VARIANCE_CATEGORIES = {
    8,   # Full House (0 or 25)
    9,   # Small Straight (0 or 30)
}


def detect_edge_cases(unfilled1, unfilled2, upper1, upper2, ev_diff, cats_remaining,
                      yahtzee_status1=0, yahtzee_status2=0):
    """
    Detect edge cases where normal approximation may be inaccurate.

    Returns:
        dict with 'has_edge_case', 'reasons', 'suggest_exact'
    """
    reasons = []

    if 0 < cats_remaining <= MAX_CATS_FOR_EXACT:
        reasons.append('Endgame scores have discrete outcomes; exact calculation is available')
    if ((unfilled1 and yahtzee_status1 == YAHTZEE_SCORED) or
            (unfilled2 and yahtzee_status2 == YAHTZEE_SCORED)):
        reasons.append('A future Yahtzee can add a 100-point bonus')

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
    suggest_exact = has_edge_case and cats_remaining <= MAX_CATS_FOR_EXACT

    return {
        'has_edge_case': has_edge_case,
        'reasons': reasons,
        'suggest_exact': suggest_exact,
        'exact_feasible': cats_remaining <= MAX_CATS_FOR_EXACT
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
    if current_upper_score < 63 <= current_upper_score + max_upper_remaining:
        # Could still get the bonus (35 points)
        max_remaining += 35

    # In joker mode, if yahtzee was scored (status=2), each remaining turn
    # could potentially roll another yahtzee for +100 bonus
    if is_joker_mode and yahtzee_status == YAHTZEE_SCORED:
        num_remaining_turns = len(unfilled_categories)
        # Theoretically could get a joker bonus on every remaining turn
        max_remaining += num_remaining_turns * YAHTZEE_BONUS
    elif is_joker_mode and yahtzee_status == YAHTZEE_UNFILLED and 11 in unfilled_categories:
        # Scoring the first Yahtzee can unlock +100 on every later turn.
        max_remaining += max(0, len(unfilled_categories) - 1) * YAHTZEE_BONUS

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
    if cats_remaining1 == cats_remaining2 == 0:
        return ((1.0, 0.0, 0.0) if score1 > score2 else
                (0.0, 0.0, 1.0) if score1 < score2 else (0.0, 1.0, 0.0))

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
    std1 = std_per_cat * math.sqrt(cats_remaining1)
    std2 = std_per_cat * math.sqrt(cats_remaining2)

    # Combined std deviation for the difference
    combined_std = math.sqrt(std1**2 + std2**2)

    if combined_std < 0.1:
        # Game essentially over, use deterministic comparison
        if expected1 > expected2:
            return 1.0, 0.0, 0.0
        elif expected1 < expected2:
            return 0.0, 0.0, 1.0
        else:
            return 0.0, 1.0, 0.0

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
    if p1_win < MIN_PROB:
        p1_win = MIN_PROB
        p2_win = 1.0 - MIN_PROB
    elif p2_win < MIN_PROB:
        p2_win = MIN_PROB
        p1_win = 1.0 - MIN_PROB

    # Ties are essentially impossible with continuous distribution
    p_tie = 0.0

    return p1_win, p_tie, p2_win

# Preload solver on startup (joker mode only)
print("Loading solver...")
_ = get_expected_score_fresh_game_joker()
print(f"Solver ready! Fresh game EV (Joker): {_:.2f}")

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
    data = request_object()
    dice = validate_dice(data.get('dice'))
    rolls_remaining = integer(data.get('rolls_remaining', 2), 'rolls_remaining', 0, 2)
    state = parse_scorecard(data)
    if state.remaining == 0:
        return jsonify(error='The scorecard is complete; there is no legal action'), 409
    mask, upper = state.mask, min(state.upper, 63)
    yahtzee_status, yahtzee_bonuses = state.yahtzee_status, state.yahtzee_bonuses

    # Always use joker mode
    rec = get_recommendation_joker(dice, mask, upper, rolls_remaining, yahtzee_status)
    rec['yahtzee_bonuses'] = yahtzee_bonuses

    # Format response (always joker mode)
    response = {
        'dice': dice,
        'rolls_remaining': rolls_remaining,
        'mask': mask,
        'upper': upper,
        'action': rec['action'],
        'expected_value': round(rec['expected_value'] - state.upper_bonus, 2),
        'mode': 'joker',
        'objective': 'maximize_expected_score',
        'yahtzee_status': yahtzee_status,
        'yahtzee_bonuses': yahtzee_bonuses,
        'is_yahtzee_roll': bool(rec.get('is_yahtzee_roll', False)),
        'joker_bonus_available': bool(rec.get('joker_bonus_available', False)),
    }

    # Add joker-specific fields
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
            'expected_value': float(opt['expected_value']) - state.upper_bonus,
            'is_forced': bool(opt.get('is_forced', False)),
        }
        for opt in rec['category_options']
    ]

    return jsonify(response)


@app.route('/api/score_options', methods=['POST'])
def score_options():
    """Get legal scoring options under the same Joker rules as recommendations."""
    data = request_object()
    dice = validate_dice(data.get('dice'))
    state = parse_scorecard(data)
    if state.remaining == 0:
        return jsonify(options=[], mode='joker', joker_bonus=0)

    counts = dice_list_to_counts(dice)
    rid = roll_id(counts)

    options = []
    for cat, pts, _, is_forced in get_all_category_evs_joker(
            rid, state.mask, min(state.upper, 63), state.yahtzee_status):
        options.append({
            'category': int(cat),
            'name': CATEGORY_NAMES[cat],
            'points': int(pts),
            'is_forced': bool(is_forced),
        })

    return jsonify(options=options, mode='joker',
                   joker_bonus=100 if is_yahtzee_roll(rid) and state.yahtzee_status == YAHTZEE_SCORED and state.remaining else 0)


@app.route('/api/game_ev', methods=['POST'])
def game_ev():
    """Get expected remaining value for a game state (always joker mode)."""
    state = parse_scorecard(request_object())
    mask, upper = state.mask, min(state.upper, 63)
    yahtzee_status = state.yahtzee_status

    # Always use joker mode
    ev = ev_remaining_joker(mask, upper, yahtzee_status) - state.upper_bonus

    response = {
        'ev_remaining': round(ev, 2),
        'mask': mask,
        'upper': upper,
        'categories_filled': 13 - state.remaining,
        'categories_remaining': state.remaining,
        'current_score': state.current_total,
        'expected_final': round(state.current_total + ev, 2),
        'mode': 'joker',
        'yahtzee_status': yahtzee_status,
    }

    return jsonify(response)


@app.route('/api/modes', methods=['GET'])
def get_available_modes():
    """Return list of available game modes (only joker mode now)."""
    return jsonify({
        'modes': [
            {
                'id': 'joker',
                'name': 'Joker Mode',
                'description': 'With Yahtzee bonus chips (+100 for each additional Yahtzee)'
            },
        ],
        'default': 'joker'
    })


def probability_response(p1, p2, *, require_exact=False):
    """Select the supported calculation and keep a consistent response shape."""
    remaining = max(p1.remaining, p2.remaining)
    feasible = remaining <= MAX_CATS_FOR_EXACT
    if require_exact and not feasible:
        return jsonify(error=f'Too many categories remaining for exact calculation. Max: {MAX_CATS_FOR_EXACT}',
                       feasible=False, max_categories=MAX_CATS_FOR_EXACT), 400

    ev1 = ev_remaining_joker(p1.mask, min(p1.upper, 63), p1.yahtzee_status) - p1.upper_bonus
    ev2 = ev_remaining_joker(p2.mask, min(p2.upper, 63), p2.yahtzee_status) - p2.upper_bonus
    simulation = None
    if feasible:
        win1, tie, win2 = exact_probabilities(p1, p2)
        method = 'deterministic' if remaining == 0 else 'exact_pmf_joker'
        metadata = dict(has_edge_case=False, reasons=[], suggest_exact=False, warning=None)
        intervals = [[round(probability * 100, 2)] * 2 for probability in (win1, tie, win2)]
        displays = [f'{round(probability * 100, 2):g}%' for probability in (win1, tie, win2)]
    else:
        result = _cached_simulation_probabilities(
            p1.locked, p1.mask, min(p1.upper, 63), p1.yahtzee_status,
            p2.locked, p2.mask, min(p2.upper, 63), p2.yahtzee_status)
        win1, tie, win2 = result['probabilities']
        method = 'monte_carlo'
        # Round outward so UI formatting never narrows the calculated interval.
        intervals = [[max(0, math.floor(low * 10_000) / 100),
                      min(100, math.ceil(high * 10_000) / 100)]
                     for low, high in result['intervals']]

        def sampled_display(count):
            percent = 100 * count / result['sample_count']
            if percent < 0.1:
                return '<0.1%'
            if percent > 99.9:
                return '>99.9%'
            return f'~{round(percent, 1):g}%'

        displays = [sampled_display(count) for count in result['counts']]
        outcome_keys = ('player1', 'tie', 'player2')
        simulation = dict(
            sample_count=result['sample_count'], confidence_level=result['confidence_level'],
            target_margin_percentage_points=1.0,
            max_margin_percentage_points=result['max_margin_percentage_points'],
            intervals=dict(zip(outcome_keys, intervals)),
            counts=dict(zip(outcome_keys, result['counts'])))
        metadata = dict(has_edge_case=False, reasons=[], suggest_exact=False,
                        warning=('95% intervals describe sampling uncertainty for each outcome under '
                                 'score-optimal play, not a guarantee of perfect match strategy. '
                                 'Exact odds are used automatically when each player has four or fewer categories left.'))
    metadata.update(method=method, is_approximate=not feasible, exact_feasible=feasible,
                    max_categories_for_exact=MAX_CATS_FOR_EXACT, distribution_basis='start_of_turn')

    def player_result(state, ev, win, index):
        return dict(current_score=state.current_total, ev_remaining=round(ev, 2),
                    expected_final=round(state.current_total + ev, 2),
                    categories_remaining=state.remaining, win_probability=round(win * 100, 2),
                    win_probability_display=displays[index], win_probability_interval=intervals[index],
                    yahtzee_status=state.yahtzee_status, yahtzee_bonuses=state.yahtzee_bonuses,
                    bonus_points=state.yahtzee_bonuses * YAHTZEE_BONUS)

    return jsonify(player1=player_result(p1, ev1, win1, 0), player2=player_result(p2, ev2, win2, 2),
                   tie_probability=round(tie * 100, 2), tie_probability_display=displays[1],
                   tie_probability_interval=intervals[1], simulation=simulation,
                   mode='joker', approximation=metadata,
                   method=method, is_exact=feasible, feasible=feasible,
                   objective='maximize_expected_score', distribution_basis='start_of_turn')


@app.route('/api/win_probability', methods=['POST'])
def win_probability():
    """Automatically use exact endgame odds; clearly mark early-game estimates."""
    data = request_object()
    return probability_response(parse_scorecard(data, 'player1_'), parse_scorecard(data, 'player2_'))


@app.route('/api/win_probability_exact', methods=['POST'])
def win_probability_exact():
    """Explicit exact-only compatibility endpoint, using the shared result cache."""
    data = request_object()
    return probability_response(parse_scorecard(data, 'player1_'), parse_scorecard(data, 'player2_'),
                                require_exact=True)


def load_game_results():
    return load_games(GAME_RESULTS_FILE)


@app.route('/api/save_game', methods=['POST'])
def save_game():
    """Validate a completed game and atomically append an authoritative summary."""
    data = request_object()
    p1 = parse_scorecard(data, 'player1_')
    p2 = parse_scorecard(data, 'player2_')
    if p1.remaining or p2.remaining:
        raise InvalidState('Both scorecards must be complete before saving a game')
    turns = data.get('turns', [])
    if not isinstance(turns, list) or len(turns) > 26 or any(not isinstance(turn, dict) for turn in turns):
        raise InvalidState('turns must be a list of at most 26 turn objects')
    if not isinstance(data.get('stats', {}), dict):
        raise InvalidState('stats must be an object')
    if not isinstance(data.get('timestamp', ''), str) or len(data.get('timestamp', '')) > 100:
        raise InvalidState('timestamp must be a string of at most 100 characters')
    saved = dict(data, player1_score=p1.current_total, player2_score=p2.current_total,
                 winner=1 if p1.current_total > p2.current_total else 2 if p2.current_total > p1.current_total else 0,
                 mode='joker', player1_yahtzee_status=p1.yahtzee_status, player2_yahtzee_status=p2.yahtzee_status,
                 player1_yahtzee_bonuses=p1.yahtzee_bonuses, player2_yahtzee_bonuses=p2.yahtzee_bonuses)
    try:
        game_id, total_games = append_game(GAME_RESULTS_FILE, saved)
    except (OSError, ValueError):
        app.logger.exception('Unable to save game history')
        return jsonify(error='Unable to save game history'), 500
    return jsonify(success=True, game_id=game_id, total_games=total_games)


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


@app.route('/api/article', methods=['GET'])
def get_article():
    """Serve the 'You Are Playing Yahtzee Wrong' article as HTML."""
    article_path = os.path.join(os.path.dirname(__file__), 'you-are-probably-playing-yahtzee-wrong.md')

    try:
        with open(article_path, 'r') as f:
            markdown_content = f.read()

        # Simple markdown to HTML conversion
        html = markdown_to_html(markdown_content)
        return jsonify({'html': html})
    except FileNotFoundError:
        return jsonify({'error': 'Article not found'}), 404


def markdown_to_html(md):
    """Convert markdown to HTML (simple implementation)."""
    lines = md.split('\n')
    html_lines = []
    in_table = False
    in_code_block = False
    in_list = False
    list_type = None

    i = 0
    while i < len(lines):
        line = lines[i]

        # Code blocks
        if line.strip().startswith('```'):
            if in_code_block:
                html_lines.append('</code></pre>')
                in_code_block = False
            else:
                html_lines.append('<pre><code>')
                in_code_block = True
            i += 1
            continue

        if in_code_block:
            html_lines.append(escape_html(line))
            i += 1
            continue

        # Close list if needed
        if in_list and not line.strip().startswith(('-', '*')) and not re.match(r'^\d+\.', line.strip()):
            html_lines.append(f'</{list_type}>')
            in_list = False

        # Tables
        if '|' in line and not in_table:
            # Check if next line is separator
            if i + 1 < len(lines) and re.match(r'^[\s|:-]+$', lines[i + 1]):
                in_table = True
                html_lines.append('<table>')
                # Header row
                cells = [c.strip() for c in line.split('|')[1:-1]]
                html_lines.append('<tr>' + ''.join(f'<th>{process_inline(c)}</th>' for c in cells) + '</tr>')
                i += 2  # Skip separator line
                continue

        if in_table:
            if '|' not in line or line.strip() == '':
                html_lines.append('</table>')
                in_table = False
            else:
                cells = [c.strip() for c in line.split('|')[1:-1]]
                html_lines.append('<tr>' + ''.join(f'<td>{process_inline(c)}</td>' for c in cells) + '</tr>')
                i += 1
                continue

        # Headers
        if line.startswith('# '):
            html_lines.append(f'<h1>{process_inline(line[2:])}</h1>')
        elif line.startswith('## '):
            html_lines.append(f'<h2>{process_inline(line[3:])}</h2>')
        elif line.startswith('### '):
            html_lines.append(f'<h3>{process_inline(line[4:])}</h3>')
        elif line.startswith('#### '):
            html_lines.append(f'<h4>{process_inline(line[5:])}</h4>')
        # Horizontal rule
        elif line.strip() in ['---', '***', '___']:
            html_lines.append('<hr>')
        # Unordered list
        elif line.strip().startswith(('-', '*')) and len(line.strip()) > 1 and line.strip()[1] == ' ':
            if not in_list or list_type != 'ul':
                if in_list:
                    html_lines.append(f'</{list_type}>')
                html_lines.append('<ul>')
                in_list = True
                list_type = 'ul'
            content = line.strip()[2:]
            html_lines.append(f'<li>{process_inline(content)}</li>')
        # Ordered list
        elif re.match(r'^\d+\.', line.strip()):
            if not in_list or list_type != 'ol':
                if in_list:
                    html_lines.append(f'</{list_type}>')
                html_lines.append('<ol>')
                in_list = True
                list_type = 'ol'
            content = re.sub(r'^\d+\.\s*', '', line.strip())
            html_lines.append(f'<li>{process_inline(content)}</li>')
        # Blockquote
        elif line.startswith('>'):
            html_lines.append(f'<blockquote>{process_inline(line[1:].strip())}</blockquote>')
        # Paragraph
        elif line.strip():
            html_lines.append(f'<p>{process_inline(line)}</p>')

        i += 1

    # Close any open elements
    if in_list:
        html_lines.append(f'</{list_type}>')
    if in_table:
        html_lines.append('</table>')
    if in_code_block:
        html_lines.append('</code></pre>')

    return '\n'.join(html_lines)


def process_inline(text):
    """Process inline markdown elements."""
    # Escape HTML first
    text = escape_html(text)

    # Bold
    text = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', text)

    # Italic
    text = re.sub(r'\*([^*]+)\*', r'<em>\1</em>', text)

    # Inline code
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)

    # Links
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2" target="_blank">\1</a>', text)

    return text


def escape_html(text):
    """Escape HTML special characters."""
    return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


if __name__ == '__main__':
    print("\n" + "=" * 50)
    print("YAHTZEE SOLVER WEB UI")
    print("=" * 50)
    print("Open http://localhost:8080 in your browser")
    print("=" * 50 + "\n")
    app.run(debug=os.environ.get('FLASK_DEBUG') == '1', host='127.0.0.1', port=8080)
