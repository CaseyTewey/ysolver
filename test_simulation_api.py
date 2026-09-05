"""HTTP integration for sampled early-game odds and their uncertainty contract."""

import math

import pytest

import app as backend


def simulation_fixture(counts=(7500, 100, 2400)):
    """A valid engine result with independent Wilson interval calculations."""
    sample_count = sum(counts)
    z = 1.959963984540054
    probabilities = tuple(count / sample_count for count in counts)
    intervals = []
    for probability in probabilities:
        denominator = 1 + z * z / sample_count
        center = (probability + z * z / (2 * sample_count)) / denominator
        half_width = z * math.sqrt(probability * (1 - probability) / sample_count
                                   + z * z / (4 * sample_count * sample_count)) / denominator
        intervals.append((max(0.0, center - half_width), min(1.0, center + half_width)))
    return dict(probabilities=probabilities, counts=counts, intervals=tuple(intervals),
                sample_count=sample_count, confidence_level=.95,
                max_margin_percentage_points=max(
                    max(probability - low, high - probability) * 100
                    for probability, (low, high) in zip(probabilities, intervals)))


def scores_with_open_categories(*categories):
    return {str(category): 0 for category in range(13) if category not in categories}


def early_payload():
    return dict(player1_scores={}, player2_scores={})


@pytest.fixture
def client():
    backend.app.config.update(TESTING=True)
    backend._cached_exact_probabilities.cache_clear()
    backend._cached_simulation_probabilities.cache_clear()
    yield backend.app.test_client()
    backend._cached_exact_probabilities.cache_clear()
    backend._cached_simulation_probabilities.cache_clear()


@pytest.fixture
def fake_simulation(monkeypatch):
    calls = []

    def simulate(*args, **kwargs):
        calls.append((args, kwargs))
        return simulation_fixture()

    monkeypatch.setattr(backend, 'simulate_match', simulate)
    return calls


def assert_sampled_uncertainty(body):
    assert body['method'] == 'monte_carlo'
    assert body['is_exact'] is False
    assert body['objective'] == 'maximize_expected_score'
    assert body['distribution_basis'] == 'start_of_turn'
    assert body['approximation']['method'] == 'monte_carlo'
    assert body['approximation']['is_approximate'] is True
    assert body['approximation']['exact_feasible'] is False
    simulation = body['simulation']
    assert simulation['sample_count'] == 10_000
    assert simulation['confidence_level'] == .95
    assert simulation['target_margin_percentage_points'] == 1
    assert 0 <= simulation['max_margin_percentage_points'] <= 1
    assert sum(simulation['counts'].values()) == 10_000
    assert set(simulation['counts']) == {'player1', 'tie', 'player2'}
    assert set(simulation['intervals']) == {'player1', 'tie', 'player2'}
    estimates = (body['player1']['win_probability'], body['tie_probability'],
                 body['player2']['win_probability'])
    assert sum(estimates) == pytest.approx(100, abs=.011)
    intervals = (body['player1']['win_probability_interval'], body['tie_probability_interval'],
                 body['player2']['win_probability_interval'])
    for key, estimate, interval in zip(('player1', 'tie', 'player2'), estimates, intervals):
        low, high = interval
        assert interval == simulation['intervals'][key]
        assert math.isfinite(low) and math.isfinite(high)
        assert 0 <= low <= estimate <= high <= 100
        assert high - low <= 2.001
        assert high > low  # Even sampled zero/all outcomes retain uncertainty.


def test_early_game_response_reports_sampling_precision(client, fake_simulation):
    response = client.post('/api/win_probability', json=early_payload())
    assert response.status_code == 200
    body = response.json
    assert_sampled_uncertainty(body)
    assert body['simulation']['counts'] == {'player1': 7500, 'tie': 100, 'player2': 2400}
    assert body['player1']['win_probability'] == 75
    assert body['tie_probability'] == 1
    assert body['player2']['win_probability'] == 24
    assert body['player1']['win_probability_display'] == '~75%'
    assert body['tie_probability_display'].startswith('~')
    assert body['player2']['win_probability_display'].startswith('~')
    assert len(fake_simulation) == 1


def test_client_cannot_reduce_sample_count_or_change_confidence(client, fake_simulation):
    payload = dict(early_payload(), sample_count=1, samples=1, num_samples=1,
                   confidence_level=.5, target_margin_percentage_points=50)
    response = client.post('/api/win_probability', json=payload)
    assert response.status_code == 200
    assert_sampled_uncertainty(response.json)
    _, kwargs = fake_simulation[0]
    assert kwargs.get('sample_count', 10_000) == 10_000
    assert kwargs.get('num_samples', 10_000) == 10_000
    assert kwargs.get('confidence_level', .95) == .95


def test_early_game_never_uses_previous_normal_model_or_exact_solver(client, fake_simulation, monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail('Early-game odds must come only from the simulation engine')

    monkeypatch.setattr(backend, 'compute_win_probability', unexpected)
    monkeypatch.setattr(backend, 'compute_win_probability_joker_exact', unexpected)
    response = client.post('/api/win_probability', json=early_payload())
    assert response.status_code == 200
    assert response.json['method'] == 'monte_carlo'
    assert len(fake_simulation) == 1


def test_uncached_simulation_returns_retryable_busy_without_fallback(client, fake_simulation):
    assert backend._exact_slot.acquire(blocking=False)
    try:
        response = client.post('/api/win_probability', json=early_payload())
    finally:
        backend._exact_slot.release()
    assert response.status_code == 503
    assert response.is_json and response.json['error']
    assert response.headers['Retry-After'] == '1'
    assert 'player1' not in response.json
    assert fake_simulation == []
    recovered = client.post('/api/win_probability', json=early_payload())
    assert recovered.status_code == 200
    assert len(fake_simulation) == 1


def test_cached_simulation_stays_available_while_another_calculation_runs(client, fake_simulation):
    initial = client.post('/api/win_probability', json=early_payload())
    assert initial.status_code == 200
    assert backend._exact_slot.acquire(blocking=False)
    try:
        cached = client.post('/api/win_probability', json=early_payload())
        uncached = client.post('/api/win_probability', json=dict(early_payload(), player1_scores={'0': 0}))
    finally:
        backend._exact_slot.release()
    assert cached.status_code == 200 and cached.json == initial.json
    assert uncached.status_code == 503
    assert len(fake_simulation) == 1


def test_simulation_failures_are_not_cached_and_always_release_gate(client, fake_simulation, monkeypatch):
    with monkeypatch.context() as patch:
        def fail(*args, **kwargs):
            raise RuntimeError('deliberate Monte Carlo failure')
        patch.setattr(backend, 'simulate_match', fail)
        response = client.post('/api/win_probability', json=early_payload())
    assert response.status_code == 500
    assert response.is_json and response.json['error']
    assert 'simulation' not in response.json and 'player1' not in response.json
    recovered = client.post('/api/win_probability', json=early_payload())
    assert recovered.status_code == 200
    assert_sampled_uncertainty(recovered.json)
    assert len(fake_simulation) == 1


@pytest.mark.parametrize('counts', [(10_000, 0, 0), (0, 0, 10_000), (0, 10_000, 0)])
def test_all_sampled_outcomes_are_not_displayed_as_certainty(client, monkeypatch, counts):
    monkeypatch.setattr(backend, 'simulate_match', lambda *args, **kwargs: simulation_fixture(counts))
    response = client.post('/api/win_probability', json=early_payload())
    assert response.status_code == 200
    body = response.json
    assert_sampled_uncertainty(body)
    displays = (body['player1']['win_probability_display'], body['tie_probability_display'],
                body['player2']['win_probability_display'])
    for count, display in zip(counts, displays):
        assert display == ('>99.9%' if count == 10_000 else '<0.1%')


@pytest.mark.parametrize('counts', [(1, 0, 9999), (9999, 1, 0), (9, 1, 9990)])
def test_rare_sampled_outcomes_keep_interval_and_nonzero_display(client, monkeypatch, counts):
    monkeypatch.setattr(backend, 'simulate_match', lambda *args, **kwargs: simulation_fixture(counts))
    response = client.post('/api/win_probability', json=early_payload())
    assert response.status_code == 200
    body = response.json
    assert_sampled_uncertainty(body)
    displays = (body['player1']['win_probability_display'], body['tie_probability_display'],
                body['player2']['win_probability_display'])
    for count, display in zip(counts, displays):
        assert display not in ('0%', '100%', '~0%', '~100%')
        if count < 10:
            assert display == '<0.1%'


def test_simulation_cache_separates_bonus_offsets_and_status(client, fake_simulation):
    # Upper63 has already earned35. Engine locked score must exclude it, while
    # including past100-point chips. Open lower boxes keep this in MC territory.
    p1 = {str(category): 3 * (category + 1) for category in range(6)}
    p1['11'] = 50
    payload = dict(early_payload(), player1_scores=p1, player1_yahtzee_bonuses=1)
    first = client.post('/api/win_probability', json=payload)
    second = client.post('/api/win_probability', json=dict(payload, player1_yahtzee_bonuses=2))
    assert first.status_code == second.status_code == 200
    assert first.json['player1']['current_score'] == 248
    assert first.json['player1']['bonus_points'] == 100
    assert second.json['player1']['current_score'] == 348
    assert len(fake_simulation) == 2
    first_args, _ = fake_simulation[0]
    second_args, _ = fake_simulation[1]
    assert first_args[:4] == (213, 63 | (1 << 11), 63, 2)
    assert second_args[:4] == (313, 63 | (1 << 11), 63, 2)
    assert first.json['player1']['expected_final'] == pytest.approx(
        first.json['player1']['current_score'] + first.json['player1']['ev_remaining'], abs=.011)
    scratch = dict(payload, player1_scores=dict(p1, **{'11': 0}), player1_yahtzee_bonuses=0)
    third = client.post('/api/win_probability', json=scratch)
    assert third.status_code == 200
    assert len(fake_simulation) == 3
    assert fake_simulation[2][0][:4] == (63, 63 | (1 << 11), 63, 1)


def test_scorecard_key_order_and_null_boxes_share_cached_simulation(client, fake_simulation):
    first = client.post('/api/win_probability', json=dict(early_payload(), player1_scores={'0': 1, '1': 2}))
    second = client.post('/api/win_probability', json=dict(early_payload(), player1_scores={'3': None, '1': 2, '0': 1}))
    assert first.status_code == second.status_code == 200
    assert first.json == second.json
    assert len(fake_simulation) == 1


def test_explicit_exact_endpoint_rejects_early_state_without_starting_simulation(client, fake_simulation):
    response = client.post('/api/win_probability_exact', json=early_payload())
    assert response.status_code == 400
    assert response.json['feasible'] is False
    assert fake_simulation == []


def test_exact_and_deterministic_routes_do_not_use_simulation(client, monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail('An endgame must use its discrete distribution')
    monkeypatch.setattr(backend, 'simulate_match', unexpected)
    completed = scores_with_open_categories()
    for scores, method in ((scores_with_open_categories(12), 'exact_pmf_joker'),
                           (completed, 'deterministic')):
        response = client.post('/api/win_probability', json=dict(player1_scores=scores, player2_scores=completed))
        assert response.status_code == 200
        assert response.json['method'] == method
        assert response.json['is_exact'] is True
        assert 'simulation' not in response.json or response.json['simulation'] is None


def test_genuine_opening_yahtzee_lead_uses_ten_thousand_complete_games(client):
    # P1 scored a Yahtzee on turn1; P2 has a fresh scorecard. The independent
    # engine checks verify policy play and dice sampling.
    payload = dict(player1_scores={'11': 50}, player2_scores={})
    response = client.post('/api/win_probability', json=payload)
    assert response.status_code == 200
    body = response.json
    assert_sampled_uncertainty(body)
    assert body['player1']['win_probability'] == pytest.approx(75, abs=2)
    assert body['player1']['current_score'] == 50
    assert body['player2']['current_score'] == 0
