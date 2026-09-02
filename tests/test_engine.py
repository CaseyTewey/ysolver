"""Solver tables, policy helpers and the recommend() contract."""
import random
from fractions import Fraction
from math import factorial

import numpy as np
import pytest

from dice import dice_list_to_counts, roll_id
from engine import (
    CATEGORY_MAX, FULL_MASK, MAX_UPPER, YAHTZEE, canonical_yb, max_remaining, parse_dice,
    parse_rolls_remaining, parse_scorecard, yahtzee_status_of,
)

GOLDEN = {"hasbro": (254.587729, 59.6076), "verhoeff": (254.589609, 59.6114), "plain": (245.870775, 39.8201)}
LS_ROLL = roll_id(dice_list_to_counts([1, 2, 3, 4, 5]))
YZ4 = roll_id(dice_list_to_counts([4, 4, 4, 4, 4]))
M_FOURS_OPEN = (1 << YAHTZEE) | (1 << 0) | (1 << 6)


def random_states(n: int, seed: int):
    """n distinct non-terminal states with yb=1 only when the Yahtzee box is filled."""
    rng = random.Random(seed)
    out = []
    seen = set()
    while len(out) < n:
        mask = rng.randrange(FULL_MASK)
        upper = rng.randrange(MAX_UPPER + 1)
        yb = rng.randrange(2) if (mask >> YAHTZEE) & 1 else 0
        if (mask, upper, yb) not in seen:
            seen.add((mask, upper, yb))
            out.append((mask, upper, yb))
    return out


# ------------------------------------------------------------------------------ tables
def test_fresh_ev_and_std(preset_solver):
    name, s = preset_solver
    ev, sd = GOLDEN[name]
    assert abs(s.fresh_ev - ev) < 1e-6
    assert abs(s.std(0, 0, 0) - sd) < 1e-3
    assert s.ev(0, 0, 0) == s.fresh_ev
    assert s.EV.shape == (8192, 64, 2) == s.M2.shape


def test_terminal_values(preset_solver):
    _, s = preset_solver
    for yb in (0, 1):
        for u in range(64):
            expected = 35.0 if u == 63 else 0.0
            assert s.ev(FULL_MASK, u, yb) == expected
            assert s.M2[FULL_MASK, u, yb] == expected * expected
            assert s.variance(FULL_MASK, u, yb) == 0.0


def test_ev_monotone_in_upper(preset_solver):
    _, s = preset_solver
    assert np.diff(s.EV, axis=1).min() >= -1e-9


def test_variance_nonnegative(preset_solver):
    _, s = preset_solver
    assert (s.M2 - s.EV ** 2).min() >= -1e-6


def test_yb_ordering_and_preset_ordering(solvers):
    h, v, p = solvers["hasbro"], solvers["verhoeff"], solvers["plain"]
    yz = ((np.arange(FULL_MASK + 1) >> YAHTZEE) & 1) == 1
    for s in (h, v):   # a 50 in the box only adds bonus eligibility
        assert (s.EV[yz, :, 1] - s.EV[yz, :, 0]).min() >= -1e-9
    assert np.array_equal(p.EV[:, :, 0], p.EV[:, :, 1])   # no bonus, no joker: yb is irrelevant
    # Verhoeff never restricts a choice that Hasbro or plain allow, and never scores it lower
    assert (v.EV - h.EV).min() >= -1e-9
    assert (v.EV - p.EV).min() >= -1e-9


def test_turn_ev_matches_table(preset_solver):
    _, s = preset_solver
    for mask, upper, yb in random_states(50, seed=1):
        assert abs(s.turn_ev(mask, upper, yb) - s.ev(mask, upper, yb)) < 1e-9
    tv = s.turn(0, 0, 0)
    assert {k: v.shape for k, v in tv.items()} == {"v1": (252,), "v2": (252,), "v3": (252,), "e1": (462,), "e2": (462,)}


def test_check_rejects_bad_states(solver_hasbro):
    for bad in [(-1, 0, 0), (FULL_MASK + 1, 0, 0), (0, 64, 0), (0, -1, 0), (0, 0, 2)]:
        with pytest.raises(ValueError):
            solver_hasbro.ev(*bad)
    with pytest.raises(ValueError):
        solver_hasbro.turn(FULL_MASK, 63, 0)


# ------------------------------------------------------------------------------- keeps
def test_best_keep_is_sub_multiset(preset_solver):
    _, s = preset_solver
    rng = random.Random(7)
    t = s.t
    for mask, upper, yb in random_states(20, seed=3):
        rid = rng.randrange(252)
        roll = t.rolls[rid]
        for rr in (1, 2):
            keep, keep_ev = s.best_keep(mask, upper, yb, rid, rr)
            assert len(keep) == 6 and all(0 <= k <= r for k, r in zip(keep, roll))
            assert keep_ev == s.roll_ev(mask, upper, yb, rid, rr)   # value of the roll == value of its best keep
            target = s.turn(mask, upper, yb)["e1" if rr == 2 else "e2"]
            kid = [tuple(k) for k in t.keeps.tolist()].index(tuple(keep))
            assert keep_ev == target[kid]
    with pytest.raises(ValueError):
        s.best_keep(0, 0, 0, 0, 0)


def test_keep_all_for_fresh_large_straight(solver_hasbro):
    s = solver_hasbro
    expected = 40 + s.ev(1 << 10, 0, 0)
    for rr in (1, 2):
        keep, keep_ev = s.best_keep(0, 0, 0, LS_ROLL, rr)
        assert keep == (1, 1, 1, 1, 1, 0)
        assert abs(keep_ev - expected) < 1e-9
        rec = s.recommend([1, 2, 3, 4, 5], 0, 0, 0, rr)
        assert rec["action"] == "keep" and rec["keep_all"] is True
        assert rec["keep_dice"] == [1, 2, 3, 4, 5]
    assert s.best_category(0, 0, 0, LS_ROLL)["category"] == 10
    assert abs(s.roll_ev(0, 0, 0, LS_ROLL, 0) - expected) < 1e-9


# --------------------------------------------------------------------------- categories
def test_category_options_contract(preset_solver):
    _, s = preset_solver
    rng = random.Random(11)
    for mask, upper, yb in random_states(30, seed=5):
        rid = rng.randrange(252)
        legal, pts, bonus = s.options(mask, upper, yb, rid)
        opts = s.category_options(mask, upper, yb, rid)
        assert [o["category"] for o in opts] and {o["category"] for o in opts} == {c for c in range(13) if legal[c]}
        evs = [o["expected_value"] for o in opts]
        assert evs == sorted(evs, reverse=True)
        for o in opts:
            c = o["category"]
            assert o["points"] == int(pts[c]) and o["bonus"] == bonus
            nm = mask | (1 << c)
            nyb = 1 if (c == YAHTZEE and s.t.is_yz[rid]) else yb
            nu = min(MAX_UPPER, upper + o["points"]) if c < 6 else upper
            assert abs(o["expected_value"] - (o["points"] + bonus + s.ev(nm, nu, nyb))) < 1e-12
        assert s.best_category(mask, upper, yb, rid) == opts[0]
        assert abs(s.roll_ev(mask, upper, yb, rid, 0) - opts[0]["expected_value"]) < 1e-9


def test_forced_case_returns_exactly_one_option(solver_hasbro):
    s = solver_hasbro
    for yb in (0, 1):
        opts = s.category_options(M_FOURS_OPEN, 10, yb, YZ4)
        assert len(opts) == 1
        o = opts[0]
        assert o["category"] == 3 and o["name"] == "Fours" and o["points"] == 20
        assert o["bonus"] == 100 * yb and o["is_forced"] is True
        assert abs(o["expected_value"] - (20 + 100 * yb + s.ev(M_FOURS_OPEN | (1 << 3), 30, yb))) < 1e-12
    # not forced without a Yahtzee roll, and not forced with the box open
    assert all(not o["is_forced"] for o in s.category_options(M_FOURS_OPEN, 10, 1, LS_ROLL))
    assert all(not o["is_forced"] for o in s.category_options(0, 0, 0, YZ4))


# ---------------------------------------------------------------------------- recommend
COMMON_KEYS = {"dice", "mask", "upper", "rolls_remaining", "mode", "rules", "yahtzee_status", "is_yahtzee_roll",
               "joker_bonus_available", "joker_rule", "forced_category", "forced_category_name",
               "category_options", "action", "expected_value"}


@pytest.mark.parametrize("rr", [0, 1, 2])
def test_recommend_contract(preset_solver, rr):
    name, s = preset_solver
    rec = s.recommend([1, 1, 3, 5, 6], 0, 0, 0, rr)
    assert COMMON_KEYS <= set(rec)
    assert rec["rules"] == name and rec["mode"] == ("traditional" if name == "plain" else "joker")
    assert rec["dice"] == [1, 1, 3, 5, 6] and rec["rolls_remaining"] == rr
    assert rec["yahtzee_status"] == 0 and rec["is_yahtzee_roll"] is False
    assert rec["joker_rule"] is None and rec["forced_category"] is None and "joker_bonus" not in rec
    rid = roll_id(dice_list_to_counts([1, 1, 3, 5, 6]))
    if rr == 0:
        assert rec["action"] == "score"
        assert {"category", "category_name", "points"} <= set(rec)
        assert rec["category"] == rec["category_options"][0]["category"]
        assert rec["expected_value"] == rec["category_options"][0]["expected_value"]
    else:
        assert rec["action"] == "keep"
        assert {"keep_counts", "keep_dice", "keep_all", "keep_expected_value"} <= set(rec)
        counts = rec["keep_counts"]
        assert rec["keep_dice"] == [f + 1 for f in range(6) for _ in range(counts[f])]
        assert rec["keep_all"] == (sum(counts) == 5)
        assert rec["expected_value"] == s.roll_ev(0, 0, 0, rid, rr) == rec["keep_expected_value"]


def test_recommend_joker_fields(solver_hasbro):
    s = solver_hasbro
    rec = s.recommend([4, 4, 4, 4, 4], M_FOURS_OPEN, 10, 2, 0)
    assert rec["is_yahtzee_roll"] is True and rec["yahtzee_status"] == 2
    assert rec["joker_rule"] == "forced_upper" and rec["forced_category"] == 3
    assert rec["forced_category_name"] == "Fours" and rec["joker_bonus"] == 100
    assert rec["joker_bonus_available"] is True
    assert rec["action"] == "score" and rec["category"] == 3 and rec["points"] == 20
    assert len(rec["category_options"]) == 1
    scratched = s.recommend([4, 4, 4, 4, 4], M_FOURS_OPEN, 10, 1, 0)
    assert scratched["yahtzee_status"] == 1 and "joker_bonus" not in scratched
    assert scratched["joker_bonus_available"] is False and scratched["forced_category"] == 3
    natural = s.recommend([4, 4, 4, 4, 4], 0, 0, 0, 0)
    assert natural["joker_rule"] is None and natural["forced_category"] is None
    assert natural["category"] == YAHTZEE and natural["points"] == 50
    keep = s.recommend([4, 4, 4, 4, 4], M_FOURS_OPEN, 10, 2, 1)
    assert keep["action"] == "keep" and keep["keep_all"] is True and keep["joker_bonus"] == 100


@pytest.mark.parametrize("dice, mask, upper, status, rr", [
    ([1, 2, 3, 4], 0, 0, 0, 0),
    ([1, 2, 3, 4, 5, 6], 0, 0, 0, 0),
    ([1, 2, 3, 4, 7], 0, 0, 0, 0),
    ([1, 2, 3, 4, 0], 0, 0, 0, 0),
    ([1, 2, 3, 4, "5"], 0, 0, 0, 0),
    ([1, 2, 3, 4, True], 0, 0, 0, 0),
    ("12345", 0, 0, 0, 0),
    ([1, 2, 3, 4, 5], 0, 0, 0, 3),
    ([1, 2, 3, 4, 5], 0, 0, 0, -1),
    ([1, 2, 3, 4, 5], 0, 0, 0, True),
    ([1, 2, 3, 4, 5], FULL_MASK, 63, 2, 0),
    ([1, 2, 3, 4, 5], 0, 64, 0, 0),
    ([1, 2, 3, 4, 5], -1, 0, 0, 0),
])
def test_recommend_rejects_bad_input(solver_hasbro, dice, mask, upper, status, rr):
    with pytest.raises(ValueError):
        solver_hasbro.recommend(dice, mask, upper, status, rr)


# ------------------------------------------------------------------------ state helpers
def test_parse_helpers():
    assert parse_dice((6, 5, 4, 3, 2)) == [6, 5, 4, 3, 2]
    assert parse_rolls_remaining(2) == 2
    st = parse_scorecard({"3": 20, "11": 50, 6: 25, "0": None, "5": 30.0})
    assert st.mask == (1 << 3) | (1 << 11) | (1 << 6) | (1 << 5)
    assert st.upper == 50 == st.upper_raw and st.yb == 1 and st.yahtzee_status == 2
    assert st.locked == 125 and st.upper_bonus_earned == 0 and st.boxes_remaining == 9
    assert st.open_boxes == [0, 1, 2, 4, 7, 8, 9, 10, 12]
    full = parse_scorecard({c: v for c, v in enumerate((5, 10, 15, 20, 25, 30, 30, 30, 25, 30, 40, 0, 30))})
    assert full.mask == FULL_MASK and full.upper == 63 and full.upper_raw == 105
    assert full.upper_bonus_earned == 35 and full.yb == 0 and full.yahtzee_status == 1
    assert full.locked == 290   # the 35 bonus is not part of locked
    for bad in ({"3": 7}, {"8": 20}, {"11": 40}, {"13": 0}, {"a": 1}, {"6": 4}, {"0": True}, [1, 2]):
        with pytest.raises(ValueError):
            parse_scorecard(bad)
    assert parse_scorecard(None).mask == 0
    for mask in (0, 1 << YAHTZEE, FULL_MASK):
        for status in (0, 1, 2):
            yb = canonical_yb(mask, status)
            assert yb == (1 if ((mask >> YAHTZEE) & 1 and status == 2) else 0)
            if (mask >> YAHTZEE) & 1 and status:
                assert yahtzee_status_of(mask, yb) == status
    assert yahtzee_status_of(0, 0) == 0


def test_max_remaining(solvers):
    from engine import HASBRO, PLAIN
    assert max_remaining(HASBRO, FULL_MASK, 63, 0) == 35
    assert max_remaining(HASBRO, FULL_MASK, 62, 1) == 0
    assert max_remaining(HASBRO, 0, 0, 0) == sum(CATEGORY_MAX) + 35 + 100 * 12
    assert max_remaining(PLAIN, 0, 0, 0) == sum(CATEGORY_MAX) + 35
    for name, s in solvers.items():
        for mask, upper, yb in random_states(40, seed=9):
            assert s.ev(mask, upper, yb) <= max_remaining(s.rules, mask, upper, yb) + 1e-9


# ------------------------------------------------------------ one open box, from scratch
def _compositions(n, k=6):
    if k == 1:
        return [(n,)]
    return [(i,) + rest for i in range(n + 1) for rest in _compositions(n - i, k - 1)]


ROLLS = _compositions(5)
KEEPS = [k for n in range(6) for k in _compositions(n)]


def _prob(counts) -> Fraction:
    n = sum(counts)
    ways = factorial(n)
    for c in counts:
        ways //= factorial(c)
    return Fraction(ways, 6 ** n)


OUTCOMES = {k: [(tuple(a + b for a, b in zip(k, d)), _prob(d)) for d in _compositions(5 - sum(k))] for k in KEEPS}
SUBKEEPS = {r: [k for k in KEEPS if all(a <= b for a, b in zip(k, r))] for r in ROLLS}


def _score(cat, counts) -> int:
    """Independent scoring of one category (no imports from the repo)."""
    total = sum((f + 1) * c for f, c in enumerate(counts))
    mx = max(counts)
    if cat < 6:
        return counts[cat] * (cat + 1)
    if cat == 6:
        return total if mx >= 3 else 0
    if cat == 7:
        return total if mx >= 4 else 0
    if cat == 8:
        return 25 if sorted(counts)[-2:] == [2, 3] else 0
    present = [c > 0 for c in counts]
    if cat == 9:
        return 30 if any(all(present[i:i + 4]) for i in range(3)) else 0
    if cat == 10:
        return 40 if any(all(present[i:i + 5]) for i in range(2)) else 0
    if cat == 11:
        return 50 if mx == 5 else 0
    return total


def _final_points(preset, cat, counts, yb):
    """(points, bonus) when `counts` must go in the single open box `cat`."""
    if max(counts) != 5 or preset == "plain":
        return _score(cat, counts), 0
    bonus = 100 if yb else 0
    if cat == 11:                       # the Yahtzee box itself is the open one: natural Yahtzee
        return 50, bonus
    face = counts.index(5)
    if cat < 6:                         # forced into the matching upper box, or a zero in the only open upper box
        return (5 * (face + 1) if cat == face else 0), bonus
    return {8: 25, 9: 30, 10: 40}.get(cat, 5 * (face + 1)), bonus


def brute_force_one_box(preset, cat, upper, yb) -> Fraction:
    """Exact expected remaining score (bonus included) with only `cat` open, three rolls, all keeps."""
    v3 = {}
    for r in ROLLS:
        p, b = _final_points(preset, cat, r, yb)
        nu = min(63, upper + p) if cat < 6 else upper
        v3[r] = p + b + (35 if nu >= 63 else 0)

    def back(v):
        e = {k: sum(pr * v[o] for o, pr in OUTCOMES[k]) for k in KEEPS}
        return {r: max(e[k] for k in SUBKEEPS[r]) for r in ROLLS}

    v1 = back(back(v3))
    return sum(_prob(r) * v1[r] for r in ROLLS)


@pytest.mark.parametrize("preset, cat, upper, yb", [
    ("hasbro", 3, 43, 1),     # only Fours open, Yahtzee box 50: 20 in Fours reaches the bonus
    ("hasbro", 12, 63, 0),    # only Chance open, Yahtzee box scratched, bonus already secured
    ("hasbro", 11, 30, 0),    # only the Yahtzee box open: a natural Yahtzee scores 50, no bonus
    ("hasbro", 5, 33, 1),     # only Sixes open, Yahtzee box 50: 30 in Sixes reaches the bonus
    ("verhoeff", 3, 43, 1),   # one open box: the Verhoeff variant collapses to the same values
    ("verhoeff", 12, 63, 0),
    ("plain", 3, 43, 1),      # no bonus, a foreign Yahtzee in Fours is simply 0
    ("plain", 12, 50, 0),
])
def test_one_open_box_brute_force(solvers, preset, cat, upper, yb):
    s = solvers[preset]
    mask = FULL_MASK & ~(1 << cat)
    exact = brute_force_one_box(preset, cat, upper, yb)
    assert abs(float(exact) - s.ev(mask, upper, yb)) < 1e-9
    assert abs(float(exact) - s.turn_ev(mask, upper, yb)) < 1e-9
