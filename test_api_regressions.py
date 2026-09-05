"""HTTP boundary, complete-game accounting, and persistence regressions."""

from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
import json

import pytest

import app as backend
from game_storage import append_game, load_games


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(backend, 'GAME_RESULTS_FILE', str(tmp_path / 'games.json'))
    backend.app.config.update(TESTING=True)
    return backend.app.test_client()


def closed(upper_bonus=False, yahtzee=False):
    scores = {str(i): 0 for i in range(13)}
    if upper_bonus:
        scores.update({str(i): (i + 1) * 3 for i in range(6)})
    if yahtzee:
        scores['11'] = 50
    return scores


@pytest.mark.parametrize('path', ['recommend', 'score_options', 'game_ev', 'win_probability', 'win_probability_exact', 'save_game'])
@pytest.mark.parametrize('body', [None, [], 4, 'invalid'])
def test_non_object_body_is_json_400(client, path, body):
    response = client.post('/api/' + path, data=json.dumps(body), content_type='application/json')
    assert response.status_code == 400
    assert response.is_json and response.json['error']


def test_http_errors_are_json(client):
    assert client.post('/api/game_ev', data='{', content_type='application/json').status_code == 400
    assert client.post('/api/game_ev', data='{}').status_code == 415
    response = client.post('/api/game_ev', data=' ' * (1024 * 1024 + 1), content_type='application/json')
    assert response.status_code == 413 and response.is_json
    response = client.post('/api/game_ev', data='{"scores":{"0":NaN}}', content_type='application/json')
    assert response.status_code == 400 and response.is_json
    assert client.get('/api/health').json['status'] == 'ok'


@pytest.mark.parametrize('dice', [None, [], [1] * 4, [1] * 6, [0, 2, 3, 4, 5], [7, 2, 3, 4, 5],
                                  [True, 2, 3, 4, 5], [1.0, 2, 3, 4, 5], ['1', 2, 3, 4, 5], '12345'])
@pytest.mark.parametrize('path', ['recommend', 'score_options'])
def test_bad_dice_rejected(client, dice, path):
    assert client.post('/api/' + path, json={'dice': dice}).status_code == 400


@pytest.mark.parametrize('rolls', [-1, 3, True, 1.0, '1', None])
def test_bad_roll_count_rejected(client, rolls):
    assert client.post('/api/recommend', json={'dice': [1, 2, 3, 4, 5], 'rolls_remaining': rolls}).status_code == 400


@pytest.mark.parametrize('scores', [[], None, {'13': 0}, {'-1': 0}, {'01': 0}, {'undefined': 0},
                                    {'0': -1}, {'0': True}, {'0': 1.0}, {'0': '1'},
                                    {'1': 3}, {'8': 10}, {'11': 25}, {'12': 31}, {'6': 2}])
@pytest.mark.parametrize('path,prefix', [('recommend', ''), ('score_options', ''), ('game_ev', ''),
                                       ('win_probability', 'player1_'), ('win_probability_exact', 'player2_')])
def test_invalid_scorecards_rejected(client, scores, path, prefix):
    response = client.post('/api/' + path, json={'dice': [1, 2, 3, 4, 5], prefix + 'scores': scores})
    assert response.status_code == 400
    assert response.json['error']


@pytest.mark.parametrize('extra', [{'yahtzee_status': 2}, {'yahtzee_status': -1}, {'yahtzee_status': True},
                                   {'yahtzee_bonuses': 1}, {'yahtzee_bonuses': -1}, {'yahtzee_bonuses': 1.5},
                                   {'scores': {'11': 0}, 'yahtzee_status': 2},
                                   {'scores': {'11': 50}, 'yahtzee_bonuses': 1}])
def test_inconsistent_joker_state_rejected(client, extra):
    assert client.post('/api/game_ev', json=extra).status_code == 400


def test_derived_status_null_category_and_terminal_recommendation(client):
    r = client.post('/api/game_ev', json={'scores': {'11': 50, '0': None}})
    assert r.status_code == 200 and r.json['yahtzee_status'] == 2
    assert r.json['categories_remaining'] == 12
    r = client.post('/api/recommend', json={'scores': closed(), 'dice': [1, 2, 3, 4, 5]})
    assert r.status_code == 409
    r = client.post('/api/score_options', json={'scores': closed(), 'dice': [1, 2, 3, 4, 5]})
    assert r.status_code == 200 and r.json['options'] == []


def test_upper_bonus_is_not_remaining_once_earned(client):
    scores = closed(upper_bonus=True)
    result = client.post('/api/game_ev', json={'scores': scores}).json
    assert result['current_score'] == result['expected_final'] == 98
    assert result['ev_remaining'] == 0
    del scores['12']
    result = client.post('/api/recommend', json={'scores': scores, 'dice': [6] * 5, 'rolls_remaining': 0}).json
    assert result['category'] == 12 and result['points'] == result['expected_value'] == 30
    assert result['category_options'][0]['expected_value'] == 30


@pytest.mark.parametrize('path', ['win_probability', 'win_probability_exact'])
def test_completed_tie_is_deterministic(client, path):
    result = client.post('/api/' + path, json={'player1_scores': closed(True), 'player2_scores': closed(True)}).json
    assert result['tie_probability'] == 100
    assert result['player1']['win_probability'] == result['player2']['win_probability'] == 0


@pytest.mark.parametrize('path', ['win_probability', 'win_probability_exact'])
def test_upper_bonus_counted_once_across_players(client, path):
    p1 = closed(True)  # 98 final points
    p2 = closed()
    p2.update({'10': 40, '11': 50, '12': 10})  # 100 final points, no upper bonus
    result = client.post('/api/' + path, json={'player1_scores': p1, 'player2_scores': p2}).json
    assert result['player1']['current_score'] == 98
    assert result['player2']['current_score'] == 100
    assert result['player2']['win_probability'] == 100 and result['tie_probability'] == 0


@pytest.mark.parametrize('path', ['win_probability', 'win_probability_exact'])
def test_earned_yahtzee_bonus_changes_winner(client, path):
    p1 = closed(yahtzee=True)
    p2 = closed(True)
    result = client.post('/api/' + path, json={'player1_scores': p1, 'player2_scores': p2,
                                             'player1_yahtzee_bonuses': 1}).json
    assert result['player1']['current_score'] == 150
    assert result['player1']['win_probability'] == 100


def test_future_yahtzee_bonus_prevents_false_elimination():
    assert backend.compute_max_remaining({11, 12}, 0, True, 0) == 180
    assert backend.compute_max_remaining({12}, 63, True, 1) == 30
    probabilities = backend.compute_win_probability(0, 60, 2, 100, 0, 0,
                       unfilled1={11, 12}, unfilled2=set(), is_joker_mode=True)
    assert probabilities[0] > 0


def test_rare_bonus_tail_automatically_uses_exact_odds(client):
    p1 = closed(yahtzee=True)
    del p1['12']
    p2 = closed(upper_bonus=True, yahtzee=True)
    p2['12'] = 27
    payload = {'player1_scores': p1, 'player2_scores': p2}
    automatic = client.post('/api/win_probability', json=payload).json
    exact = client.post('/api/win_probability_exact', json=payload).json
    assert automatic['is_exact'] and automatic['method'] == 'exact_pmf_joker'
    assert not automatic['approximation']['suggest_exact']
    assert automatic['player1']['win_probability'] == exact['player1']['win_probability']
    assert automatic['tie_probability'] == exact['tie_probability']
    assert exact['player1']['win_probability'] > .9
    assert exact['tie_probability'] > .8


@pytest.mark.parametrize('status,bonus', [(0, 0), (50, 100)])
def test_joker_score_options_agree_with_recommendation(client, status, bonus):
    # A repeat Yahtzee with matching upper filled must choose lower categories,
    # even if the original Yahtzee was scratched.
    payload = {'scores': {'0': 5, '11': status}, 'dice': [1] * 5, 'rolls_remaining': 0}
    options = client.post('/api/score_options', json=payload).json
    recommendation = client.post('/api/recommend', json=payload).json
    assert {x['category'] for x in options['options']} == {6, 7, 8, 9, 10, 12}
    assert next(x for x in options['options'] if x['category'] == 10)['points'] == 40
    assert options['joker_bonus'] == bonus
    assert {x['category']: x['points'] for x in options['options']} == {
        x['category']: x['points'] for x in recommendation['category_options']}


def test_exact_bound_is_consistent_and_busy_request_is_bounded(client):
    scores = closed()
    for cat in range(5):
        del scores[str(cat)]
    state = {'player1_scores': scores, 'player2_scores': scores}
    approx = client.post('/api/win_probability', json=state).json
    assert not approx['approximation']['exact_feasible']
    assert client.post('/api/win_probability_exact', json=state).status_code == 400
    backend._cached_exact_probabilities.cache_clear()
    one_open = closed()
    del one_open['12']
    with backend._exact_slot:
        response = client.post('/api/win_probability_exact', json={'player1_scores': one_open, 'player2_scores': closed()})
    assert response.status_code == 503 and response.headers['Retry-After'] == '1'


def test_save_roundtrip_uses_authoritative_totals(client):
    payload = {'player1_scores': closed(True), 'player2_scores': closed(),
               'player1_score': -100, 'winner': 2, 'game_id': 77, 'turns': []}
    saved = client.post('/api/save_game', json=payload)
    assert saved.status_code == 200 and saved.json['game_id'] == 1
    history = client.get('/api/game_history').json
    assert history[0]['player1_score'] == 98 and history[0]['winner'] == 1
    detail = client.get('/api/game_details/1').json
    assert detail['player1_score'] == 98 and detail['game_id'] == 1
    assert client.get('/api/game_details/2').status_code == 404
    assert client.post('/api/save_game', json={}).status_code == 400


def test_concurrent_game_saves_preserve_every_record(client):
    def save_one(_):
        with backend.app.test_client() as parallel_client:
            response = parallel_client.post('/api/save_game', json={'player1_scores': closed(), 'player2_scores': closed()})
            assert response.status_code == 200
            return response.json['game_id']
    with ThreadPoolExecutor(max_workers=8) as pool:
        ids = list(pool.map(save_one, range(24)))
    assert len(set(ids)) == len(client.get('/api/game_history').json) == 24


def test_process_saves_are_atomic(tmp_path):
    path = str(tmp_path / 'games.json')
    with ProcessPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(append_game, path, {'tag': i}) for i in range(9)]
        results = [future.result(timeout=30) for future in futures]
    assert len({row[0] for row in results}) == 9
    assert {row['tag'] for row in load_games(path)} == set(range(9))


def test_corrupt_history_is_not_silently_overwritten(client):
    from pathlib import Path
    path = Path(backend.GAME_RESULTS_FILE)
    path.write_text('{broken')
    response = client.post('/api/save_game', json={'player1_scores': closed(), 'player2_scores': closed()})
    assert response.status_code == 500 and response.is_json
    assert path.read_text() == '{broken'
