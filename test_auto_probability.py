"""Automatic endgame selection checked against analytical distributions and HTTP behavior."""
import math

import pytest

import app as backend


def completed_scores():
    return {str(category): 0 for category in range(13)}


def late_scores(*open_categories):
    scores = completed_scores()
    for category in open_categories:
        del scores[str(category)]
    return scores


def payload_for(p1, p2, **extras):
    return dict(player1_scores=p1, player2_scores=p2, **extras)


def probabilities(body):
    return (body['player1']['win_probability'], body['tie_probability'],
            body['player2']['win_probability'])


def swap_players(payload):
    return {('player2_' + key[8:] if key.startswith('player1_') else
             'player1_' + key[8:] if key.startswith('player2_') else key): value
            for key, value in payload.items()}


def assert_probabilities(body):
    values = probabilities(body)
    assert all(math.isfinite(value) and 0 <= value <= 100 for value in values)
    # Each of the three exact percentages is rounded independently to 0.01.
    assert sum(values) == pytest.approx(100, abs=.011)


@pytest.fixture
def client(monkeypatch):
    backend.app.config.update(TESTING=True)
    # Result memos are process-local; isolate failure and gate tests. Boundary
    # cases test routing, while the simulation API suite covers the real engine.
    backend._cached_exact_probabilities.cache_clear()
    backend._cached_simulation_probabilities.cache_clear()
    from test_simulation_api import simulation_fixture
    monkeypatch.setattr(backend, 'simulate_match', lambda *args, **kwargs: simulation_fixture())
    return backend.app.test_client()


@pytest.mark.parametrize('category,win_percent', [(11,4.60),(10,26.53),(9,61.60),(8,36.61)])
def test_two_point_deficit_uses_discrete_three_roll_endgame(client, category, win_percent):
    opponent = completed_scores()
    opponent['0'] = 2
    payload = payload_for(late_scores(category), opponent)
    response = client.post('/api/win_probability', json=payload)
    assert response.status_code == 200
    body = response.json
    assert body['method'] == 'exact_pmf_joker' and body['is_exact'] is True
    assert body['objective'] == 'maximize_expected_score'
    assert body['approximation']['distribution_basis'] == 'start_of_turn'
    assert body['player1']['current_score'] == 0
    assert body['player2']['current_score'] == 2
    assert body['player1']['win_probability'] == win_percent
    assert body['tie_probability'] == 0
    assert body['player2']['ev_remaining'] == 0
    assert body['player2']['expected_final'] == 2
    assert_probabilities(body)
    dedicated = client.post('/api/win_probability_exact', json=payload)
    assert dedicated.status_code == 200
    assert probabilities(body) == probabilities(dedicated.json)


@pytest.mark.parametrize('p1_count,p2_count,method', [
    (4,4,'exact_pmf_joker'), (4,0,'exact_pmf_joker'), (0,4,'exact_pmf_joker'),
    (5,4,'monte_carlo'), (4,5,'monte_carlo'), (5,0,'monte_carlo'), (0,5,'monte_carlo'),
])
def test_four_category_boundary_applies_to_each_player(client, p1_count, p2_count, method):
    open_order = (8,9,10,12,6)
    payload = payload_for(late_scores(*open_order[:p1_count]), late_scores(*open_order[:p2_count]))
    response = client.post('/api/win_probability', json=payload)
    assert response.status_code == 200
    body = response.json
    assert body['method'] == method
    assert body['is_exact'] is (method == 'exact_pmf_joker')
    assert body['player1']['categories_remaining'] == p1_count
    assert body['player2']['categories_remaining'] == p2_count
    assert body['approximation']['exact_feasible'] is (method == 'exact_pmf_joker')
    if method == 'monte_carlo':
        assert body['simulation']['sample_count'] == 10_000
        assert body['simulation']['max_margin_percentage_points'] <= 1
        assert body['player1']['win_probability_display'].startswith('~')


def test_last_ones_probabilities_include_ties_and_reverse_when_swapped(client):
    opponent = completed_scores()
    opponent['0'] = 2
    payload = payload_for(late_scores(0), opponent)
    chance = 1 - (5/6)**3
    hits = {n: math.comb(5,n)*chance**n*(1-chance)**(5-n) for n in range(6)}
    expected = (round(sum(p for n,p in hits.items() if n > 2)*100,2),
                round(hits[2]*100,2), round((hits[0]+hits[1])*100,2))
    first = client.post('/api/win_probability', json=payload).json
    second = client.post('/api/win_probability', json=swap_players(payload)).json
    assert probabilities(first) == expected
    assert probabilities(second) == expected[::-1]
    assert first['tie_probability'] > 0
    assert_probabilities(first)


def test_identical_live_endgames_have_equal_wins_and_positive_ties(client):
    payload = payload_for(late_scores(12), late_scores(12))
    body = client.post('/api/win_probability', json=payload).json
    assert body['player1']['win_probability'] == body['player2']['win_probability']
    assert body['tie_probability'] > 0
    assert body['player1']['expected_final'] == 23.33
    assert body['player1']['ev_remaining'] == 23.33
    assert_probabilities(body)


def test_upper_bonus_cliff_uses_discrete_bonus_distribution(client):
    p1 = late_scores(0)
    for category in range(1,6):
        p1[str(category)] = 3*(category+1)
    p2 = dict(p1, **{'0':0, '12':20})
    chance = 1 - (5/6)**3
    earn_bonus = sum(math.comb(5,n)*chance**n*(1-chance)**(5-n) for n in range(3,6))
    body = client.post('/api/win_probability', json=payload_for(p1,p2)).json
    assert body['player1']['current_score'] == 60
    assert body['player2']['current_score'] == 80
    assert body['player1']['ev_remaining'] == round(5*chance+35*earn_bonus,2)
    assert body['player1']['win_probability'] == round(100*earn_bonus,2)
    assert body['tie_probability'] == 0
    assert_probabilities(body)


def test_already_earned_upper_bonus_not_added_twice(client):
    p1 = late_scores(12)
    for category in range(6):
        p1[str(category)] = 3*(category+1)
    p2 = dict(p1, **{'12':22})
    distribution = {0:1.0}
    die = {1:1/18, 2:1/18, 3:1/18, 4:1/6, 5:1/3, 6:1/3}
    for _ in range(5):
        updated = {}
        for current,probability in distribution.items():
            for face,face_prob in die.items():
                updated[current+face] = updated.get(current+face,0)+probability*face_prob
        distribution = updated
    expected = (round(sum(p for s,p in distribution.items() if s>22)*100,2),
                round(distribution[22]*100,2), round(sum(p for s,p in distribution.items() if s<22)*100,2))
    payload = payload_for(p1,p2)
    body = client.post('/api/win_probability', json=payload).json
    assert body['player1']['current_score'] == 98
    assert body['player1']['ev_remaining'] == 23.33
    assert body['player1']['expected_final'] == 121.33
    assert body['player2']['current_score'] == 120
    assert probabilities(body) == expected
    assert probabilities(client.post('/api/win_probability_exact',json=payload).json) == expected


def test_future_yahtzee_bonus_tail_is_automatically_exact(client):
    p1 = late_scores(12)
    p1['11'] = 50
    p2 = completed_scores()
    p2.update({str(category):3*(category+1) for category in range(6)})
    p2.update({'11':50,'12':27})
    payload = payload_for(p1,p2)
    body = client.post('/api/win_probability',json=payload).json
    assert body['method'] == 'exact_pmf_joker'
    assert probabilities(body) == (.97,.87,98.16)
    assert body['player1']['current_score'] == 50
    assert body['player2']['current_score'] == 175
    assert probabilities(client.post('/api/win_probability_exact',json=payload).json) == probabilities(body)


def test_earned_yahtzee_bonuses_shift_exact_locked_score(client):
    p1 = late_scores(12)
    p1['11'] = 50
    p2 = completed_scores()
    p2.update({'10':40,'11':50,'12':10})
    payload = payload_for(p1,p2,player1_yahtzee_bonuses=1)
    body = client.post('/api/win_probability',json=payload).json
    assert body['player1']['current_score'] == 150
    assert body['player1']['bonus_points'] == 100
    assert body['player1']['expected_final'] == round(150+body['player1']['ev_remaining'],2)
    assert probabilities(body) == (100,0,0)
    reverse = client.post('/api/win_probability',json=swap_players(payload)).json
    assert probabilities(reverse) == (0,0,100)


@pytest.mark.parametrize('lead,expected', [(0,(0,100,0)),(1,(100,0,0)),(-1,(0,0,100))])
def test_completed_game_is_deterministic_even_when_exact_gate_is_busy(client, lead, expected):
    p1 = completed_scores()
    p2 = completed_scores()
    (p1 if lead>0 else p2)['0'] = abs(lead)
    assert backend._exact_slot.acquire(blocking=False)
    try:
        response = client.post('/api/win_probability',json=payload_for(p1,p2))
    finally:
        backend._exact_slot.release()
    assert response.status_code == 200
    assert response.json['method'] == 'deterministic' and response.json['is_exact'] is True
    assert probabilities(response.json) == expected
    assert response.json['player1']['ev_remaining'] == response.json['player2']['ev_remaining'] == 0


def test_busy_exact_request_returns_retryable_error_without_normal_fallback(client):
    assert backend._exact_slot.acquire(blocking=False)
    try:
        response = client.post('/api/win_probability',json=payload_for(late_scores(0),completed_scores()))
    finally:
        backend._exact_slot.release()
    assert response.status_code == 503
    assert response.is_json and response.json['error']
    assert response.headers['Retry-After'] == '1'
    assert 'player1' not in response.json


def test_early_game_uses_shared_gate_without_calling_exact_solver(client, monkeypatch):
    def unexpected_call(*args, **kwargs):
        pytest.fail('An early-game estimate must not call the exact solver')
    monkeypatch.setattr(backend,'compute_win_probability_joker_exact',unexpected_call)
    assert backend._exact_slot.acquire(blocking=False)
    try:
        response = client.post('/api/win_probability',json=payload_for({},completed_scores()))
    finally:
        backend._exact_slot.release()
    assert response.status_code == 503
    assert response.is_json and response.json['error']
    assert response.headers['Retry-After'] == '1'
    assert 'player1' not in response.json
    recovered = client.post('/api/win_probability', json=payload_for({},completed_scores()))
    assert recovered.status_code == 200
    assert recovered.json['method'] == 'monte_carlo' and recovered.json['is_exact'] is False


def test_solver_failure_does_not_return_approximate_success_and_releases_gate(client, monkeypatch):
    payload = payload_for(late_scores(12),completed_scores())
    with monkeypatch.context() as local_patch:
        def fail(*args, **kwargs):
            raise RuntimeError('Deliberate exact solver failure')
        local_patch.setattr(backend,'compute_win_probability_joker_exact',fail)
        response = client.post('/api/win_probability',json=payload)
    assert response.status_code == 500
    assert response.is_json and response.json['error']
    assert 'player1' not in response.json
    restored = client.post('/api/win_probability',json=payload)
    assert restored.status_code == 200 and restored.json['is_exact'] is True


def test_automatic_and_dedicated_routes_share_successful_exact_results(client, monkeypatch):
    real_solver = backend.compute_win_probability_joker_exact
    calls = []
    def counted(*args, **kwargs):
        calls.append((args,kwargs))
        return real_solver(*args,**kwargs)
    monkeypatch.setattr(backend,'compute_win_probability_joker_exact',counted)
    payload = payload_for(late_scores(8),late_scores(9))
    automatic = client.post('/api/win_probability',json=payload)
    dedicated = client.post('/api/win_probability_exact',json=payload)
    repeated = client.post('/api/win_probability',json=payload)
    assert automatic.status_code == dedicated.status_code == repeated.status_code == 200
    assert probabilities(automatic.json) == probabilities(dedicated.json) == probabilities(repeated.json)
    assert len(calls) == 1


def test_cached_endgame_result_remains_available_while_another_exact_solve_runs(client):
    cached_payload = payload_for(late_scores(11),completed_scores())
    initial = client.post('/api/win_probability',json=cached_payload)
    assert initial.status_code == 200
    assert backend._exact_slot.acquire(blocking=False)
    try:
        cached = client.post('/api/win_probability',json=cached_payload)
        uncached = client.post('/api/win_probability',json=payload_for(late_scores(10),completed_scores()))
    finally:
        backend._exact_slot.release()
    assert cached.status_code == 200 and cached.json == initial.json
    assert uncached.status_code == 503


def test_exact_cache_separates_earned_bonus_offsets(client):
    p1 = late_scores(12)
    p1['11'] = 50
    p2 = completed_scores()
    p2.update({'10':40,'11':50,'12':10})
    payload = payload_for(p1,p2)
    before = client.post('/api/win_probability',json=payload).json
    after = client.post('/api/win_probability',json=dict(payload,player1_yahtzee_bonuses=1)).json
    assert before['player1']['win_probability'] < 100
    assert after['player1']['win_probability'] == 100
    assert before['player1']['current_score'] + 100 == after['player1']['current_score']
