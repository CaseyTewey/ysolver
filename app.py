#!/usr/bin/env python3
"""
Web UI and JSON API for the two player Yahtzee solver.

Run with: python app.py        (PORT env var, default 8080; FLASK_DEBUG=1 for debug mode)
Then open: http://localhost:8080

All policy questions are answered by engine.Solver (official Hasbro rules by default) and
exact end-game distributions come from distribution.py. Every POST endpoint takes a JSON
object and answers 400 {"error": ...} on anything it cannot validate; the API never returns
HTML, not even for 404, 405 or 500.

Accounting convention used throughout: the engine's remaining EV already contains the
eventual 35 point upper bonus. Whenever a displayed current score includes an earned 35,
the displayed ev_remaining has that 35 removed so the two still sum to the expected final.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from contextlib import contextmanager
from functools import lru_cache
from typing import Any, Dict, List, Optional

from flask import Flask, jsonify, render_template, request
from werkzeug.exceptions import HTTPException

from dice import dice_list_to_counts, roll_id
from distribution import (
    MAX_OPEN_FOR_EXACT, TooManyBoxesOpen, normal_win_probabilities, pmf_remaining,
    pmf_stats, win_probabilities,
)
from engine import (
    FULL_MASK, HASBRO, NUM_CATS, YAHTZEE_SCORED, YAHTZEE_SCRATCHED, YAHTZEE_UNFILLED, ScoreState,
    Solver, max_remaining, parse_dice, parse_rolls_remaining, parse_scorecard,
)

try:
    import fcntl
except ImportError:          # not POSIX
    fcntl = None
from scoring import CATEGORY_NAMES

GAME_RESULTS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'game_results.json')
ARTICLE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            'you-are-probably-playing-yahtzee-wrong.md')
MAX_SAVE_BYTES = 256 * 1024
MAX_SAVE_DEPTH = 12           # a saved game nests turns > rolls > recommendation > options; 12 is generous
MAX_YAHTZEE_BONUSES = 12      # the box takes one turn; at most 12 further Yahtzees can be rolled
MIN_DISPLAY_PROB = 0.001      # a live (not eliminated) player never shows 0.0%
MAX_SIM_GAMES = 2000          # /api/simulate cap: about a second of work

# Error of the normal approximation used by /api/win_probability when the exact distributions are
# not computed, in win-probability percentage points, keyed by the larger of the two players' open-box
# counts: (usual = 90th percentile of the absolute error, worst seen). Measured on 324 matchups against
# exact distributions and 200,000-game simulations; see README "How sure is it".
APPROX_ERROR_PTS = {
    13: (5, 8), 12: (5, 8), 11: (5, 8), 10: (5, 8), 9: (5, 8), 8: (5, 8),
    7: (7, 10), 6: (7, 10), 5: (7, 10), 4: (10, 23), 3: (10, 23), 2: (10, 18), 1: (10, 18), 0: (0, 0),
}

app = Flask(__name__)

# ------------------------------------------------------------------------------------------
# Solver (built once at import; auto-builds the table if the LFS file is a pointer or missing)
# ------------------------------------------------------------------------------------------
print("Loading solver...", flush=True)
SOLVER = Solver(HASBRO)
RULES = SOLVER.rules
MODE = 'joker' if RULES.joker != 'none' else 'traditional'
print(f"Solver ready. Rules: {RULES.key}. Fresh game EV: {SOLVER.fresh_ev:.4f} "
      f"(std {SOLVER.std(0, 0, 0):.4f})", flush=True)


# ------------------------------------------------------------------------------------------
# Request parsing helpers (everything the engine indexes with is validated here or in engine)
# ------------------------------------------------------------------------------------------
def json_body() -> Dict[str, Any]:
    """The request body as a dict; ValueError (400) when missing or not a JSON object."""
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise ValueError("request body must be a JSON object")
    return body


def _as_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        if isinstance(value, float) and value.is_integer():
            return int(value)
        raise ValueError(f"{name} must be an integer")
    return int(value)


def int_field(body: Dict[str, Any], key: str, default: int, lo: int, hi: int) -> int:
    """Optional integer field clamped to a closed range; None counts as absent."""
    value = body.get(key)
    if value is None:
        return default
    value = _as_int(value, key)
    if not lo <= value <= hi:
        raise ValueError(f"{key} must be between {lo} and {hi}")
    return value


def check_yahtzee_status(value: Any) -> Optional[int]:
    """Validate a client supplied yahtzee_status. The scorecard remains the source of truth."""
    if value is None:
        return None
    value = _as_int(value, "yahtzee_status")
    if value not in (YAHTZEE_UNFILLED, YAHTZEE_SCRATCHED, YAHTZEE_SCORED):
        raise ValueError("yahtzee_status must be 0 (unfilled), 1 (scratched) or 2 (scored 50)")
    return value


def scorecard_state(body: Dict[str, Any], scores_key: str = 'scores',
                    status_key: str = 'yahtzee_status') -> ScoreState:
    """Derive mask, upper and yahtzee_status from the scorecard. A client status is only validated."""
    state = parse_scorecard(body.get(scores_key))
    check_yahtzee_status(body.get(status_key))
    return state


def bonuses_field(body: Dict[str, Any], key: str, state: ScoreState) -> int:
    """Yahtzee bonus chips, checked against the scorecard: chips need a 50 in the Yahtzee box and
    at most one can be earned per box filled after it."""
    bonuses = int_field(body, key, 0, 0, MAX_YAHTZEE_BONUSES)
    if bonuses:
        if state.yahtzee_status != YAHTZEE_SCORED:
            raise ValueError(f"{key}: Yahtzee bonus chips need a Yahtzee box holding 50")
        if bonuses > len(state.filled) - 1:
            raise ValueError(f"{key}: at most one bonus chip per box filled after the Yahtzee box")
    return bonuses


def multiset_difference(dice: List[int], keep: List[int]) -> List[int]:
    """The dice that are rerolled: the roll minus the kept dice, as multisets."""
    remaining = list(keep)
    reroll = []
    for d in dice:
        if d in remaining:
            remaining.remove(d)
        else:
            reroll.append(d)
    return reroll


def category_option_json(opt: Dict[str, Any]) -> Dict[str, Any]:
    return {
        'category': int(opt['category']),
        'name': opt['name'],
        'points': int(opt['points']),
        'bonus': int(opt.get('bonus', 0)),
        'expected_value': float(opt['expected_value']),
        'is_forced': bool(opt.get('is_forced', False)),
    }


# ------------------------------------------------------------------------------------------
# JSON error handling
# ------------------------------------------------------------------------------------------
@app.errorhandler(ValueError)
def handle_value_error(err: ValueError):
    """Bad input (ours or the engine's validation) is a 400 with the message."""
    return jsonify({'error': str(err)}), 400


@app.errorhandler(400)
@app.errorhandler(404)
@app.errorhandler(405)
@app.errorhandler(500)
@app.errorhandler(HTTPException)
def handle_http_error(err: HTTPException):
    code = err.code or 500
    if code >= 500:
        app.logger.error("internal error: %s", getattr(err, 'original_exception', err))
        message = 'internal server error'
    else:
        message = err.description or err.name
    return jsonify({'error': message, 'status': code}), code


# ------------------------------------------------------------------------------------------
# Win probability helpers
# ------------------------------------------------------------------------------------------
class PlayerView:
    """One player's state plus the numbers the win probability endpoints report."""

    def __init__(self, state: ScoreState, yahtzee_bonuses: int):
        self.state = state
        self.yahtzee_bonuses = yahtzee_bonuses
        self.bonus_points = yahtzee_bonuses * RULES.yahtzee_bonus
        self.ev = SOLVER.ev(state.mask, state.upper, state.yb)          # includes the eventual 35
        self.std = SOLVER.std(state.mask, state.upper, state.yb)
        # banked points without the 35 (the PMFs and EV carry it)
        self.locked = state.locked + self.bonus_points
        # what the scorecard shows right now
        self.current_score = self.locked + state.upper_bonus_earned
        self.ev_remaining = self.ev - state.upper_bonus_earned
        self.expected_final = self.locked + self.ev
        self.max_final = self.locked + max_remaining(RULES, state.mask, state.upper, state.yb)

    @property
    def boxes_remaining(self) -> int:
        return self.state.boxes_remaining


def player_from_body(body: Dict[str, Any], prefix: str) -> PlayerView:
    if f'{prefix}_scores' not in body:
        raise ValueError(f"{prefix}_scores is required (send {{}} for a fresh scorecard)")
    state = scorecard_state(body, f'{prefix}_scores', f'{prefix}_yahtzee_status')
    bonuses = bonuses_field(body, f'{prefix}_yahtzee_bonuses', state)
    return PlayerView(state, bonuses)


def win_confidence(exact: bool, max_open: int, exact_feasible: bool, tie: float = 0.0) -> dict:
    """How much to trust a displayed win probability."""
    if exact:
        headline = 'Exact' + (f', tie {tie * 100:.1f}%' if tie >= 0.0005 else '')
        return {'label': 'exact', 'headline': headline,
                'note': 'Computed from the exact score distributions of both players under optimal play.'}
    typical, worst = APPROX_ERROR_PTS.get(max_open, (5, 8))
    note = ('Normal approximation from each player\'s exact expected score and standard deviation; ties are ignored. '
            + ('The exact calculation is available for this position.' if exact_feasible else
               f'The exact calculation becomes available once both players are down to {MAX_OPEN_FOR_EXACT} open boxes.'))
    return {'label': 'approximate', 'headline': f'Approximate, usually within {typical} points',
            'typical_error_pts': typical, 'worst_error_pts': worst, 'note': note}


def approximation_block(max_open: int, exact_feasible: bool, exact_used: bool) -> dict:
    """The approximation summary the UI reads; the warning appears only when exact is available but unused."""
    if exact_used:
        return {'method': 'exact_pmf', 'has_edge_case': False, 'reasons': [], 'suggest_exact': False,
                'exact_feasible': True, 'exact_used': True, 'max_open_for_exact': MAX_OPEN_FOR_EXACT}
    typical, worst = APPROX_ERROR_PTS.get(max_open, (5, 8))
    reason = (f"Normal approximation: at this stage of the game it is usually within {typical} points "
              f"of the exact figure (worst measured {worst}).")
    if exact_feasible:
        reason += " The exact calculation is available for this position."
    return {'method': 'normal_exact_moments', 'has_edge_case': exact_feasible, 'reasons': [reason],
            'suggest_exact': exact_feasible, 'exact_feasible': exact_feasible, 'exact_used': False,
            'max_open_for_exact': MAX_OPEN_FOR_EXACT}


def exact_is_cheap(p: "PlayerView") -> bool:
    """The exact distribution takes well under a second unless several upper boxes are still open."""
    open_upper = sum(1 for c in p.state.open_boxes if c < 6)
    return p.boxes_remaining <= 4 or (p.boxes_remaining <= 5 and open_upper <= 3)


@lru_cache(maxsize=64)
def pmf_for_state(mask: int, upper: int, yb: int):
    """Exact PMF of the remaining score (bonus included) for an end-game state."""
    return pmf_remaining(SOLVER, mask, upper, yb, max_open=MAX_OPEN_FOR_EXACT)


# ------------------------------------------------------------------------------------------
# Routes
# ------------------------------------------------------------------------------------------
@app.after_request
def api_answers_json(response):
    """Flask's automatic OPTIONS reply is text/html with an empty body; keep /api/* JSON-typed."""
    if request.path.startswith('/api/') and response.mimetype == 'text/html':
        response.mimetype = 'application/json'
    return response


@app.route('/')
def index():
    return render_template('index.html', categories=CATEGORY_NAMES)


@app.route('/api/recommend', methods=['POST'])
def recommend():
    """Optimal keep or box for the current roll and scorecard."""
    body = json_body()
    dice = parse_dice(body.get('dice'))
    rolls_remaining = parse_rolls_remaining(body.get('rolls_remaining', 2))
    state = scorecard_state(body)
    yahtzee_bonuses = bonuses_field(body, 'yahtzee_bonuses', state)

    rec = SOLVER.recommend(dice, state.mask, state.upper, state.yahtzee_status, rolls_remaining)

    response = {
        'dice': dice,
        'rolls_remaining': rolls_remaining,
        'mask': state.mask,
        'upper': state.upper,
        'upper_raw': state.upper_raw,
        'action': rec['action'],
        'expected_value': float(rec['expected_value']),   # unrounded: the UI compares it with category_options
        'std': round(SOLVER.std(state.mask, state.upper, state.yb), 2),
        'mode': rec['mode'],
        'rules': rec['rules'],
        'yahtzee_status': state.yahtzee_status,
        'yahtzee_bonuses': yahtzee_bonuses,
        'is_yahtzee_roll': bool(rec['is_yahtzee_roll']),
        'joker_bonus_available': bool(rec['joker_bonus_available']),
        'joker_rule': rec['joker_rule'],
        'forced_category': rec['forced_category'],
        'forced_category_name': rec['forced_category_name'],
        'category_options': [category_option_json(o) for o in rec['category_options']],
        'confidence': SOLVER.decision_report(state.mask, state.upper, state.yb,
                                             roll_id(dice_list_to_counts(dice)), rolls_remaining),
    }
    if rec.get('joker_bonus'):
        response['joker_bonus'] = int(rec['joker_bonus'])

    if rec['action'] == 'keep':
        keep_dice = [int(d) for d in rec['keep_dice']]
        response['keep_dice'] = keep_dice
        response['keep_all'] = bool(rec['keep_all'])
        response['reroll'] = multiset_difference(dice, keep_dice)
        response['keep_expected_value'] = float(rec['keep_expected_value'])
    else:
        response['category'] = int(rec['category'])
        response['category_name'] = rec['category_name']
        response['points'] = int(rec['points'])
    return jsonify(response)


@app.route('/api/score_options', methods=['POST'])
def score_options():
    """Points and legality of every box for these dice under the current state (Joker aware)."""
    body = json_body()
    dice = parse_dice(body.get('dice'))
    state = scorecard_state(body)
    if state.mask == FULL_MASK:
        raise ValueError("game is over: every box is filled")
    rid = roll_id(dice_list_to_counts(dice))

    legal, pts, bonus = SOLVER.options(state.mask, state.upper, state.yb, rid)
    situation = SOLVER.joker_situation(state.mask, state.yb, rid)
    options = [
        {
            'category': cat,
            'name': CATEGORY_NAMES[cat],
            'points': int(pts[cat]) if legal[cat] else 0,
            'legal': bool(legal[cat]),
            'is_forced': bool(legal[cat]) and situation == 'forced_upper',
        }
        for cat in range(NUM_CATS)
    ]
    return jsonify({
        'options': options,
        'joker_rule': situation,
        'joker_bonus': int(bonus),
        'is_yahtzee_roll': bool(SOLVER.t.is_yz[rid]),
        'yahtzee_status': state.yahtzee_status,
        'mode': MODE,
        'rules': RULES.key,
    })


@app.route('/api/game_ev', methods=['POST'])
def game_ev():
    """Expected remaining score (upper bonus included) and its exact standard deviation."""
    body = json_body()
    state = scorecard_state(body)
    return jsonify({
        'ev_remaining': round(SOLVER.ev(state.mask, state.upper, state.yb), 2),
        'std': round(SOLVER.std(state.mask, state.upper, state.yb), 2),
        'mask': state.mask,
        'upper': state.upper,
        'upper_raw': state.upper_raw,
        'upper_bonus_earned': state.upper_bonus_earned,
        'categories_filled': len(state.filled),
        'categories_remaining': state.boxes_remaining,
        'mode': MODE,
        'yahtzee_status': state.yahtzee_status,
        'rules': RULES.key,
        'fresh_ev': round(SOLVER.fresh_ev, 2),
    })


@app.route('/api/modes', methods=['GET'])
def get_available_modes():
    """The single rule set the server plays."""
    return jsonify({
        'modes': [
            {
                'id': MODE,
                'name': 'Joker Mode',
                'rules': RULES.key,
                'description': ('Official Hasbro rules with the Joker rule and a '
                                f'{RULES.yahtzee_bonus} point Yahtzee bonus'),
            },
        ],
        'default': MODE,
    })


@app.route('/api/win_probability', methods=['POST'])
def win_probability():
    """Win, tie and lose chances. Exact from the two score distributions whenever that is cheap
    (few boxes open), otherwise a normal approximation from each player's exact mean and std."""
    body = json_body()
    p1 = player_from_body(body, 'player1')
    p2 = player_from_body(body, 'player2')
    max_open = max(p1.boxes_remaining, p2.boxes_remaining)
    exact_feasible = (p1.boxes_remaining <= MAX_OPEN_FOR_EXACT
                      and p2.boxes_remaining <= MAX_OPEN_FOR_EXACT)
    exact_used = exact_feasible and exact_is_cheap(p1) and exact_is_cheap(p2)

    p1_eliminated = p1.max_final < p2.current_score
    p2_eliminated = p2.max_final < p1.current_score
    if exact_used:
        pmf1 = pmf_for_state(p1.state.mask, p1.state.upper, p1.state.yb)
        pmf2 = pmf_for_state(p2.state.mask, p2.state.upper, p2.state.yb)
        p1_win, tie, p2_win = win_probabilities(pmf1, p1.locked, pmf2, p2.locked)
        p1_eliminated = p1_eliminated or (p1_win == 0.0 and tie == 0.0)
        p2_eliminated = p2_eliminated or (p2_win == 0.0 and tie == 0.0)
    elif p1_eliminated and not p2_eliminated:
        p1_win, tie, p2_win = 0.0, 0.0, 1.0
    elif p2_eliminated and not p1_eliminated:
        p1_win, tie, p2_win = 1.0, 0.0, 0.0
    else:
        p1_win, tie, p2_win = normal_win_probabilities(p1.expected_final, p1.std,
                                                       p2.expected_final, p2.std)
        # never display 0.0% for a player who is still mathematically alive
        if tie == 0.0:
            if p1_win < MIN_DISPLAY_PROB and not p1_eliminated:
                p1_win, p2_win = MIN_DISPLAY_PROB, 1.0 - MIN_DISPLAY_PROB
            elif p2_win < MIN_DISPLAY_PROB and not p2_eliminated:
                p2_win, p1_win = MIN_DISPLAY_PROB, 1.0 - MIN_DISPLAY_PROB

    def block(p: PlayerView, win: float, eliminated: bool) -> dict:
        ev_shown = round(p.ev_remaining, 2)
        return {
            'current_score': int(p.current_score),
            'ev_remaining': ev_shown,
            'expected_final': round(p.current_score + ev_shown, 2),
            'std': round(p.std, 2),
            'categories_remaining': p.boxes_remaining,
            'win_probability': round(max(0.0, win) * 100, 1),
            'eliminated': bool(eliminated),
            'yahtzee_status': p.state.yahtzee_status,
            'yahtzee_bonuses': p.yahtzee_bonuses,
            'bonus_points': p.bonus_points,
            'upper_bonus_earned': p.state.upper_bonus_earned,
        }

    return jsonify({
        'player1': block(p1, p1_win, p1_eliminated),
        'player2': block(p2, p2_win, p2_eliminated),
        'tie_probability': round(tie * 100, 1),
        'method': 'exact_pmf' if exact_used else 'normal_exact_moments',
        'mode': MODE,
        'rules': RULES.key,
        'approximation': approximation_block(max_open, exact_feasible, exact_used),
        'confidence': win_confidence(exact_used, max_open, exact_feasible, tie),
    })


@app.route('/api/simulate', methods=['POST'])
def simulate():
    """Play the table policy from this scorecard with random dice and compare with the table EV."""
    body = json_body()
    state = scorecard_state(body)
    games = int_field(body, 'games', 500, 1, MAX_SIM_GAMES)
    seed = body.get('seed')
    if seed is not None:
        seed = int_field(body, 'seed', 0, 0, 2 ** 31 - 1)
    if state.mask == FULL_MASK:
        raise ValueError("game is over: every box is filled")
    result = SOLVER.simulate(state.mask, state.upper, state.yb, games=games, seed=seed)
    verdict = (f"{games:,} simulated games from this spot averaged {result['mean']:.1f} remaining points "
               f"(standard error {result['se']:.1f}); the table says {result['table_ev']:.2f}. "
               + ("Consistent." if result['consistent'] else
                  "Further from the table than 3 standard errors, which should happen about 0.3% of the time; run it again."))
    return jsonify({**result, 'verdict': verdict, 'mask': state.mask, 'upper': state.upper,
                    'yahtzee_status': state.yahtzee_status, 'categories_remaining': state.boxes_remaining,
                    'rules': RULES.key})


@app.route('/api/win_probability_exact', methods=['POST'])
def win_probability_exact():
    """Exact win, tie and loss probabilities from both players' end-game score distributions."""
    body = json_body()
    p1 = player_from_body(body, 'player1')
    p2 = player_from_body(body, 'player2')

    n1, n2 = p1.boxes_remaining, p2.boxes_remaining
    if n1 > MAX_OPEN_FOR_EXACT or n2 > MAX_OPEN_FOR_EXACT:
        return jsonify({
            'error': (f'Too many categories remaining for exact calculation. '
                      f'Max: {MAX_OPEN_FOR_EXACT}, P1: {n1}, P2: {n2}'),
            'feasible': False,
            'max_open_for_exact': MAX_OPEN_FOR_EXACT,
        }), 400

    try:
        pmf1 = pmf_for_state(p1.state.mask, p1.state.upper, p1.state.yb)
        pmf2 = pmf_for_state(p2.state.mask, p2.state.upper, p2.state.yb)
    except TooManyBoxesOpen as err:
        return jsonify({'error': str(err), 'feasible': False,
                        'max_open_for_exact': MAX_OPEN_FOR_EXACT}), 400

    p1_win, tie, p2_win = win_probabilities(pmf1, p1.locked, pmf2, p2.locked)

    def block(p: PlayerView, pmf, win: float) -> dict:
        stats = pmf_stats(pmf)
        return {
            'current_score': int(p.current_score),
            'categories_remaining': p.boxes_remaining,
            'win_probability': round(win * 100, 2),
            'mean': round(p.locked + stats['mean'], 2),
            'std': round(stats['std'], 2),
            'p10': int(p.locked + stats['p10']),
            'p50': int(p.locked + stats['p50']),
            'p90': int(p.locked + stats['p90']),
            'yahtzee_status': p.state.yahtzee_status,
            'yahtzee_bonuses': p.yahtzee_bonuses,
        }

    return jsonify({
        'player1': block(p1, pmf1, p1_win),
        'player2': block(p2, pmf2, p2_win),
        'tie_probability': round(tie * 100, 2),
        'method': 'exact_pmf',
        'feasible': True,
        'mode': MODE,
        'rules': RULES.key,
        'confidence': win_confidence(True, 0, True),
    })


# ------------------------------------------------------------------------------------------
# Game history (JSON file on disk)
# ------------------------------------------------------------------------------------------
class GameHistoryError(Exception):
    """The game history file exists but cannot be read as a list of game records."""


_HISTORY_LOCK = threading.Lock()


@app.errorhandler(GameHistoryError)
def handle_history_error(err: GameHistoryError):
    app.logger.error("%s", err)
    return jsonify({'error': str(err), 'status': 500}), 500


@contextmanager
def history_file_lock():
    """Cross-process lock on a sidecar file so two servers never interleave a read-modify-write."""
    if fcntl is None:
        yield
        return
    with open(GAME_RESULTS_FILE + '.lock', 'w') as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)


def json_depth(obj: Any, limit: int) -> int:
    """Nesting depth of a JSON value, iterative, stopping as soon as it exceeds limit."""
    depth = 0
    stack = [(obj, 1)]
    while stack:
        node, d = stack.pop()
        if d > depth:
            depth = d
            if depth > limit:
                return depth
        if isinstance(node, dict):
            stack.extend((v, d + 1) for v in node.values())
        elif isinstance(node, list):
            stack.extend((v, d + 1) for v in node)
    return depth


def validate_game_record(data: Any) -> Dict[str, Any]:
    """Shape check for a saved game: the fields game_history summarises must have the right types."""
    if not isinstance(data, dict):
        raise ValueError("game record must be a JSON object")
    if json_depth(data, MAX_SAVE_DEPTH) > MAX_SAVE_DEPTH:
        raise ValueError(f"game record nests deeper than {MAX_SAVE_DEPTH} levels")
    turns = data.get('turns')
    if turns is None:
        data['turns'] = []
    elif not isinstance(turns, list):
        raise ValueError("turns must be a list")
    stats = data.get('stats')
    if stats is not None and not isinstance(stats, dict):
        raise ValueError("stats must be an object")
    for key in ('player1_score', 'player2_score'):
        value = data.get(key)
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))):
            raise ValueError(f"{key} must be a number")
    timestamp = data.get('timestamp')
    if timestamp is not None and not isinstance(timestamp, str):
        raise ValueError("timestamp must be a string")
    winner = data.get('winner')          # the UI sends 1, 2 or 0 (tie); older clients sent a name
    if winner is not None and (isinstance(winner, bool) or not isinstance(winner, (int, str))):
        raise ValueError("winner must be a player number or name")
    return data


def load_game_results() -> list:
    """All saved games. A missing file is an empty history; an unreadable one is an error, never []."""
    if not os.path.exists(GAME_RESULTS_FILE):
        return []
    try:
        with open(GAME_RESULTS_FILE, 'r') as f:
            results = json.load(f)
    except (json.JSONDecodeError, OSError, RecursionError) as exc:
        raise GameHistoryError(f"game history file is unreadable, refusing to touch it: {exc}") from exc
    if not isinstance(results, list) or not all(isinstance(g, dict) for g in results):
        raise GameHistoryError("game history file does not contain a list of game records")
    return results


def save_game_results(results: list) -> None:
    """Write the history atomically: serialise in memory first, then replace the file in one step."""
    payload = json.dumps(results, indent=2)
    directory = os.path.dirname(GAME_RESULTS_FILE)
    fd, tmp_path = tempfile.mkstemp(prefix='.game_results.', suffix='.tmp', dir=directory)
    try:
        with os.fdopen(fd, 'w') as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, GAME_RESULTS_FILE)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


@app.route('/api/save_game', methods=['POST'])
def save_game():
    """Save a completed game to the results file."""
    if request.content_length is not None and request.content_length > MAX_SAVE_BYTES:
        raise ValueError(f"game record too large (limit {MAX_SAVE_BYTES // 1024} KB)")
    raw = request.get_data(cache=True)
    if len(raw) > MAX_SAVE_BYTES:
        raise ValueError(f"game record too large (limit {MAX_SAVE_BYTES // 1024} KB)")
    data = validate_game_record(json_body())

    with _HISTORY_LOCK, history_file_lock():
        results = load_game_results()
        used_ids = [g['game_id'] for g in results if isinstance(g.get('game_id'), int)]
        data['game_id'] = (max(used_ids) if used_ids else 0) + 1
        results.append(data)
        save_game_results(results)

    return jsonify({
        'success': True,
        'game_id': data['game_id'],
        'total_games': len(results),
    })


@app.route('/api/game_history', methods=['GET'])
def game_history():
    """Get all saved game results."""
    results = load_game_results()

    summaries = []
    for game in results:
        summaries.append({
            'game_id': game.get('game_id'),
            'timestamp': game.get('timestamp'),
            'player1_score': game.get('player1_score'),
            'player2_score': game.get('player2_score'),
            'winner': game.get('winner'),
            'total_turns': len(game['turns']) if isinstance(game.get('turns'), list) else 0,
            'stats': game.get('stats', {}),
        })

    return jsonify(summaries)


@app.route('/api/game_details/<int:game_id>', methods=['GET'])
def game_details(game_id: int):
    """Get detailed results for a specific game."""
    results = load_game_results()

    for game in results:
        if game.get('game_id') == game_id:
            return jsonify(game)

    return jsonify({'error': 'Game not found'}), 404


# ------------------------------------------------------------------------------------------
# Article
# ------------------------------------------------------------------------------------------
@app.route('/api/article', methods=['GET'])
def get_article():
    """Serve the 'You Are Playing Yahtzee Wrong' article as HTML."""
    try:
        with open(ARTICLE_FILE, 'r') as f:
            markdown_content = f.read()
        return jsonify({'html': markdown_to_html(markdown_content)})
    except FileNotFoundError:
        return jsonify({'error': 'Article not found'}), 404


def markdown_to_html(md: str) -> str:
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


def process_inline(text: str) -> str:
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


def escape_html(text: str) -> str:
    """Escape HTML special characters."""
    return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


if __name__ == '__main__':
    port_env = os.environ.get('PORT')
    port = int(port_env) if port_env else 8080
    host = '0.0.0.0' if port_env else '127.0.0.1'
    debug = os.environ.get('FLASK_DEBUG') == '1'
    print("\n" + "=" * 50)
    print("YAHTZEE SOLVER WEB UI")
    print("=" * 50)
    print(f"Open http://localhost:{port} in your browser")
    print("=" * 50 + "\n", flush=True)
    app.run(debug=debug, host=host, port=port)
