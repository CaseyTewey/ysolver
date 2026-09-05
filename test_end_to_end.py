"""Seeded complete matches through real HTTP handlers and independent rules."""

from collections import Counter
import random

import pytest

import app as backend


def legal_scores(dice, scores):
    """Small independent rules oracle, with no scoring/EV imports."""
    counts = Counter(dice)
    yahtzee = len(counts) == 1
    joker = yahtzee and '11' in scores
    available = [cat for cat in range(13) if str(cat) not in scores]
    if joker:
        matching = dice[0] - 1
        if matching in available:
            available = [matching]
        elif any(cat >= 6 for cat in available):
            available = [cat for cat in available if cat >= 6]
    values = {}
    for cat in available:
        if cat < 6:
            points = counts[cat + 1] * (cat + 1)
        elif cat in (6, 7):
            points = sum(dice) if max(counts.values()) >= cat - 3 else 0
        elif cat == 8:
            points = 25 if joker or sorted(counts.values()) == [2, 3] else 0
        elif cat == 9:
            points = 30 if joker or any(set(range(start, start + 4)) <= counts.keys() for start in (1, 2, 3)) else 0
        elif cat == 10:
            points = 40 if joker or set(dice) in (set(range(1, 6)), set(range(2, 7))) else 0
        elif cat == 11:
            points = 50 if yahtzee else 0
        else:
            points = sum(dice)
        values[cat] = points
    return values, 100 if yahtzee and scores.get('11') == 50 else 0


@pytest.mark.parametrize('seed', range(12))
def test_complete_match_from_first_roll_through_saved_result(seed, tmp_path, monkeypatch):
    monkeypatch.setattr(backend, 'GAME_RESULTS_FILE', str(tmp_path / 'games.json'))
    rng = random.Random(seed)
    client = backend.app.test_client()
    states = [{}, {}]
    bonuses = [0, 0]
    for turn in range(13):
        for player in range(2):
            scores = states[player]
            dice = [rng.randint(1, 6) for _ in range(5)]
            for rolls_remaining in (2, 1, 0):
                payload = dict(dice=dice, scores=scores, rolls_remaining=rolls_remaining,
                               yahtzee_bonuses=bonuses[player])
                response = client.post('/api/recommend', json=payload)
                assert response.status_code == 200, response.json
                recommendation = response.json
                legal, bonus = legal_scores(dice, scores)
                assert {x['category']: x['points'] for x in recommendation['category_options']} == legal
                assert recommendation['joker_bonus_available'] == bool(bonus)
                assert recommendation['expected_value'] + .011 >= max(x['expected_value'] for x in recommendation['category_options'])
                if rolls_remaining:
                    assert recommendation['action'] == 'keep'
                    keep = recommendation['keep_dice']
                    assert not (Counter(keep) - Counter(dice))
                    assert Counter(keep) + Counter(recommendation['reroll']) == Counter(dice)
                    dice = keep + [rng.randint(1, 6) for _ in range(5 - len(keep))]
                else:
                    assert recommendation['action'] == 'score'
                    category = recommendation['category']
                    assert recommendation['points'] == legal[category]
                    assert str(category) not in scores
                    scores[str(category)] = legal[category]
                    bonuses[player] += bonus // 100
            ev = client.post('/api/game_ev', json={'scores': scores, 'yahtzee_bonuses': bonuses[player]})
            assert ev.status_code == 200
            expected_current = sum(scores.values()) + bonuses[player] * 100
            if sum(scores.get(str(cat), 0) for cat in range(6)) >= 63:
                expected_current += 35
            assert ev.json['current_score'] == expected_current
            assert ev.json['ev_remaining'] >= 0
            assert ev.json['categories_remaining'] == 12 - turn
            if turn == 12:
                assert ev.json['ev_remaining'] == 0 and ev.json['expected_final'] == expected_current

    payload = {'player1_scores': states[0], 'player2_scores': states[1],
               'player1_yahtzee_bonuses': bonuses[0], 'player2_yahtzee_bonuses': bonuses[1]}
    approx = client.post('/api/win_probability', json=payload)
    exact = client.post('/api/win_probability_exact', json=payload)
    assert approx.status_code == exact.status_code == 200
    for field in ('player1', 'player2'):
        assert approx.json[field]['win_probability'] == exact.json[field]['win_probability']
    assert approx.json['tie_probability'] == exact.json['tie_probability']
    assert sum(exact.json[field]['win_probability'] for field in ('player1', 'player2')) + exact.json['tie_probability'] == 100
    saved = client.post('/api/save_game', json=payload)
    assert saved.status_code == 200
    detail = client.get('/api/game_details/' + str(saved.json['game_id'])).json
    assert detail['player1_scores'] == states[0] and detail['player2_scores'] == states[1]
