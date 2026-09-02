"""cli.py: drive the command line front end in-process through cli.main(argv).

Every test calls cli.main with an argv list and inspects the captured stdout / stderr and the
return code, exactly as a shell would see them. One test runs the real interpreter as a
subprocess to confirm the piped-stdin behaviour of interactive mode outside pytest's capture.
"""
import io
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

import cli
from distribution import MAX_OPEN_FOR_EXACT
from engine import PLAIN, Solver, parse_scorecard

ROOT = Path(__file__).resolve().parents[1]

# fresh-game numbers per rule set: (expected final, std)
FRESH = {
    "hasbro": (254.587729, 59.6076),
    "verhoeff": (254.589609, 59.6114),
    "plain": (245.870775, 39.8201),
}

# scorecards used throughout (box index -> points)
CARD_3OPEN_BONUS = {"0": 3, "1": 6, "2": 9, "3": 12, "4": 15, "5": 18,
                    "6": 20, "7": 21, "8": 25, "9": 30}          # upper 63, LS / Yahtzee / Chance open
CARD_3OPEN_NOBONUS = dict(CARD_3OPEN_BONUS, **{"5": 6})          # upper 51, same open boxes
CARD_2OPEN_Y50 = dict(CARD_3OPEN_BONUS, **{"11": 50})            # Yahtzee scored: chips are possible; LS / Chance open
CARD_5OPEN = {"0": 3, "1": 6, "2": 9, "3": 12, "4": 15, "5": 18, "6": 20, "7": 21}
CARD_5OPEN_Y = {"0": 3, "1": 6, "2": 9, "3": 12, "4": 15, "5": 18, "6": 20, "11": 50}
CARD_DONE = dict(CARD_3OPEN_BONUS, **{"10": 40, "11": 50, "12": 22})   # 271 + 35 bonus = 306


def js(card: dict) -> str:
    return json.dumps(card)


def state_of(card: dict):
    return parse_scorecard({int(k): v for k, v in card.items()})


@pytest.fixture
def run(capsys, monkeypatch):
    """run(*argv, stdin='') -> (return code, stdout, stderr), with argparse's SystemExit folded in."""
    def _run(*argv, stdin: str = ""):
        monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))
        capsys.readouterr()
        try:
            rc = cli.main(list(argv))
        except SystemExit as e:
            rc = e.code if isinstance(e.code, int) else 2
        out, err = capsys.readouterr()
        return rc, out, err
    return _run


def ok_json(out: str) -> dict:
    data = json.loads(out)
    assert data["ok"] is True
    return data


def table_rows(out: str) -> list:
    """Rows of the box table that follows the 'Box  Pts  Exp. final' header."""
    tail = out.split("Exp. final", 1)[1]
    return [l for l in tail.splitlines() if l.strip() and not l.startswith("  ...")]


# --------------------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------------------
def test_main_is_callable_with_argv():
    assert callable(cli.main)
    assert cli.main.__code__.co_varnames[:1] == ("argv",)


def test_no_command_prints_help_and_exits_2(run):
    rc, out, err = run()
    assert rc == 2
    assert "usage:" in out and "recommend" in out and "interactive" in out


# --------------------------------------------------------------------------------------
# ev
# --------------------------------------------------------------------------------------
def test_ev_fresh_game_text(run):
    rc, out, err = run("ev")
    assert rc == 0 and err == ""
    assert out.startswith("Rules: hasbro (official Hasbro rules")
    assert "13 boxes open (Ones, Twos, Threes, Fours, Fives, Sixes" in out
    assert "expected remaining 254.59 (std 59.61)    expected final 254.59" in out
    assert "Fresh game: expected final 254.587729, std 59.6076" in out


def test_ev_fresh_game_json(run, solver_hasbro):
    rc, out, err = run("--json", "ev")
    assert rc == 0 and err == ""
    d = ok_json(out)
    assert abs(d["ev_remaining"] - 254.587729) < 1e-6
    assert abs(d["std_remaining"] - 59.6076) < 1e-4
    assert d["ev_remaining"] == solver_hasbro.fresh_ev
    assert d["fresh_game_ev"] == d["ev_remaining"] == d["expected_final"]
    assert d["fresh_game_std"] == d["std_remaining"]
    assert d["boxes_open"] == 13 and len(d["open_boxes"]) == 13
    assert d["locked"] == 0 and d["current_total"] == 0 and d["upper_bonus_earned"] == 0
    assert d["yahtzee_status"] == "open" and d["game_over"] is False and d["rules"] == "hasbro"


@pytest.mark.parametrize("rules", sorted(FRESH))
def test_rules_presets_change_the_fresh_ev(run, rules):
    ev, std = FRESH[rules]
    rc, out, err = run("--rules", rules, "--json", "ev")
    assert rc == 0
    d = ok_json(out)
    assert d["rules"] == rules
    assert abs(d["ev_remaining"] - ev) < 1e-4
    assert abs(d["std_remaining"] - std) < 1e-4
    assert abs(d["fresh_game_ev"] - ev) < 1e-4
    # the same flags are accepted after the subcommand
    rc2, out2, _ = run("ev", "--rules", rules, "--json")
    assert rc2 == 0 and json.loads(out2)["ev_remaining"] == d["ev_remaining"]
    # and the human view rounds the same number
    rc3, out3, _ = run("--rules", rules, "ev")
    assert rc3 == 0 and f"expected remaining {ev:.2f} (std {std:.2f})" in out3


def test_ev_scorecard_accounting_with_bonus_and_chips(run, solver_hasbro):
    st = state_of(CARD_2OPEN_Y50)
    ev = solver_hasbro.ev(st.mask, st.upper, st.yb)
    rc, out, err = run("--json", "ev", "--scores", js(CARD_2OPEN_Y50), "--bonuses", "2")
    assert rc == 0
    d = ok_json(out)
    assert d["boxes_open"] == 2 and d["open_boxes"] == ["Large Straight", "Chance"]
    assert d["locked"] == 209 and d["upper_subtotal"] == 63 and d["upper_bonus_earned"] == 35
    assert d["yahtzee_bonus_chips"] == 2 and d["yahtzee_bonus_points"] == 200
    assert d["current_total"] == 209 + 35 + 200
    assert abs(d["ev_remaining"] - ev) < 1e-12
    assert abs(d["ev_remaining_after_earned_bonus"] - (ev - 35)) < 1e-12
    assert abs(d["expected_final"] - (209 + 200 + ev)) < 1e-12
    # text view: score so far + remaining (35 removed) = expected final
    rc, out, _ = run("ev", "--scores", js(CARD_2OPEN_Y50), "--bonuses", "2")
    assert rc == 0
    assert "Upper subtotal 63/63 (35 bonus earned)" in out and "bonus chips: 2" in out
    m = re.search(r"Score so far (\d+)\s+expected remaining ([\d.]+) \(std ([\d.]+)\)\s+expected final ([\d.]+)", out)
    assert m, out
    assert int(m.group(1)) == 444
    assert abs(float(m.group(2)) - (ev - 35)) < 0.006
    assert abs(float(m.group(4)) - (209 + 200 + ev)) < 0.006
    # chips are impossible while the Yahtzee box is open
    rc, out, err = run("ev", "--scores", js(CARD_3OPEN_BONUS), "--bonuses", "2")
    assert rc == 2 and "Yahtzee bonus chips need a Yahtzee box holding 50" in err


def test_ev_accepts_box_names_and_aliases(run):
    rc, out, err = run("--json", "ev", "--scores", '{"yahtzee": 50, "Sixes": 18, "3k": 25, "full house": null}')
    assert rc == 0
    d = ok_json(out)
    assert d["boxes_open"] == 10
    assert "Yahtzee" not in d["open_boxes"] and "Sixes" not in d["open_boxes"] and "Three of a Kind" not in d["open_boxes"]
    assert "Full House" in d["open_boxes"]           # null means open
    assert d["locked"] == 93 and d["yahtzee_status"] == "scored 50"


def test_ev_game_over(run):
    rc, out, err = run("ev", "--scores", js(CARD_DONE))
    assert rc == 0
    assert "0 boxes open (none)" in out and "Game over. Final total 306" in out
    rc, out, _ = run("--json", "ev", "--scores", js(CARD_DONE))
    d = ok_json(out)
    assert d["game_over"] is True and d["current_total"] == 306 and d["ev_remaining"] == 35.0


# --------------------------------------------------------------------------------------
# recommend
# --------------------------------------------------------------------------------------
def test_recommend_large_straight_stands_pat_text(run):
    rc, out, err = run("recommend", "--dice", "1,2,3,4,5", "--rolls", "2")
    assert rc == 0 and err == ""
    assert "Dice 1 2 3 4 5    rolls left 2" in out
    assert "STOP ROLLING and score Large Straight for 40 points" in out
    assert "expected final 261.53" in out
    rows = table_rows(out)
    assert len(rows) == 13
    assert rows[0].startswith("* Large Straight") and rows[0].rstrip().endswith("261.53")
    assert rows[1].startswith("  Small Straight") and rows[1].rstrip().endswith("246.56")


def test_recommend_large_straight_json(run, solver_hasbro):
    rc, out, err = run("--json", "recommend", "--dice", "1,2,3,4,5", "--rolls", "2")
    assert rc == 0
    d = ok_json(out)
    assert d["action"] == "keep" and d["keep_all"] is True and d["keep_dice"] == [1, 2, 3, 4, 5]
    assert d["rolls_remaining"] == 2 and d["is_yahtzee_roll"] is False and d["joker_rule"] is None
    assert abs(d["expected_final"] - 261.53) < 0.005
    assert d["expected_final"] == d["expected_value"]                # nothing locked yet
    assert abs(d["expected_value"] - (40 + solver_hasbro.ev(1 << 10, 0, 0))) < 1e-9
    best = d["category_options"][0]
    assert best["name"] == "Large Straight" and best["points"] == 40 and best["bonus"] == 0
    assert abs(best["expected_value"] - d["expected_value"]) < 1e-9
    assert abs(d["keep_expected_value"] - d["expected_value"]) < 1e-9
    assert d["state"]["boxes_open"] == 13 and d["joker_note"] is None


@pytest.mark.parametrize("dice", ["12345", "1 2 3 4 5", "5,4,3,2,1", "1, 2, 3, 4, 5"])
def test_recommend_accepts_other_dice_spellings(run, dice):
    rc, out, _ = run("--json", "recommend", "--dice", dice, "--rolls", "2")
    assert rc == 0
    d = ok_json(out)
    assert sorted(d["dice"]) == [1, 2, 3, 4, 5]
    assert abs(d["expected_final"] - 261.5314) < 1e-3


def test_recommend_forced_fours_with_bonus_text(run):
    rc, out, err = run("recommend", "--dice", "4,4,4,4,4", "--rolls", "0", "--scores", '{"11":50}')
    assert rc == 0 and err == ""
    assert "Yahtzee box: scored 50" in out
    assert "SCORE Fours for 20 points (+100 bonus)" in out
    assert "expected final 433.07" in out
    assert "+100 Yahtzee bonus (the Yahtzee box holds 50)" in out
    assert "matching upper box (Fours) is open, so the roll MUST be scored there" in out
    rows = table_rows(out)
    assert len(rows) == 1 and rows[0].startswith("* Fours") and rows[0].rstrip().endswith("forced")


def test_recommend_forced_fours_with_bonus_json(run, solver_hasbro):
    rc, out, _ = run("--json", "recommend", "--dice", "4,4,4,4,4", "--rolls", "0", "--scores", '{"11":50}')
    assert rc == 0
    d = ok_json(out)
    assert d["action"] == "score" and d["category"] == 3 and d["category_name"] == "Fours"
    assert d["points"] == 20 and d["joker_bonus"] == 100 and d["joker_bonus_available"] is True
    assert d["joker_rule"] == "forced_upper" and d["forced_category_name"] == "Fours"
    assert d["yahtzee_status"] == 2 and d["is_yahtzee_roll"] is True
    opts = d["category_options"]
    assert len(opts) == 1 and opts[0]["is_forced"] is True and opts[0]["bonus"] == 100
    after = (1 << 11) | (1 << 3)
    assert abs(d["expected_value"] - (20 + 100 + solver_hasbro.ev(after, 20, 1))) < 1e-9
    assert abs(d["expected_final"] - (50 + d["expected_value"])) < 1e-12
    assert abs(d["expected_final"] - 433.07) < 0.005


def test_recommend_scratched_yahtzee_lower_only_no_bonus(run, solver_hasbro):
    card = '{"11":0,"3":12}'
    rc, out, _ = run("--json", "recommend", "--dice", "4,4,4,4,4", "--rolls", "0", "--scores", card)
    assert rc == 0
    d = ok_json(out)
    assert d["action"] == "score" and d["category_name"] == "Large Straight" and d["points"] == 40
    assert d["joker_rule"] == "lower_only" and d["forced_category"] is None
    assert d["joker_bonus_available"] is False and d.get("joker_bonus") is None
    names = [o["name"] for o in d["category_options"]]
    assert set(names) == {"Three of a Kind", "Four of a Kind", "Full House", "Small Straight",
                          "Large Straight", "Chance"}
    assert all(o["bonus"] == 0 and o["is_forced"] is False for o in d["category_options"])
    pts = {o["name"]: o["points"] for o in d["category_options"]}
    assert pts == {"Three of a Kind": 20, "Four of a Kind": 20, "Full House": 25, "Small Straight": 30,
                   "Large Straight": 40, "Chance": 20}
    after = (1 << 11) | (1 << 3) | (1 << 10)
    assert abs(d["expected_value"] - (40 + solver_hasbro.ev(after, 12, 0))) < 1e-9
    assert abs(d["expected_final"] - (12 + d["expected_value"])) < 1e-12
    assert "no bonus because the Yahtzee box holds 0" in d["joker_note"]
    rc, out, _ = run("recommend", "--dice", "4,4,4,4,4", "--rolls", "0", "--scores", card)
    assert rc == 0
    assert "SCORE Large Straight for 40 points" in out and "(+" not in out
    assert "Yahtzee box: scratched (0)" in out
    assert "an open lower box must be used at Joker values" in out
    assert "no bonus because the Yahtzee box holds 0" in out
    assert "forced" not in out.split("Exp. final")[1]


def test_recommend_keep_and_reroll_text(run):
    rc, out, _ = run("recommend", "--dice", "1,2,3,4,6", "--rolls", "1")
    assert rc == 0
    assert "KEEP 1 2 3 4, reroll 6" in out
    m = re.search(r"expected final ([\d.]+)\s+\(stopping now: Small Straight for 30, expected final ([\d.]+)\)", out)
    assert m and float(m.group(1)) > float(m.group(2))


def test_recommend_plain_rules_yahtzee_scores_normally(run):
    rc, out, _ = run("--rules", "plain", "--json", "recommend", "--dice", "4,4,4,4,4", "--rolls", "0",
                     "--scores", '{"11":50}')
    assert rc == 0
    d = ok_json(out)
    assert d["mode"] == "traditional" and d["joker_bonus_available"] is False and d.get("joker_bonus") is None
    pts = {o["name"]: o["points"] for o in d["category_options"]}
    assert pts["Full House"] == 0 and pts["Large Straight"] == 0 and pts["Fours"] == 20
    assert "plain rules: no Joker" in d["joker_note"]


# --------------------------------------------------------------------------------------
# pmf
# --------------------------------------------------------------------------------------
@pytest.mark.parametrize("card", [CARD_3OPEN_BONUS, CARD_3OPEN_NOBONUS], ids=["bonus_earned", "no_bonus"])
def test_pmf_three_open_boxes_mean_matches_table(run, solver_hasbro, card):
    st = state_of(card)
    ev = solver_hasbro.ev(st.mask, st.upper, st.yb)
    std = solver_hasbro.std(st.mask, st.upper, st.yb)
    rc, out, err = run("--json", "pmf", "--scores", js(card))
    assert rc == 0 and err == ""
    d = ok_json(out)
    assert d["distribution_of"] == "remaining" and d["offset"] == -st.upper_bonus_earned
    # displayed mean is the table EV less the already-earned 35
    assert abs(d["stats"]["mean"] - (ev - st.upper_bonus_earned)) < 1e-9
    assert abs(d["stats"]["std"] - std) < 1e-9
    assert abs(d["stats"]["mass"] - 1.0) < 1e-12
    assert d["ev_check"]["table_mean"] == ev and d["ev_check"]["table_std"] == std
    pmf = d["pmf"]
    assert abs(sum(pmf) - 1.0) < 1e-12 and min(pmf) >= 0
    raw_mean = sum(i * p for i, p in enumerate(pmf))
    assert abs(raw_mean - ev) < 1e-9
    assert d["support"][0] >= 0 and d["support"][1] == len(pmf) - 1 + d["offset"]
    assert d["stats"]["p10"] <= d["stats"]["p50"] <= d["stats"]["p90"] <= d["support"][1]
    assert abs(sum(b["p"] for b in d["histogram"]["bins"]) + d["histogram"]["p_below"]
               + d["histogram"]["p_above"] - 1.0) < 1e-9
    # text view prints the same mean and std
    rc, out, _ = run("pmf", "--scores", js(card))
    assert rc == 0
    assert "Exact distribution of the remaining score under optimal play" in out
    m = re.search(r"^\s*mean ([\d.]+)\s+std ([\d.]+)\s+p10 (\d+)\s+p50 (\d+)\s+p90 (\d+)\s+range (\d+)-(\d+)", out, re.M)
    assert m, out
    assert float(m.group(1)) == round(ev - st.upper_bonus_earned, 2)
    assert float(m.group(2)) == round(std, 2)
    assert [int(m.group(i)) for i in (3, 4, 5)] == [d["stats"]["p10"], d["stats"]["p50"], d["stats"]["p90"]]
    assert [int(m.group(6)), int(m.group(7))] == d["support"]
    assert sum(1 for l in out.splitlines() if l.rstrip().endswith("%")) == len(d["histogram"]["bins"]) + \
        (d["histogram"]["p_below"] > 5e-4) + (d["histogram"]["p_above"] > 5e-4)


def test_pmf_final_and_locked_offsets(run, solver_hasbro):
    st50 = state_of(CARD_2OPEN_Y50)
    ev50 = solver_hasbro.ev(st50.mask, st50.upper, st50.yb)
    rc, out, _ = run("--json", "pmf", "--scores", js(CARD_2OPEN_Y50), "--final", "--bonuses", "1")
    assert rc == 0
    d = ok_json(out)
    assert d["distribution_of"] == "final" and d["offset"] == 209 + 100
    assert abs(d["stats"]["mean"] - d["state"]["expected_final"]) < 1e-9
    assert abs(d["stats"]["mean"] - (309 + ev50)) < 1e-9
    st = state_of(CARD_3OPEN_BONUS)
    ev = solver_hasbro.ev(st.mask, st.upper, st.yb)
    rc, out, _ = run("--json", "pmf", "--scores", js(CARD_3OPEN_BONUS), "--locked", "0")
    assert rc == 0
    d = ok_json(out)
    assert d["offset"] == 0 and abs(d["stats"]["mean"] - ev) < 1e-9
    rc, out, _ = run("pmf", "--scores", js(CARD_3OPEN_BONUS), "--final")
    assert rc == 0 and "Exact distribution of the final score under optimal play (159 banked points added)" in out


def test_pmf_refuses_thirteen_open_boxes(run):
    rc, out, err = run("pmf")
    assert rc == 2 and out == ""
    assert err.startswith("error: ")
    assert f"13 boxes open; exact distribution limited to {MAX_OPEN_FOR_EXACT}" in err
    assert "--max-open" in err and "'ev'" in err
    rc, out, err = run("--json", "pmf")
    assert rc == 2 and err == ""
    d = json.loads(out)
    assert d["ok"] is False and "13 boxes open" in d["error"]


def test_pmf_max_open_cap_is_honoured(run):
    rc, out, err = run("pmf", "--scores", js(CARD_5OPEN), "--max-open", "3")
    assert rc == 2 and "5 boxes open; exact distribution limited to 3" in err
    rc, out, err = run("--json", "pmf", "--scores", js(CARD_5OPEN), "--max-open", "5")
    assert rc == 0 and abs(json.loads(out)["stats"]["mass"] - 1.0) < 1e-12


def test_pmf_game_over_is_a_point_mass(run):
    rc, out, _ = run("--json", "pmf", "--scores", js(CARD_DONE))
    assert rc == 0
    d = ok_json(out)
    assert d["pmf"][-1] == 1.0 and d["stats"]["std"] == 0.0 and d["stats"]["mean"] == 0.0


# --------------------------------------------------------------------------------------
# match
# --------------------------------------------------------------------------------------
def test_match_symmetric_normal_approximation(run):
    rc, out, err = run("match", "--p1", '{"11":50}', "--p2", '{"11":50}')
    assert rc == 0 and err == ""
    assert "Player 1 wins 50.0%    tie 0.0%    Player 2 wins 50.0%" in out
    assert "normal approximation" in out
    rc, out, _ = run("--json", "match", "--p1", "{}", "--p2", "{}")
    d = ok_json(out)
    assert d["method"] == "normal" and d["p_win"] == d["p_lose"] == 0.5 and d["p_tie"] == 0.0
    assert d["p1"]["expected_final"] == d["p2"]["expected_final"]


def test_match_normal_favours_the_leader(run):
    rc, out, _ = run("--json", "match", "--p1", '{"11":50}', "--p2", '{"11":0}')
    d = ok_json(out)
    assert d["p_win"] > 0.5 > d["p_lose"] and abs(d["p_win"] + d["p_lose"] - 1.0) < 1e-12
    rc, out, _ = run("--json", "match", "--p1", '{"11":50,"3":12}', "--p2", '{"11":50}', "--p1-bonuses", "1")
    d = ok_json(out)
    assert d["p1"]["current_total"] == 162 and d["p_win"] > 0.75 > d["p_lose"]
    # a chip is impossible with an open or scratched Yahtzee box, or without a box filled after it
    for p1, chips in (('{"11":0}', "1"), ('{"3":12}', "1"), ('{"11":50}', "1")):
        rc, out, _ = run("--json", "match", "--p1", p1, "--p2", '{"11":50}', "--p1-bonuses", chips)
        assert rc == 2 and json.loads(out)["ok"] is False


def test_match_exact_identical_players_tie_symmetrically(run):
    rc, out, err = run("--json", "match", "--exact", "--p1", js(CARD_5OPEN), "--p2", js(CARD_5OPEN))
    assert rc == 0 and err == ""
    d = ok_json(out)
    assert d["method"] == "exact"
    assert abs(d["p_win"] - d["p_lose"]) < 1e-9
    assert d["p_tie"] > 0.01
    assert abs(d["p_win"] + d["p_tie"] + d["p_lose"] - 1.0) < 1e-9
    assert d["p1"]["boxes_open"] == d["p2"]["boxes_open"] == 5
    rc, out, _ = run("match", "--exact", "--p1", js(CARD_5OPEN), "--p2", js(CARD_5OPEN))
    assert rc == 0
    m = re.search(r"Player 1 wins ([\d.]+)%\s+tie ([\d.]+)%\s+Player 2 wins ([\d.]+)%", out)
    assert m and m.group(1) == m.group(3)
    assert abs(sum(float(g) for g in m.groups()) - 100.0) < 0.15      # three rounded percentages
    assert "exact score distributions" in out


def test_match_exact_swapping_players_swaps_win_and_loss(run):
    rc, out, _ = run("--json", "match", "--exact", "--p1", js(CARD_5OPEN), "--p2", js(CARD_5OPEN_Y))
    a = ok_json(out)
    rc, out, _ = run("--json", "match", "--exact", "--p1", js(CARD_5OPEN_Y), "--p2", js(CARD_5OPEN))
    b = ok_json(out)
    assert abs(a["p_win"] - b["p_lose"]) < 1e-9 and abs(a["p_lose"] - b["p_win"]) < 1e-9
    assert abs(a["p_tie"] - b["p_tie"]) < 1e-12
    assert abs(a["p_win"] + a["p_tie"] + a["p_lose"] - 1.0) < 1e-9
    assert a["p_lose"] > a["p_win"]            # the player holding the 50 is ahead


def test_match_exact_refuses_too_many_open_boxes_per_player(run):
    rc, out, err = run("match", "--exact", "--p1", "{}", "--p2", js(CARD_5OPEN))
    assert rc == 2 and out == "" and err.startswith("error: player 1: 13 boxes open")
    rc, out, err = run("match", "--exact", "--p1", js(CARD_5OPEN), "--p2", "{}")
    assert rc == 2 and err.startswith("error: player 2: 13 boxes open")
    rc, out, err = run("match", "--exact", "--max-open", "3", "--p1", js(CARD_5OPEN), "--p2", js(CARD_5OPEN))
    assert rc == 2 and "player 1: 5 boxes open; exact distribution limited to 3" in err


# --------------------------------------------------------------------------------------
# precompute
# --------------------------------------------------------------------------------------
def test_precompute_plain_builds_then_loads(run, tmp_path):
    table = tmp_path / "ev_plain.npz"
    rc, out, err = run("precompute", "--rules", "plain", "--table-dir", str(tmp_path))
    assert rc == 0, err
    assert table.exists() and table.stat().st_size > 1_000_000
    assert "Building tables for rules plain" in out
    assert re.search(r"rules=plain\s+built\s+table=", out)
    assert "fresh-game expected score 245.870775   std 39.8201" in out
    assert sorted(p.name for p in tmp_path.iterdir()) == ["ev_plain.npz"]     # no .bak left behind
    mtime = table.stat().st_mtime_ns

    rc, out, err = run("--json", "precompute", "--rules", "plain", "--table-dir", str(tmp_path))
    assert rc == 0, err
    d = ok_json(out)
    assert d["action"] == "loaded" and d["rules"] == "plain"
    assert Path(d["table"]) == table
    assert abs(d["fresh_ev"] - 245.870775) < 1e-6 and abs(d["fresh_std"] - 39.8201) < 1e-4
    assert d["seconds"] < 2.0
    assert table.stat().st_mtime_ns == mtime                     # the second run did not rewrite it

    s = Solver(PLAIN, table_dir=tmp_path, build_if_missing=False, verbose=False)
    assert abs(s.fresh_ev - 245.870775) < 1e-6
    rc, out, _ = run("--rules", "plain", "--table-dir", str(tmp_path), "--json", "ev")
    assert rc == 0 and abs(ok_json(out)["ev_remaining"] - s.fresh_ev) < 1e-12


def test_precompute_unusable_table_dir(run):
    rc, out, err = run("precompute", "--table-dir", "/dev/null/not-a-dir")
    assert rc == 2 and out == "" and err.startswith("error: cannot use table directory")


# --------------------------------------------------------------------------------------
# error paths: exit status 2, message on stderr (text) or a JSON error object (--json)
# --------------------------------------------------------------------------------------
ERROR_CASES = [
    (["recommend", "--dice", "1,2,3,4", "--rolls", "2"], "dice must be a list of 5 values"),
    (["recommend", "--dice", "1,2,3,4,5,6", "--rolls", "2"], "dice must be a list of 5 values"),
    (["recommend", "--dice", "1,2,3,4,7", "--rolls", "2"], "each die must be an integer from 1 to 6"),
    (["recommend", "--dice", "abcde", "--rolls", "2"], "dice must be five numbers from 1 to 6"),
    (["recommend", "--dice", "1,2,3,4,5", "--rolls", "3"], "rolls left must be 0, 1 or 2"),
    (["recommend", "--dice", "1,2,3,4,5", "--rolls", "-1"], "rolls left must be 0, 1 or 2"),
    (["recommend", "--dice", "1,2,3,4,5", "--rolls", "2", "--scores", "{bad"], "scores must be a JSON object"),
    (["recommend", "--dice", "1,2,3,4,5", "--rolls", "2", "--scores", js(CARD_DONE)], "game is over"),
    (["ev", "--scores", '{"0":7}'], "7 is not a possible score for Ones"),
    (["ev", "--scores", '{"8":20}'], "20 is not a possible score for Full House"),
    (["ev", "--scores", '{"11":25}'], "25 is not a possible score for Yahtzee"),
    (["ev", "--scores", '{"6":4}'], "4 is not a possible score for Three of a Kind"),
    (["ev", "--scores", '{"12":-1}'], "-1 is not a possible score for Chance"),
    (["ev", "--scores", '{"0":1.5}'], "score for Ones must be an integer"),
    (["ev", "--scores", "[1,2]"], "scores must be a JSON object"),
    (["ev", "--scores", '{"foo":3}'], "unknown category 'foo'"),
    (["ev", "--scores", '{"f":3}'], "ambiguous category 'f'"),
    (["ev", "--scores", '{"13":3}'], "category index 13 out of range"),
    (["ev", "--scores", '{"11":50,"yahtzee":0}'], "box Yahtzee appears twice"),
    (["ev", "--scores", "@/nonexistent/ysolver-scores.json"], "cannot read scores file"),
    (["ev", "--bonuses", "13"], "bonuses must be between 0 and 12"),
    (["ev", "--bonuses", "x"], "bonuses must be a whole number"),
    (["pmf", "--max-open", "14"], "--max-open must be between 0 and 13"),
    (["pmf", "--locked", "3", "--final"], "either --locked N or --final"),
    (["pmf", "--locked", "-1", "--scores", js(CARD_3OPEN_BONUS)], "--locked must be >= 0"),
    (["match", "--p1", "{}", "--p2", "{nope"], "--p2: scores must be a JSON object"),
    (["match", "--p1", '{"0":9}', "--p2", "{}"], "--p1: invalid scorecard: 9 is not a possible score for Ones"),
    (["match", "--p1", "{}", "--p2", "{}", "--p1-bonuses", "99"], "--p1-bonuses must be between 0 and 12"),
    (["interactive", "--scores", "{bad"], "scores must be a JSON object"),
]
ERROR_IDS = [" ".join(a[:3]) + (" ..." if len(a) > 3 else "") for a, _ in ERROR_CASES]


@pytest.mark.parametrize("argv,needle", ERROR_CASES, ids=ERROR_IDS)
def test_error_paths_text(run, argv, needle):
    rc, out, err = run(*argv)
    assert rc == 2
    assert out == ""
    assert err.startswith("error: ") and needle in err, err
    assert "Traceback" not in err


@pytest.mark.parametrize("argv,needle", ERROR_CASES, ids=ERROR_IDS)
def test_error_paths_json(run, argv, needle):
    rc, out, err = run("--json", *argv)
    assert rc == 2
    assert err == ""
    d = json.loads(out)
    assert d == {"ok": False, "error": d["error"]} and needle in d["error"]


@pytest.mark.parametrize("argv", [["--rules", "bogus", "ev"], ["ev", "--rules", "bogus"], ["bogus"],
                                  ["recommend", "--rolls", "2"], ["match", "--p1", "{}"]],
                         ids=["global-rules", "sub-rules", "command", "missing-dice", "missing-p2"])
def test_argparse_level_errors_exit_2_with_usage_on_stderr(run, argv):
    rc, out, err = run(*argv)
    assert rc == 2 and out == ""
    assert "usage:" in err and "error:" in err
    if "bogus" in argv:
        assert "invalid choice: 'bogus'" in err


# --------------------------------------------------------------------------------------
# interactive
# --------------------------------------------------------------------------------------
def test_interactive_plays_two_entries_and_quits(run):
    script = "1 2 3 4 5\nscore ls\n6 6 6 6 6 0\nscore yahtzee\nquit\n"
    rc, out, err = run("interactive", stdin=script)
    assert rc == 0 and err == ""
    assert out.startswith("Yahtzee solver, rules hasbro")
    assert "error:" not in out and "Traceback" not in out
    prompts = re.findall(r"\[turn \d+, [^\]]+\] >", out)
    assert prompts == ["[turn 1, new roll] >", "[turn 1, 2 rolls left] >", "[turn 2, new roll] >",
                       "[turn 2, 0 rolls left] >", "[turn 3, new roll] >"]
    assert "STOP ROLLING and score Large Straight for 40 points" in out
    assert "  ... 7 more" in out                                  # the table is trimmed to 6 rows
    assert "(enter 'score <box>' to write it down)" in out
    assert "Scored 40 in Large Straight." in out
    assert "SCORE Yahtzee for 50 points" in out
    assert "the Yahtzee box is open, so this is a natural 50" in out
    assert "Scored 50 in Yahtzee." in out
    assert "Score so far 90    expected remaining 237.29" in out
    assert "Game complete" not in out


def test_interactive_joker_chip_card_and_undo(run):
    script = "66666 0\nscore y\n44444 0\nscore chance\nscore fours\ncard\nundo\nev\nbonus 3\nzero chance\nzero ls\nzero fh\nbonus 3\nq\n"
    rc, out, err = run("interactive", stdin=script)
    assert rc == 0 and err == ""
    assert "SCORE Fours for 20 points (+100 bonus)" in out
    assert "error: with 4 4 4 4 4 the Joker rule does not allow Chance; allowed: Fours." in out
    assert "Scored 20 in Fours. Yahtzee bonus chip +100 (now 1)." in out
    assert re.search(r"^ {3}3  Fours {14}20$", out, re.M)
    assert re.search(r"Yahtzee bonus\s+100\s+\(1 chips\)", out)
    assert re.search(r"Total\s+170$", out, re.M)
    assert "Undone." in out
    after_undo = out.split("Undone.")[1]
    assert "bonus chips: 0" in after_undo and "Score so far 50" in after_undo
    assert "error: bonuses: at most one bonus chip per box filled after the Yahtzee box" in after_undo
    assert "Scored 0 in Chance." in after_undo
    assert "bonus chips: 3" in after_undo and "Score so far 350" in after_undo


def test_interactive_resume_and_finish_the_game(run):
    card = dict(CARD_DONE)
    del card["12"]
    rc, out, err = run("interactive", "--scores", js(card), stdin="2 3 4 5 6 0\nscore chance\nignored\n")
    assert rc == 0 and err == ""
    assert "1 box open (Chance)" in out
    assert "[turn 13, new roll] >" in out and "[turn 13, 0 rolls left] >" in out
    assert "SCORE Chance for 20 points" in out
    assert out.rstrip().endswith("Game over. Final total 304\nGame complete. Final total 304.")
    assert "ignored" not in out and "error:" not in out        # the loop ended at game over


def test_interactive_eof_and_unknown_input(run):
    rc, out, err = run("interactive", stdin="")
    assert rc == 0 and out.rstrip().endswith("[turn 1, new roll] >")
    rc, out, err = run("--json", "interactive", stdin="bogus input here\nhelp\nscore\nq\n")
    assert rc == 0
    assert err == "note: --json is ignored by interactive mode\n"
    assert "error: unrecognised input 'bogus input here'; type 'help' for the commands" in out
    assert "score <box> [pts]" in out
    assert "error: usage: score <box> [points]" in out


def test_interactive_subprocess_with_piped_stdin():
    script = "1 2 3 4 5\nscore ls\n6 6 6 6 6 0\nscore yahtzee\nquit\n"
    proc = subprocess.run([sys.executable, "-W", "ignore", str(ROOT / "cli.py"), "interactive"],
                          input=script, capture_output=True, text=True, cwd=ROOT, timeout=120)
    assert proc.returncode == 0, proc.stderr
    assert proc.stderr == ""
    assert "Scored 40 in Large Straight." in proc.stdout
    assert "Scored 50 in Yahtzee." in proc.stdout
    assert proc.stdout.rstrip().endswith("[turn 3, new roll] >")
    # EOF without 'quit' also leaves cleanly
    proc = subprocess.run([sys.executable, "-W", "ignore", str(ROOT / "cli.py"), "interactive"],
                          input="1 2 3 4 5\n", capture_output=True, text=True, cwd=ROOT, timeout=120)
    assert proc.returncode == 0 and proc.stderr == ""
    assert "STOP ROLLING and score Large Straight" in proc.stdout
