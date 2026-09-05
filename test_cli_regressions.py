"""Exercise the public CLI with real solver results and bounded scorecards."""

import json

import pytest

from cli import FULL_MASK, format_recommendation, main, normalize_player


def run_json(capsys, *args):
    main(list(args) + ['--json'])
    return json.loads(capsys.readouterr().out)


def write_state(tmp_path, state):
    path = tmp_path / 'state.json'
    path.write_text(json.dumps(state))
    return str(path)


def test_default_rules_and_traditional_switch(capsys):
    joker = run_json(capsys, 'expected-score')
    traditional = run_json(capsys, 'expected-score', '--mode', 'traditional')
    assert joker['mode'] == 'joker'
    assert traditional['mode'] == 'traditional'
    assert joker['expected_score'] > traditional['expected_score']
    assert joker['policy'] == 'score_optimal'


def test_joker_recommendation_forces_upper_and_awards_bonus(capsys):
    rec = run_json(capsys, 'recommend', '--dice', '6,6,6,6,6',
                   '--mask', str(FULL_MASK ^ (1 << 5)), '--upper', '60',
                   '--rolls', '0', '--yahtzee-status', '2')
    assert rec['category'] == 5
    assert rec['points'] == 30
    assert rec['joker_bonus'] == 100
    assert rec['expected_value'] == 165


def test_joker_recommendation_forces_lower_before_unrelated_upper(capsys):
    rec = run_json(capsys, 'recommend', '--dice', '6,6,6,6,6',
                   '--mask', str(FULL_MASK ^ (1 << 0) ^ (1 << 8)),
                   '--rolls', '0', '--yahtzee-status', '2')
    assert rec['category'] == 8
    assert rec['points'] == 25
    assert rec['joker_bonus'] == 100
    assert {opt['category'] for opt in rec['category_options']} == {8}


def test_traditional_rules_do_not_award_joker_bonus(capsys):
    rec = run_json(capsys, 'recommend', '--mode', 'traditional',
                   '--dice', '6,6,6,6,6', '--mask', str(FULL_MASK ^ (1 << 8)), '--rolls', '0')
    assert rec['points'] == 0
    assert 'joker_bonus' not in rec


def test_reroll_format_preserves_duplicate_multiplicity():
    text = format_recommendation({'dice': [1, 1, 1, 2, 3], 'rolls_remaining': 1,
                                 'action': 'keep', 'keep_dice': [1, 1],
                                 'expected_value': 10.0, 'category_options': []})
    assert '(Reroll: [1, 2, 3])' in text


@pytest.mark.parametrize('extra', [
    ['--dice', '1,2,3,4'],
    ['--dice', '1,2,3,4,7'],
    ['--dice', '1,2,3,4,5', '--rolls', '3'],
    ['--dice', '1,2,3,4,5', '--rolls', '-1'],
    ['--dice', '1,2,3,4,5', '--mask', '-1'],
    ['--dice', '1,2,3,4,5', '--mask', '8192'],
    ['--dice', '1,2,3,4,5', '--upper', '-1'],
    ['--dice', '1,2,3,4,5', '--mask', '8191', '--yahtzee-status', '1'],
    ['--dice', '1,2,3,4,5', '--mask', '2048'],
    ['--dice', '1,2,3,4,5', '--yahtzee-status', '2'],
])
def test_bad_cli_inputs_fail_cleanly(capsys, extra):
    with pytest.raises(SystemExit) as exc:
        main(['recommend'] + extra)
    assert exc.value.code == 2
    assert 'error:' in capsys.readouterr().err


@pytest.mark.parametrize('state', [
    [], {'mask': True}, {'mask': None}, {'score': -1}, {'score': True},
    {'upper': 1.5}, {'mask': 2048, 'yahtzee_status': 0},
])
def test_json_state_rejects_invalid_types(state):
    with pytest.raises((ValueError, TypeError)):
        normalize_player(state, 'joker')


@pytest.mark.parametrize('score_a,score_b,expected', [(101, 100, (1, 0, 0)), (100, 100, (0, 1, 0)), (99, 100, (0, 0, 1))])
def test_completed_match_probabilities(capsys, score_a, score_b, expected):
    result = run_json(capsys, 'match', '--score-a', str(score_a), '--score-b', str(score_b),
                      '--mask-a', '8191', '--mask-b', '8191',
                      '--yahtzee-status-a', '1', '--yahtzee-status-b', '1')
    assert tuple(result[key] for key in ('win_prob', 'tie_prob', 'lose_prob')) == expected
    assert result['player_a']['name'] == 'Player A'
    assert result['player_b']['name'] == 'Player B'


def test_completed_match_upper_bonus_counted_once(capsys):
    result = run_json(capsys, 'match', '--score-a', '100', '--score-b', '134',
                      '--mask-a', '8191', '--mask-b', '8191', '--upper-a', '63',
                      '--yahtzee-status-a', '1', '--yahtzee-status-b', '1')
    assert result['player_a']['projected_final'] == 135
    assert result['win_prob'] == 1


def test_completed_outs_has_no_fictitious_turn(capsys):
    result = run_json(capsys, 'outs', '--score', '100', '--target', '135',
                      '--mask', '8191', '--upper', '63', '--yahtzee-status', '1')
    assert result['prob_reach_target'] == 1
    assert result['turn_thresholds'] == []
    assert result['category_probs'] == []


def test_distribution_commands_reject_unbounded_work(capsys):
    with pytest.raises(SystemExit) as exc:
        main(['match'])
    assert exc.value.code == 2
    assert 'at most 3 open categories' in capsys.readouterr().err


def test_early_game_solve_returns_recommendation_without_unbounded_pmf(tmp_path, capsys):
    state = write_state(tmp_path, {'dice': [1, 2, 3, 4, 5], 'rolls_remaining': 0,
                                  'current_player': {'mask': 0, 'upper': 0},
                                  'opponent': {'mask': 0, 'upper': 0}})
    result = run_json(capsys, 'solve', '--state', state)
    assert result['mode'] == 'joker'
    assert result['recommended_action']['category'] == 'Large Straight'
    assert 'distribution_unavailable' in result
    assert 'win_prob' not in result
    assert result['score_projection']['basis'] == 'start_of_turn'


def test_solve_state_mode_and_joker_status_are_honored(tmp_path, capsys):
    state = write_state(tmp_path, {'mode': 'joker', 'dice': [6] * 5, 'rolls_remaining': 0,
                                  'current_player': {'mask': FULL_MASK ^ (1 << 8), 'upper': 0,
                                                     'score': 50, 'yahtzee_status': 2}})
    result = run_json(capsys, 'solve', '--state', state)
    assert result['assumptions']['joker_rules'] is True
    assert result['recommended_action']['points'] == 25
    assert result['recommended_action']['joker_bonus'] == 100
    assert 'supplied dice affect recommendation only' in result['assumptions']['distribution_basis']


def test_solve_bad_json_fails_cleanly(tmp_path, capsys):
    path = tmp_path / 'broken.json'
    path.write_text('{not-json')
    with pytest.raises(SystemExit) as exc:
        main(['solve', '--state', str(path)])
    assert exc.value.code == 2
    assert 'error:' in capsys.readouterr().err
