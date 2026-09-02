"""
API tests for app.py using Flask's test client.

Run: cd <repo> && .venv/bin/python -m pytest tests/test_api.py -q
Self contained: no conftest fixtures are used. Importing app builds/loads the solver once.
"""
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import app as app_module  # noqa: E402

SOLVER = app_module.SOLVER
CAP = app_module.MAX_OPEN_FOR_EXACT

FRESH_EV = 254.59
FRESH_STD = 59.61
KEEP_ALL_EV = 261.53           # fresh game, 1-2-3-4-5 in hand, keep everything

# scorecards used by several tests
UPPER_63 = {"0": 3, "1": 6, "2": 9, "3": 12, "4": 15, "5": 18}                  # upper exactly 63
OPEN_7 = dict(UPPER_63)                                                           # 7 lower boxes open
OPEN_4 = dict(UPPER_63, **{"6": 20, "7": 20, "8": 25})                            # 4 boxes open
OPEN_8 = {"0": 3, "1": 6, "2": 9, "3": 12, "4": 15}                               # 8 boxes open


@pytest.fixture(scope="module")
def client():
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as c:
        yield c


def post(client, path, body):
    return client.post(path, data=json.dumps(body), content_type="application/json")


def recommend(client, dice, rolls_remaining, scores=None, **extra):
    body = {"dice": dice, "rolls_remaining": rolls_remaining, "scores": scores or {}}
    body.update(extra)
    resp = post(client, "/api/recommend", body)
    assert resp.status_code == 200, resp.get_json()
    return resp.get_json()


def option_by_name(data, name):
    return next(o for o in data["category_options"] if o["name"] == name)


# ------------------------------------------------------------------------------------------
# /api/recommend
# ------------------------------------------------------------------------------------------
def test_index_serves_html(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"<html" in resp.data.lower()


def test_fresh_recommend_rr2_keeps_all_five(client):
    data = recommend(client, [1, 2, 3, 4, 5], 2)
    assert data["action"] == "keep"
    assert data["keep_dice"] == [1, 2, 3, 4, 5]
    assert data["keep_all"] is True
    assert data["reroll"] == []
    assert data["expected_value"] == pytest.approx(KEEP_ALL_EV, abs=0.005)
    assert data["mode"] == "joker"
    assert data["rules"] == "hasbro"
    assert data["std"] == pytest.approx(FRESH_STD, abs=0.005)
    assert data["mask"] == 0 and data["upper"] == 0
    assert data["yahtzee_status"] == 0 and data["yahtzee_bonuses"] == 0
    assert data["joker_rule"] is None
    assert data["forced_category"] is None
    assert data["is_yahtzee_roll"] is False
    assert data["joker_bonus_available"] is False
    assert "joker_bonus" not in data
    # every legal box is listed, best first
    opts = data["category_options"]
    assert len(opts) == 13
    evs = [o["expected_value"] for o in opts]
    assert evs == sorted(evs, reverse=True)
    assert opts[0]["name"] == "Large Straight" and opts[0]["points"] == 40
    assert set(opts[0]) >= {"category", "name", "points", "expected_value", "is_forced"}


def test_fresh_recommend_rr1_keeps_all_five(client):
    data = recommend(client, [1, 2, 3, 4, 5], 1)
    assert data["action"] == "keep"
    assert data["keep_all"] is True
    assert data["reroll"] == []
    assert data["expected_value"] == pytest.approx(KEEP_ALL_EV, abs=0.005)


def test_fresh_recommend_rr0_scores_large_straight(client):
    data = recommend(client, [1, 2, 3, 4, 5], 0)
    assert data["action"] == "score"
    assert data["category"] == 10
    assert data["category_name"] == "Large Straight"
    assert data["points"] == 40
    assert data["expected_value"] == pytest.approx(KEEP_ALL_EV, abs=0.005)
    assert "keep_dice" not in data


def test_reroll_is_multiset_difference(client):
    data = recommend(client, [6, 6, 1, 2, 6], 2)
    assert data["action"] == "keep"
    assert data["keep_dice"] == [6, 6, 6]
    assert sorted(data["reroll"]) == [1, 2]
    assert data["keep_all"] is False


def test_natural_yahtzee_scores_fifty(client):
    data = recommend(client, [6, 6, 6, 6, 6], 0)
    assert data["action"] == "score"
    assert data["category"] == 11
    assert data["category_name"] == "Yahtzee"
    assert data["points"] == 50
    assert data["is_yahtzee_roll"] is True
    assert data["joker_bonus_available"] is False
    assert "joker_bonus" not in data
    assert data["joker_rule"] is None


def test_joker_forced_upper_with_bonus(client):
    data = recommend(client, [4, 4, 4, 4, 4], 0, {"11": 50})
    assert data["action"] == "score"
    assert data["category"] == 3 and data["category_name"] == "Fours"
    assert data["points"] == 20
    assert data["joker_bonus"] == 100
    assert data["joker_bonus_available"] is True
    assert data["joker_rule"] == "forced_upper"
    assert data["forced_category"] == 3
    assert data["forced_category_name"] == "Fours"
    assert data["yahtzee_status"] == 2
    assert len(data["category_options"]) == 1
    assert data["category_options"][0]["is_forced"] is True
    # with rolls left the engine still recognises the forced box and keeps the Yahtzee
    data2 = recommend(client, [4, 4, 4, 4, 4], 2, {"11": 50})
    assert data2["action"] == "keep" and data2["keep_all"] is True
    assert data2["forced_category"] == 3 and data2["joker_bonus"] == 100


def test_joker_lower_only_when_upper_box_filled(client):
    data = recommend(client, [4, 4, 4, 4, 4], 0, {"11": 50, "3": 12})
    assert data["joker_rule"] == "lower_only"
    assert data["forced_category"] is None
    assert data["joker_bonus"] == 100
    assert data["action"] == "score"
    assert data["category"] == 10 and data["points"] == 40
    ls = option_by_name(data, "Large Straight")
    assert ls["points"] == 40 and ls["is_forced"] is False
    assert option_by_name(data, "Full House")["points"] == 25
    assert option_by_name(data, "Small Straight")["points"] == 30
    assert all(o["category"] >= 6 and o["category"] != 11 for o in data["category_options"])


def test_joker_after_scratched_yahtzee_has_no_bonus(client):
    data = recommend(client, [4, 4, 4, 4, 4], 0, {"11": 0, "3": 12})
    assert data["yahtzee_status"] == 1
    assert data["joker_rule"] == "lower_only"
    assert data["joker_bonus_available"] is False
    assert "joker_bonus" not in data
    assert option_by_name(data, "Full House")["points"] == 25
    assert option_by_name(data, "Large Straight")["points"] == 40


def test_joker_zero_upper_when_lower_section_full(client):
    scores = {"11": 0, "3": 12, "6": 20, "7": 20, "8": 25, "9": 30, "10": 40, "12": 20}
    data = recommend(client, [4, 4, 4, 4, 4], 0, scores)
    assert data["joker_rule"] == "zero_upper"
    assert all(o["points"] == 0 and o["category"] < 6 for o in data["category_options"])


def test_scorecard_wins_over_client_yahtzee_status(client):
    # scorecard says 50 in the Yahtzee box, client claims it is unfilled
    data = recommend(client, [4, 4, 4, 4, 4], 0, {"11": 50}, yahtzee_status=0)
    assert data["yahtzee_status"] == 2
    assert data["joker_bonus"] == 100
    assert data["forced_category"] == 3
    # scorecard says the box is open, client claims it holds 50
    data = recommend(client, [6, 6, 6, 6, 6], 0, {}, yahtzee_status=2)
    assert data["yahtzee_status"] == 0
    assert data["category"] == 11 and data["points"] == 50
    assert "joker_bonus" not in data


def test_recommend_upper_over_63_is_clamped(client):
    scores = {"0": 5, "1": 10, "2": 15, "3": 20, "4": 25, "5": 30}   # raw 105
    data = recommend(client, [1, 2, 3, 4, 5], 0, scores)
    assert data["upper"] == 63 and data["upper_raw"] == 105


@pytest.mark.parametrize("body", [
    {"dice": [1, 2, 3, 4, 7], "rolls_remaining": 2, "scores": {}},
    {"dice": [1, 2, 3, 4], "rolls_remaining": 2, "scores": {}},
    {"dice": [1, 2, 3, 4, 5], "rolls_remaining": 3, "scores": {}},
    {"dice": [1, 2, 3, 4, 5], "rolls_remaining": 2, "scores": {"0": "3"}},
    {"dice": [1, 2, 3, 4, 5], "rolls_remaining": 2, "scores": {"0": 7}},
    {"dice": [1, 2, 3, 4, 5], "rolls_remaining": 2, "scores": {"0": -1}},
    {"dice": [1, 2, 3, 4, 5], "rolls_remaining": 2, "scores": {"12": 31}},
    {"dice": [1, 2, 3, 4, 5], "rolls_remaining": 2, "scores": {"13": 5}},
    {"dice": [1, 2, 3, 4, 5], "rolls_remaining": 2, "scores": []},
    {"dice": [1, 2, 3, 4, 5], "rolls_remaining": 2, "scores": {}, "yahtzee_status": 5},
    {"dice": [1, 2, 3, 4, 5], "rolls_remaining": 2, "scores": {}, "yahtzee_bonuses": -1},
    {"dice": "12345", "rolls_remaining": 2, "scores": {}},
])
def test_recommend_invalid_inputs_return_400_json(client, body):
    resp = post(client, "/api/recommend", body)
    assert resp.status_code == 400
    assert resp.is_json
    assert "error" in resp.get_json()


def test_recommend_non_json_body_returns_400(client):
    resp = client.post("/api/recommend", data="this is not json", content_type="application/json")
    assert resp.status_code == 400 and resp.is_json
    assert "error" in resp.get_json()
    resp = client.post("/api/recommend", data="[1,2,3]", content_type="application/json")
    assert resp.status_code == 400 and resp.is_json
    resp = client.post("/api/recommend")
    assert resp.status_code == 400 and resp.is_json


def test_recommend_on_finished_game_returns_400(client):
    full = {str(c): 0 for c in range(13)}
    resp = post(client, "/api/recommend", {"dice": [1, 2, 3, 4, 5], "rolls_remaining": 2, "scores": full})
    assert resp.status_code == 400 and "error" in resp.get_json()


def test_404_and_405_are_json(client):
    resp = client.get("/api/does_not_exist")
    assert resp.status_code == 404 and resp.is_json and "error" in resp.get_json()
    resp = client.get("/api/recommend")
    assert resp.status_code == 405 and resp.is_json and "error" in resp.get_json()


# ------------------------------------------------------------------------------------------
# /api/score_options
# ------------------------------------------------------------------------------------------
def test_score_options_fresh(client):
    resp = post(client, "/api/score_options", {"dice": [1, 2, 3, 4, 5]})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["joker_rule"] is None
    opts = data["options"]
    assert len(opts) == 13
    assert all(o["legal"] for o in opts)
    by_cat = {o["category"]: o for o in opts}
    assert by_cat[10]["points"] == 40 and by_cat[9]["points"] == 30 and by_cat[12]["points"] == 15
    assert set(opts[0]) == {"category", "name", "points", "legal", "is_forced"}


def test_score_options_joker_forced(client):
    resp = post(client, "/api/score_options", {"dice": [4, 4, 4, 4, 4], "scores": {"11": 50}})
    data = resp.get_json()
    assert data["joker_rule"] == "forced_upper"
    legal = [o for o in data["options"] if o["legal"]]
    assert [o["category"] for o in legal] == [3]
    assert legal[0]["is_forced"] is True and legal[0]["points"] == 20
    assert data["joker_bonus"] == 100


def test_score_options_joker_lower_only(client):
    resp = post(client, "/api/score_options",
                {"dice": [4, 4, 4, 4, 4], "scores": {"11": 50, "3": 12}, "yahtzee_status": 2})
    data = resp.get_json()
    assert data["joker_rule"] == "lower_only"
    by_cat = {o["category"]: o for o in data["options"]}
    assert not by_cat[3]["legal"] and not by_cat[11]["legal"]
    assert all(not by_cat[c]["legal"] for c in range(6))
    assert by_cat[10]["legal"] and by_cat[10]["points"] == 40
    assert by_cat[8]["legal"] and by_cat[8]["points"] == 25


def test_score_options_invalid(client):
    assert post(client, "/api/score_options", {"dice": [0, 1, 2, 3, 4]}).status_code == 400
    assert post(client, "/api/score_options", {"dice": [1, 1, 1, 1, 1], "scores": {"3": 7}}).status_code == 400


# ------------------------------------------------------------------------------------------
# /api/game_ev and /api/modes
# ------------------------------------------------------------------------------------------
def test_game_ev_fresh(client):
    resp = post(client, "/api/game_ev", {"scores": {}, "yahtzee_status": 0})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ev_remaining"] == pytest.approx(FRESH_EV, abs=0.005)
    assert data["std"] == pytest.approx(FRESH_STD, abs=0.005)
    assert data["fresh_ev"] == pytest.approx(FRESH_EV, abs=0.005)
    assert data["mask"] == 0 and data["upper"] == 0 and data["upper_raw"] == 0
    assert data["categories_filled"] == 0 and data["categories_remaining"] == 13
    assert data["mode"] == "joker" and data["rules"] == "hasbro"
    assert data["yahtzee_status"] == 0


def test_game_ev_tracks_scorecard(client):
    resp = post(client, "/api/game_ev", {"scores": {"11": 50, "5": 30}})
    data = resp.get_json()
    assert data["yahtzee_status"] == 2
    assert data["categories_filled"] == 2 and data["categories_remaining"] == 11
    assert data["upper"] == 30
    st = app_module.parse_scorecard({"11": 50, "5": 30})
    assert data["ev_remaining"] == pytest.approx(SOLVER.ev(st.mask, st.upper, st.yb), abs=0.005)


def test_game_ev_invalid(client):
    assert post(client, "/api/game_ev", {"scores": {"0": 7}}).status_code == 400
    assert client.post("/api/game_ev", data="x", content_type="application/json").status_code == 400


def test_modes(client):
    data = client.get("/api/modes").get_json()
    assert data["default"] == "joker"
    assert data["modes"][0]["id"] == "joker"
    assert "Hasbro" in data["modes"][0]["description"]
    assert "100" in data["modes"][0]["description"]


# ------------------------------------------------------------------------------------------
# /api/win_probability
# ------------------------------------------------------------------------------------------
def test_win_probability_symmetric_fresh(client):
    resp = post(client, "/api/win_probability", {"player1_scores": {}, "player2_scores": {}})
    assert resp.status_code == 200
    data = resp.get_json()
    p1, p2 = data["player1"], data["player2"]
    assert p1["win_probability"] == 50.0 and p2["win_probability"] == 50.0
    assert p1["win_probability"] + p2["win_probability"] + data["tie_probability"] == pytest.approx(100.0)
    assert p1["expected_final"] == pytest.approx(FRESH_EV, abs=0.005)
    assert p1["current_score"] == 0 and p1["ev_remaining"] == pytest.approx(FRESH_EV, abs=0.005)
    assert p1["std"] == pytest.approx(FRESH_STD, abs=0.005)
    assert p1["categories_remaining"] == 13
    assert data["approximation"]["method"] == "normal_exact_moments"
    assert data["approximation"]["exact_feasible"] is False
    assert data["approximation"]["suggest_exact"] is False
    assert isinstance(data["approximation"]["reasons"], list)


def test_win_probability_symmetric_midgame_with_bonuses(client):
    body = {
        "player1_scores": OPEN_7, "player2_scores": OPEN_7,
        "player1_yahtzee_status": 0, "player2_yahtzee_status": 0,
        "player1_yahtzee_bonuses": 0, "player2_yahtzee_bonuses": 0,
    }
    data = post(client, "/api/win_probability", body).get_json()
    assert data["player1"]["win_probability"] == 50.0
    assert data["player2"]["win_probability"] == 50.0
    assert data["approximation"]["exact_feasible"] is True
    assert data["approximation"]["suggest_exact"] is True


def test_win_probability_upper_63_no_double_bonus(client):
    data = post(client, "/api/win_probability", {"player1_scores": UPPER_63, "player2_scores": {}}).get_json()
    p1 = data["player1"]
    st = app_module.parse_scorecard(UPPER_63)
    ev = SOLVER.ev(st.mask, st.upper, st.yb)
    assert st.upper_raw == 63
    assert p1["current_score"] == 63 + 35
    assert p1["upper_bonus_earned"] == 35
    assert p1["ev_remaining"] == pytest.approx(ev - 35, abs=0.005)
    assert p1["expected_final"] == pytest.approx(p1["current_score"] + p1["ev_remaining"], abs=1e-9)
    assert p1["expected_final"] == pytest.approx(63 + ev, abs=0.005)


def test_win_probability_yahtzee_bonus_chips_counted_once(client):
    scores = {"11": 50, "5": 30, "4": 25}         # two boxes filled after the Yahtzee box: room for 2 chips
    body = {"player1_scores": scores, "player2_scores": {}, "player1_yahtzee_status": 2,
            "player1_yahtzee_bonuses": 2}
    data = post(client, "/api/win_probability", body).get_json()
    p1 = data["player1"]
    st = app_module.parse_scorecard(scores)
    assert p1["bonus_points"] == 200 and p1["yahtzee_bonuses"] == 2
    assert p1["current_score"] == 105 + 200
    assert p1["expected_final"] == pytest.approx(305 + SOLVER.ev(st.mask, st.upper, st.yb), abs=0.005)
    assert p1["win_probability"] > data["player2"]["win_probability"]


def test_win_probability_rejects_impossible_bonus_chips(client):
    for scores, chips in (({}, 1), ({"11": 0, "3": 12}, 1), ({"11": 50}, 1), ({"11": 50, "3": 12}, 2)):
        body = {"player1_scores": scores, "player2_scores": {}, "player1_yahtzee_bonuses": chips}
        resp = post(client, "/api/win_probability", body)
        assert resp.status_code == 400 and "error" in resp.get_json(), (scores, chips)
    ok = post(client, "/api/win_probability", {"player1_scores": {"11": 50, "3": 12}, "player2_scores": {},
                                                "player1_yahtzee_bonuses": 1})
    assert ok.status_code == 200
    missing = post(client, "/api/win_probability", {"player1_scores": {}})
    assert missing.status_code == 400
    alive = post(client, "/api/win_probability", {
        "player1_scores": {"1": 8, "2": 15, "3": 20, "4": 15, "5": 0, "6": 30, "7": 30, "8": 25, "9": 30, "10": 40, "12": 30, "11": 0},
        "player2_scores": {"1": 8, "2": 15, "3": 20, "4": 20, "5": 0, "6": 30, "7": 30, "8": 25, "9": 30, "10": 40, "12": 30, "11": 0},
    }).get_json()
    assert alive["player1"]["eliminated"] is False and alive["player1"]["win_probability"] > 0.0


def test_win_probability_elimination(client):
    # player 2 has only Ones open (max 5 more) and a scratched Yahtzee; player 1 already has 30
    p2 = {str(c): 0 for c in range(1, 13)}
    data = post(client, "/api/win_probability", {"player1_scores": {"12": 30}, "player2_scores": p2}).get_json()
    assert data["player1"]["win_probability"] == 100.0
    assert data["player2"]["win_probability"] == 0.0
    assert data["player2"]["eliminated"] is True
    assert data["player1"]["eliminated"] is False


def test_win_probability_finished_game(client):
    full_a = {str(c): 0 for c in range(13)}
    full_a["12"] = 20
    full_b = {str(c): 0 for c in range(13)}
    full_b["12"] = 10
    data = post(client, "/api/win_probability", {"player1_scores": full_a, "player2_scores": full_b}).get_json()
    assert data["player1"]["win_probability"] == 100.0
    assert data["player2"]["win_probability"] == 0.0
    assert data["player1"]["ev_remaining"] == 0 and data["player1"]["std"] == 0
    data = post(client, "/api/win_probability", {"player1_scores": full_a, "player2_scores": full_a}).get_json()
    assert data["tie_probability"] == 100.0


def test_win_probability_invalid(client):
    resp = post(client, "/api/win_probability", {"player1_scores": {"0": 6}, "player2_scores": {}})
    assert resp.status_code == 400 and "error" in resp.get_json()
    resp = post(client, "/api/win_probability", {"player1_scores": {}, "player2_scores": {},
                                                 "player1_yahtzee_bonuses": 99})
    assert resp.status_code == 400


# ------------------------------------------------------------------------------------------
# /api/win_probability_exact
# ------------------------------------------------------------------------------------------
@pytest.mark.parametrize("scores,n_open", [(OPEN_4, 4), (OPEN_7, 7)])
def test_win_probability_exact_identical_players(client, scores, n_open):
    body = {"player1_scores": scores, "player2_scores": scores}
    resp = post(client, "/api/win_probability_exact", body)
    assert resp.status_code == 200, resp.get_json()
    data = resp.get_json()
    assert data["feasible"] is True
    assert data["method"] == "exact_pmf"
    p1, p2 = data["player1"], data["player2"]
    assert p1["categories_remaining"] == n_open == p2["categories_remaining"]
    assert p1["win_probability"] == p2["win_probability"]
    assert p1["win_probability"] + p2["win_probability"] + data["tie_probability"] == pytest.approx(100.0, abs=0.02)
    assert data["tie_probability"] > 0
    # distribution summary is of the final score and agrees with the solver's moments
    st = app_module.parse_scorecard(scores)
    assert p1["mean"] == pytest.approx(st.locked + SOLVER.ev(st.mask, st.upper, st.yb), abs=0.01)
    assert p1["std"] == pytest.approx(SOLVER.std(st.mask, st.upper, st.yb), abs=0.01)
    assert p1["p10"] <= p1["p50"] <= p1["p90"]
    assert p1["current_score"] == 63 + 35 + sum(v for k, v in scores.items() if int(k) >= 6)
    # the exact mean matches the approximation endpoint's expected final
    approx = post(client, "/api/win_probability", body).get_json()
    assert p1["mean"] == pytest.approx(approx["player1"]["expected_final"], abs=0.01)


def test_win_probability_exact_asymmetric(client):
    leader = dict(OPEN_4, **{"12": 30})          # 3 open, 30 more banked
    body = {"player1_scores": leader, "player2_scores": OPEN_4}
    data = post(client, "/api/win_probability_exact", body).get_json()
    assert data["player1"]["win_probability"] > data["player2"]["win_probability"]
    total = data["player1"]["win_probability"] + data["player2"]["win_probability"] + data["tie_probability"]
    assert total == pytest.approx(100.0, abs=0.02)


def test_win_probability_exact_with_yahtzee_bonus_chips(client):
    scores = dict(OPEN_4, **{"11": 50})          # 3 open, Yahtzee box holds 50
    body = {"player1_scores": scores, "player2_scores": scores,
            "player1_yahtzee_bonuses": 1, "player2_yahtzee_bonuses": 0}
    data = post(client, "/api/win_probability_exact", body).get_json()
    assert data["player1"]["current_score"] == data["player2"]["current_score"] + 100
    assert data["player1"]["mean"] == pytest.approx(data["player2"]["mean"] + 100, abs=0.01)
    assert data["player1"]["win_probability"] > 90


def test_win_probability_exact_too_many_open(client):
    body = {"player1_scores": OPEN_8, "player2_scores": OPEN_4}
    resp = post(client, "/api/win_probability_exact", body)
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["feasible"] is False
    assert str(CAP) in data["error"]
    assert data["max_open_for_exact"] == CAP


def test_win_probability_exact_invalid(client):
    resp = post(client, "/api/win_probability_exact", {"player1_scores": {"11": 25}, "player2_scores": OPEN_4})
    assert resp.status_code == 400 and "error" in resp.get_json()


# ------------------------------------------------------------------------------------------
# /api/save_game, /api/game_history, /api/game_details, /api/article
# ------------------------------------------------------------------------------------------
def test_save_game_oversized_returns_400(client):
    payload = {"turns": [], "padding": "x" * (app_module.MAX_SAVE_BYTES + 1)}
    resp = post(client, "/api/save_game", payload)
    assert resp.status_code == 400
    assert "error" in resp.get_json()


def test_save_game_rejects_non_object(client):
    resp = client.post("/api/save_game", data="[1, 2, 3]", content_type="application/json")
    assert resp.status_code == 400 and "error" in resp.get_json()
    resp = client.post("/api/save_game", data="nope", content_type="application/json")
    assert resp.status_code == 400 and "error" in resp.get_json()


def test_save_game_rejects_bad_shapes_and_never_damages_history(client, tmp_path, monkeypatch):
    path = tmp_path / "games.json"
    monkeypatch.setattr(app_module, "GAME_RESULTS_FILE", str(path))
    good = {"timestamp": "2026-09-02T00:00:00", "player1_score": 1, "player2_score": 2, "winner": 2,
            "turns": [], "stats": {}}
    assert post(client, "/api/save_game", good).status_code == 200
    before = path.read_text()
    deep = '{"x":' + '[' * 5000 + ']' * 5000 + '}'          # under the size cap, far over the depth cap
    resp = client.post("/api/save_game", data=deep, content_type="application/json")
    assert resp.status_code == 400 and "error" in resp.get_json()
    assert post(client, "/api/save_game", {"turns": 5}).status_code == 400
    assert post(client, "/api/save_game", {"turns": None, "stats": []}).status_code == 400
    assert post(client, "/api/save_game", {"turns": [], "winner": True}).status_code == 400
    assert path.read_text() == before
    hist = client.get("/api/game_history").get_json()
    assert len(hist) == 1 and hist[0]["total_turns"] == 0 and hist[0]["game_id"] == 1
    path.write_text("{not json")                              # a damaged file is reported, never overwritten
    assert client.get("/api/game_history").status_code == 500
    assert post(client, "/api/save_game", good).status_code == 500
    assert path.read_text() == "{not json"


def test_save_game_round_trip(client, tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "GAME_RESULTS_FILE", str(tmp_path / "games.json"))
    game = {"timestamp": "2026-09-01T00:00:00", "player1_score": 250, "player2_score": 200,
            "winner": 1, "turns": [{"turn": 1}], "stats": {"x": 1}}
    resp = post(client, "/api/save_game", game)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True and data["game_id"] == 1 and data["total_games"] == 1

    history = client.get("/api/game_history").get_json()
    assert len(history) == 1
    assert history[0]["game_id"] == 1 and history[0]["total_turns"] == 1
    assert history[0]["player1_score"] == 250

    details = client.get("/api/game_details/1").get_json()
    assert details["winner"] == 1 and details["turns"] == [{"turn": 1}]
    resp = client.get("/api/game_details/999")
    assert resp.status_code == 404 and "error" in resp.get_json()


def test_article(client):
    resp = client.get("/api/article")
    assert resp.status_code == 200
    assert "<h1>" in resp.get_json()["html"] or "<p>" in resp.get_json()["html"]
