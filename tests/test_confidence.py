"""Decision confidence and the Monte Carlo sanity check: engine, API and CLI."""
import json
import os
import subprocess
import sys

import pytest

from dice import dice_list_to_counts, roll_id
from engine import FULL_MASK, confidence_label, parse_scorecard

TIE_CARD = {0: 3, 1: 6, 2: 9, 3: 12, 4: 15, 5: 18, 6: 20, 7: 20, 8: 25, 10: 40, 11: 50}   # SS and Chance open


def rid(dice):
    return roll_id(dice_list_to_counts(dice))


def state(scores):
    return parse_scorecard({str(k): v for k, v in scores.items()})


def test_confidence_label_bands():
    assert confidence_label(None) == ("forced", "Forced: only one legal play")
    assert confidence_label(5.0)[0] == "clear" and confidence_label(3.0)[0] == "clear"
    assert confidence_label(1.5)[0] == "solid" and confidence_label(0.5)[0] == "close"
    assert confidence_label(0.0)[0] == "toss-up" and confidence_label(0.24)[0] == "toss-up"


def test_fresh_large_straight_is_a_clear_stand_pat(solver_hasbro):
    r = solver_hasbro.decision_report(0, 0, 0, rid([1, 2, 3, 4, 5]), 2)
    assert r["decision"] == "keep" and r["best"] == "stand pat" and r["label"] == "clear" and r["gap"] > 3
    assert r["solved"] == "exact" and r["exact_tie"] is False
    losses = [a["loss"] for a in r["alternatives"]]
    assert losses == sorted(losses) and losses[0] == pytest.approx(r["gap"])


def test_classic_opening_is_a_toss_up(solver_hasbro):
    r = solver_hasbro.decision_report(0, 0, 0, rid([1, 1, 3, 5, 6]), 2)
    assert r["best"] == "keep 5" and r["runner_up"] == "keep 6"
    assert r["label"] in ("toss-up", "close") and r["near_ties"] >= 1 and 0 < r["gap"] < 0.25


def test_forced_joker_reports_forced(solver_hasbro):
    st = state({11: 50})
    r = solver_hasbro.decision_report(st.mask, st.upper, st.yb, rid([3, 3, 3, 3, 3]), 0)
    assert r["label"] == "forced" and r["gap"] is None and r["runner_up"] is None and r["best"] == "score Threes"


def test_exact_tie_is_flagged_and_broken_toward_standing_pat(solver_hasbro):
    st = state(TIE_CARD)
    r = solver_hasbro.decision_report(st.mask, st.upper, st.yb, rid([1, 2, 3, 4, 4]), 2)
    assert r["exact_tie"] is True and r["label"] == "toss-up" and r["best"] == "stand pat"
    assert "tie" in r["tie_note"].lower() and r["gap"] == pytest.approx(0.0, abs=1e-9)


def test_box_decision_report(solver_hasbro):
    r = solver_hasbro.decision_report(0, 0, 0, rid([2, 2, 3, 3, 6]), 0)
    assert r["decision"] == "box" and r["best"].startswith("score ") and r["runner_up"].startswith("score ")
    assert r["gap"] > 0 and r["outcome_std"] > 0


def test_simulate_fresh_game_matches_table(solver_hasbro):
    r = solver_hasbro.simulate(0, 0, 0, games=3000, seed=123)
    assert r["games"] == 3000 and abs(r["z"]) < 4
    assert abs(r["std"] - r["table_std"]) < 0.06 * r["table_std"]
    assert r["p5"] < r["p50"] < r["p95"] and r["min"] >= 0


def test_simulate_end_game_and_edge_arguments(solver_hasbro):
    st = state({**TIE_CARD, 12: 20})                     # only Small Straight open, Yahtzee box holds 50
    r = solver_hasbro.simulate(st.mask, st.upper, st.yb, games=4000, seed=5)
    assert abs(r["mean"] - r["table_ev"]) < 4 * r["se"] + 1e-9
    full = solver_hasbro.simulate(FULL_MASK, 63, 0, games=3, seed=0)
    assert full["mean"] == 35 and full["std"] == 0
    one = solver_hasbro.simulate(0, 0, 0, games=1, seed=1)
    assert one["games"] == 1 and one["se"] != one["se"]   # a single game has no standard error (NaN)
    with pytest.raises(ValueError):
        solver_hasbro.simulate(0, 0, 0, games=0)
    with pytest.raises(ValueError):
        solver_hasbro.simulate(0, 0, 1, games=10)         # yb=1 with the Yahtzee box open is not a state


def test_simulate_is_reproducible_with_a_seed(solver_hasbro):
    a = solver_hasbro.simulate(0, 0, 0, games=200, seed=9)
    b = solver_hasbro.simulate(0, 0, 0, games=200, seed=9)
    assert a["mean"] == b["mean"] and a["std"] == b["std"]


@pytest.fixture(scope="module")
def client():
    import app as app_module
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as c:
        yield c


def test_api_recommend_carries_confidence(client):
    data = client.post("/api/recommend", json={"dice": [1, 2, 3, 4, 5], "rolls_remaining": 2, "scores": {}}).get_json()
    c = data["confidence"]
    assert c["label"] == "clear" and c["best"] == "stand pat" and c["solved"] == "exact"
    forced = client.post("/api/recommend", json={"dice": [3, 3, 3, 3, 3], "rolls_remaining": 0, "scores": {"11": 50}}).get_json()
    assert forced["confidence"]["label"] == "forced"


def test_api_simulate(client):
    data = client.post("/api/simulate", json={"scores": {"11": 50, "3": 12}, "games": 300, "seed": 3}).get_json()
    assert data["games"] == 300 and "verdict" in data and abs(data["z"]) < 5 and data["categories_remaining"] == 11
    assert client.post("/api/simulate", json={"scores": {}, "games": 5000}).status_code == 400
    assert client.post("/api/simulate", json={"scores": {}, "games": 0}).status_code == 400
    assert client.post("/api/simulate", json={"scores": {str(c): 0 for c in range(13)}}).status_code == 400
    default = client.post("/api/simulate", json={"scores": {}}).get_json()
    assert default["games"] == 500


def test_api_win_probability_confidence(client):
    data = client.post("/api/win_probability", json={"player1_scores": {}, "player2_scores": {}}).get_json()
    assert data["confidence"]["label"] == "approximate" and "within" in data["confidence"]["headline"]
    end = {str(c): v for c, v in TIE_CARD.items()}
    exact = client.post("/api/win_probability_exact", json={"player1_scores": end, "player2_scores": end}).get_json()
    assert exact["confidence"]["label"] == "exact"


def test_cli_simulate_and_confidence_line():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def run(*args):
        return subprocess.run([sys.executable, "-W", "ignore", "cli.py", *args], cwd=root, capture_output=True, text=True)

    out = run("--json", "simulate", "--scores", '{"11":50,"3":12}', "--games", "300", "--seed", "1")
    d = json.loads(out.stdout)
    assert out.returncode == 0 and d["ok"] is True and d["games"] == 300 and "table_ev" in d and "state" in d
    out = run("recommend", "--dice", "1,1,3,5,6", "--rolls", "2")
    assert out.returncode == 0 and "Confidence:" in out.stdout and "keep 6" in out.stdout
    out = run("simulate", "--games", "0")
    assert out.returncode == 2 and "games must be between" in out.stderr
