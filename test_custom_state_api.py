"""Validate manually entered games without solving or persisting anything."""

from copy import deepcopy
import json

import pytest

import app as backend
from api_state import parse_position


@pytest.fixture
def client(monkeypatch):
    backend.app.config.update(TESTING=True)

    def unexpected_work(*args, **kwargs):
        pytest.fail('Position validation must not solve or persist a game')

    for function in ('probability_response', 'simulate_match', 'ev_remaining_joker', 'append_game'):
        monkeypatch.setattr(backend, function, unexpected_work)
    return backend.app.test_client()


def post(client, **payload):
    return client.post('/api/validate_position', json=payload)


def test_blank_position_defaults(client):
    response = post(client)
    assert response.status_code == 200
    position = response.json['position']
    assert position['active_player'] == 1
    assert position['rolls_remaining'] == 2
    assert position['dice'] == [None] * 5
    assert position['current_turn'] == 1
    assert position['completed'] is False
    for player in ('player1', 'player2'):
        assert position[player + '_scores'] == {str(cat): None for cat in range(13)}
        assert position[player + '_yahtzee_status'] == position[player + '_yahtzee_bonuses'] == 0
        assert response.json[player] == {
            'current_total': 0, 'upper_total': 0, 'upper_bonus': 0,
            'filled_categories': 0, 'categories_remaining': 13,
        }


def test_screenshot_position_bonus_and_partial_dice(client):
    response = post(client,
        player1_scores={'0': 0, '1': 4, '2': 6, '3': 12, '4': 15, '5': 30,
                        '6': 21, '10': 40, '11': 50, '12': 12},
        player1_yahtzee_bonuses=1,
        player2_scores={'1': 8, '2': 9, '3': 12, '4': 15, '5': 24,
                        '8': 25, '9': 30, '10': 40, '11': 50},
        active_player=2, rolls_remaining=2, dice=[4, None, None, None, None])
    assert response.status_code == 200
    result = response.json
    position = result['position']
    assert position['current_turn'] == 20
    assert position['active_player'] == 2
    assert position['dice'] == [4, None, None, None, None]
    assert position['player1_yahtzee_status'] == position['player2_yahtzee_status'] == 2
    assert position['player1_yahtzee_bonuses'] == 1
    assert result['player1'] == {
        'current_total': 325, 'upper_total': 67, 'upper_bonus': 35,
        'filled_categories': 10, 'categories_remaining': 3,
    }
    assert result['player2'] == {
        'current_total': 248, 'upper_total': 68, 'upper_bonus': 35,
        'filled_categories': 9, 'categories_remaining': 4,
    }


def test_zero_is_used_and_blank_is_open_and_turn_override_is_ignored(client):
    result = post(client, player1_scores={'0': 0, '11': 0, '12': None}, current_turn=24).json
    assert result['position']['player1_scores']['0'] == 0
    assert result['position']['player1_scores']['12'] is None
    assert result['position']['player1_yahtzee_status'] == 1
    assert result['position']['current_turn'] == 3
    assert result['player1']['categories_remaining'] == 11


@pytest.mark.parametrize('dice', [[], [6], [None, 3], [1, None, 6, None, 2], [1, 2, 3, 4, 5]])
@pytest.mark.parametrize('rolls_remaining', [0, 1, 2])
def test_partial_or_complete_roll_can_be_entered_at_each_stage(client, dice, rolls_remaining):
    response = post(client, dice=dice, rolls_remaining=rolls_remaining)
    assert response.status_code == 200
    assert response.json['position']['dice'] == dice + [None] * (5 - len(dice))
    assert response.json['position']['rolls_remaining'] == rolls_remaining


def test_uneven_analysis_position_is_allowed(client):
    result = post(client, player1_scores={'0': 0, '1': 0, '2': 0, '3': 0}, active_player=1)
    assert result.status_code == 200
    assert result.json['position']['current_turn'] == 5


@pytest.mark.parametrize('active_player', [1, 2])
def test_both_complete_is_valid(client, active_player):
    closed = {str(cat): 0 for cat in range(13)}
    response = post(client, player1_scores=closed, player2_scores=closed, active_player=active_player)
    assert response.status_code == 200
    assert response.json['position']['completed'] is True
    assert response.json['position']['current_turn'] == 26


@pytest.mark.parametrize('active_player', [1, 2])
def test_selected_player_must_have_a_turn_left(client, active_player):
    payload = {f'player{active_player}_scores': {str(cat): 0 for cat in range(13)}}
    response = post(client, **payload, active_player=active_player)
    assert response.status_code == 400
    assert 'active_player' in response.json['error']
    assert f'select Player {3 - active_player}' in response.json['error']
    response = post(client, **payload, active_player=3 - active_player)
    assert response.status_code == 200
    assert response.json['position']['completed'] is False
    assert response.json['position']['current_turn'] == 14


@pytest.mark.parametrize('field,values', [
    ('active_player', [0, 3, True, 1.0, '1', None]),
    ('rolls_remaining', [-1, 3, True, 1.0, '1', None]),
    ('dice', [None, '12345', {}, [1] * 6, [0], [7], [True], [1.0], ['1']]),
    ('player1_scores', [None, [], {'13': 0}, {'0': True}, {'1': 3}, {'8': 10}, {'11': 25}, {'12': 2}]),
    ('player2_scores', [None, [], {'-1': 0}, {'0': 1.0}, {'5': 31}, {'9': 20}]),
    ('player1_yahtzee_bonuses', [-1, 1, 13, True, 1.0]),
    ('player2_yahtzee_status', [-1, 1, 2, 3, True, 1.0]),
])
def test_invalid_fields_return_actionable_errors(client, field, values):
    for value in values:
        response = post(client, **{field: value})
        assert response.status_code == 400, (field, value, response.json)
        assert field in response.json['error']


@pytest.mark.parametrize('payload', [
    {'player1_scores': {'11': 0}, 'player1_yahtzee_status': 2},
    {'player1_scores': {'11': 0, '0': 0}, 'player1_yahtzee_bonuses': 1},
    {'player2_scores': {'11': 50}, 'player2_yahtzee_bonuses': 1},
    {'player2_scores': {'11': 50, '0': 0}, 'player2_yahtzee_bonuses': 2},
])
def test_inconsistent_bonus_or_status_is_rejected(client, payload):
    assert post(client, **payload).status_code == 400


@pytest.mark.parametrize('body', [None, [], 1, 'bad'])
def test_non_object_body_is_rejected(client, body):
    response = client.post('/api/validate_position', data=json.dumps(body), content_type='application/json')
    assert response.status_code == 400 and response.is_json


def test_nonfinite_json_and_malformed_body_are_rejected(client):
    for body in ('{"dice":[NaN]}', '{'):
        response = client.post('/api/validate_position', data=body, content_type='application/json')
        assert response.status_code == 400 and response.is_json


def test_normalization_does_not_mutate_or_share_input():
    payload = {'player1_scores': {'0': 0}, 'dice': [4, None]}
    original = deepcopy(payload)
    result = parse_position(payload)
    assert payload == original
    result['position']['player1_scores']['0'] = 4
    result['position']['dice'][0] = 5
    assert payload == original
    assert parse_position(original)['position']['player1_scores']['0'] == 0
