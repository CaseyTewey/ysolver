"""Win probability: exact when cheap, calibrated approximation otherwise; small engine guards."""
import pytest

from engine import FULL_MASK

TIE_CARD = {"0": 3, "1": 6, "2": 9, "3": 12, "4": 15, "5": 18, "6": 20, "7": 20, "8": 25, "10": 40, "11": 50}


@pytest.fixture(scope="module")
def client():
    import app as app_module
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as c:
        yield c


def test_finished_tied_game_is_a_certain_tie(client):
    zeros = {str(c): 0 for c in range(13)}
    d = client.post("/api/win_probability", json={"player1_scores": zeros, "player2_scores": zeros}).get_json()
    assert d["player1"]["win_probability"] == 0.0 and d["player2"]["win_probability"] == 0.0
    assert d["tie_probability"] == 100.0 and d["method"] == "exact_pmf"
    assert d["approximation"]["exact_used"] is True and d["confidence"]["label"] == "exact"
    assert "tie 100.0%" in d["confidence"]["headline"]


def test_exact_used_automatically_late_and_matches_exact_endpoint(client):
    other = dict(TIE_CARD, **{"9": 0})                       # only Chance open
    body = {"player1_scores": TIE_CARD, "player2_scores": other}
    d = client.post("/api/win_probability", json=body).get_json()
    e = client.post("/api/win_probability_exact", json=body).get_json()
    assert d["method"] == "exact_pmf" and d["approximation"]["suggest_exact"] is False
    assert abs(d["player1"]["win_probability"] - e["player1"]["win_probability"]) <= 0.06
    assert abs(d["tie_probability"] - e["tie_probability"]) <= 0.06
    total = d["player1"]["win_probability"] + d["player2"]["win_probability"] + d["tie_probability"]
    assert abs(total - 100.0) <= 0.2


def test_seven_open_stays_approximate_with_exact_offered(client):
    six_filled = {"0": 3, "1": 6, "2": 9, "3": 12, "4": 15, "5": 18}
    d = client.post("/api/win_probability", json={"player1_scores": six_filled, "player2_scores": six_filled}).get_json()
    a = d["approximation"]
    assert d["method"] == "normal_exact_moments" and a["exact_feasible"] is True
    assert a["suggest_exact"] is True and a["exact_used"] is False and a["has_edge_case"] is True
    assert "within 7 points" in a["reasons"][0] and d["confidence"]["label"] == "approximate"
    assert d["player1"]["win_probability"] == d["player2"]["win_probability"] == 50.0


def test_fresh_game_has_no_warning_but_states_its_band(client):
    d = client.post("/api/win_probability", json={"player1_scores": {}, "player2_scores": {}}).get_json()
    a = d["approximation"]
    assert a["has_edge_case"] is False and a["exact_feasible"] is False and a["exact_used"] is False
    assert d["confidence"]["headline"] == "Approximate, usually within 5 points"
    assert d["confidence"]["worst_error_pts"] == 8


def test_cannot_win_case_is_zero_with_exact(client):
    p1 = {str(c): v for c, v in {0: 3, 2: 9, 3: 12, 4: 15, 5: 18, 6: 20, 7: 20, 8: 25, 9: 30, 10: 40, 11: 0, 12: 22}.items()}
    p2 = {str(c): v for c, v in {1: 6, 2: 9, 3: 12, 4: 15, 5: 18, 6: 25, 7: 25, 8: 25, 9: 30, 10: 40, 11: 50}.items()}
    d = client.post("/api/win_probability", json={"player1_scores": p1, "player2_scores": p2}).get_json()
    assert d["method"] == "exact_pmf"
    assert d["player1"]["win_probability"] + d["player2"]["win_probability"] + d["tie_probability"] == pytest.approx(100.0, abs=0.2)
    assert d["player1"]["win_probability"] >= 0.0 and d["player2"]["win_probability"] >= 0.0


def test_score_options_zero_points_for_illegal_boxes(client):
    d = client.post("/api/score_options", json={"dice": [5, 5, 5, 5, 5], "scores": {"11": 50}}).get_json()
    assert d["joker_rule"] == "forced_upper"
    assert all(o["points"] == 0 for o in d["options"] if not o["legal"])
    assert any(o["legal"] and o["is_forced"] and o["category"] == 4 and o["points"] == 25 for o in d["options"])


def test_engine_guards(solver_hasbro):
    with pytest.raises(ValueError):
        solver_hasbro.best_category(FULL_MASK, 63, 0, 0)
    with pytest.raises(ValueError):
        solver_hasbro.options(0, 0, 1, 0)
    with pytest.raises(ValueError):
        solver_hasbro.recommend([1, 2, 3, 4, 5], 0, 0, 7, 2)
