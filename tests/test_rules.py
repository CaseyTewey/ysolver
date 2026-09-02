"""Legality, points and the Yahtzee bonus per rule set, via Solver.options / joker_situation."""
import numpy as np
import pytest

from dice import dice_list_to_counts, roll_id
from engine import HASBRO, PLAIN, PRESETS, VERHOEFF, YAHTZEE, Rules, tables

FOURS = 3
LOWER = (6, 7, 8, 9, 10, 12)


def rid_of(dice) -> int:
    return roll_id(dice_list_to_counts(dice))


def bits(*cats) -> int:
    m = 0
    for c in cats:
        m |= 1 << c
    return m


def open_set(mask: int) -> set:
    return {c for c in range(13) if not (mask >> c) & 1}


def legal_set(legal) -> set:
    return {c for c in range(13) if legal[c]}


YZ4 = rid_of([4, 4, 4, 4, 4])
YZ_ALL = [rid_of([f] * 5) for f in range(1, 7)]
NORMAL_4 = {0: 0, 1: 0, 2: 0, 3: 20, 4: 0, 5: 0, 6: 20, 7: 20, 8: 0, 9: 0, 10: 0, 11: 50, 12: 20}
JOKER_4 = {**NORMAL_4, 8: 25, 9: 30, 10: 40}

M_FOURS_OPEN = bits(YAHTZEE, 0, 6)                         # Ones, 3K, Yahtzee filled; Fours open
M_FOURS_FILLED = bits(YAHTZEE, FOURS, 0)                   # Ones, Fours, Yahtzee filled
M_LOWER_FILLED = bits(3, 4, 5, 6, 7, 8, 9, 10, 11, 12)     # only Ones, Twos, Threes open
M_BOX_OPEN = bits(0, 6)                                    # Yahtzee box still open


def _pts(pts, mask) -> dict:
    return {c: int(pts[c]) for c in open_set(mask)}


class TestHasbro:
    @pytest.mark.parametrize("yb", [0, 1])
    def test_forced_upper(self, solver_hasbro, yb):
        legal, pts, bonus = solver_hasbro.options(M_FOURS_OPEN, 0, yb, YZ4)
        assert legal_set(legal) == {FOURS}
        assert pts[FOURS] == 20
        assert bonus == 100 * yb
        assert solver_hasbro.joker_situation(M_FOURS_OPEN, yb, YZ4) == "forced_upper"

    @pytest.mark.parametrize("yb", [0, 1])
    def test_lower_only_with_joker_values(self, solver_hasbro, yb):
        legal, pts, bonus = solver_hasbro.options(M_FOURS_FILLED, 0, yb, YZ4)
        assert legal_set(legal) == set(LOWER)
        assert {c: int(pts[c]) for c in LOWER} == {6: 20, 7: 20, 8: 25, 9: 30, 10: 40, 12: 20}
        assert bonus == 100 * yb
        assert solver_hasbro.joker_situation(M_FOURS_FILLED, yb, YZ4) == "lower_only"

    @pytest.mark.parametrize("yb", [0, 1])
    def test_zero_in_open_upper_box(self, solver_hasbro, yb):
        legal, pts, bonus = solver_hasbro.options(M_LOWER_FILLED, 0, yb, YZ4)
        assert legal_set(legal) == {0, 1, 2}
        assert _pts(pts, M_LOWER_FILLED) == {0: 0, 1: 0, 2: 0}
        assert bonus == 100 * yb
        assert solver_hasbro.joker_situation(M_LOWER_FILLED, yb, YZ4) == "zero_upper"

    def test_forcing_follows_the_face(self, solver_hasbro):
        mask = bits(YAHTZEE)
        for face, rid in enumerate(YZ_ALL):
            legal, pts, bonus = solver_hasbro.options(mask, 0, 1, rid)
            assert legal_set(legal) == {face}
            assert pts[face] == 5 * (face + 1)
            assert bonus == 100


class TestVerhoeff:
    @pytest.mark.parametrize("yb", [0, 1])
    def test_face_open_normal_scores_no_forcing(self, solver_verhoeff, yb):
        legal, pts, bonus = solver_verhoeff.options(M_FOURS_OPEN, 0, yb, YZ4)
        assert legal_set(legal) == open_set(M_FOURS_OPEN)
        assert _pts(pts, M_FOURS_OPEN) == {c: NORMAL_4[c] for c in open_set(M_FOURS_OPEN)}
        assert bonus == 100 * yb
        assert solver_verhoeff.joker_situation(M_FOURS_OPEN, yb, YZ4) is None

    @pytest.mark.parametrize("yb", [0, 1])
    def test_face_filled_joker_values_everywhere(self, solver_verhoeff, yb):
        legal, pts, bonus = solver_verhoeff.options(M_FOURS_FILLED, 0, yb, YZ4)
        assert legal_set(legal) == open_set(M_FOURS_FILLED)
        assert _pts(pts, M_FOURS_FILLED) == {c: JOKER_4[c] for c in open_set(M_FOURS_FILLED)}
        assert bonus == 100 * yb
        assert solver_verhoeff.joker_situation(M_FOURS_FILLED, yb, YZ4) == "joker"

    @pytest.mark.parametrize("yb", [0, 1])
    def test_all_lower_filled(self, solver_verhoeff, yb):
        legal, pts, bonus = solver_verhoeff.options(M_LOWER_FILLED, 0, yb, YZ4)
        assert legal_set(legal) == {0, 1, 2}
        assert _pts(pts, M_LOWER_FILLED) == {0: 0, 1: 0, 2: 0}
        assert bonus == 100 * yb


class TestPlain:
    @pytest.mark.parametrize("mask", [M_FOURS_OPEN, M_FOURS_FILLED, M_LOWER_FILLED, M_BOX_OPEN])
    @pytest.mark.parametrize("rid", YZ_ALL)
    def test_never_a_bonus_never_joker_values(self, solver_plain, mask, rid):
        t = tables()
        for yb in ((0, 1) if (mask >> YAHTZEE) & 1 else (0,)):
            legal, pts, bonus = solver_plain.options(mask, 0, yb, rid)
            assert bonus == 0
            assert legal_set(legal) == open_set(mask)
            assert _pts(pts, mask) == {c: int(t.score[rid, c]) for c in open_set(mask)}
            assert solver_plain.joker_situation(mask, yb, rid) is None


def test_natural_yahtzee_scores_normally(preset_solver):
    _, s = preset_solver
    legal, pts, bonus = s.options(M_BOX_OPEN, 0, 0, YZ4)
    assert legal_set(legal) == open_set(M_BOX_OPEN)
    assert _pts(pts, M_BOX_OPEN) == {c: NORMAL_4[c] for c in open_set(M_BOX_OPEN)}
    assert pts[YAHTZEE] == 50 and pts[8] == 0 and pts[9] == 0 and pts[10] == 0
    assert bonus == 0
    assert s.joker_situation(M_BOX_OPEN, 0, YZ4) is None


def test_non_yahtzee_roll_with_box_at_50(preset_solver):
    _, s = preset_solver
    t = tables()
    rid = rid_of([4, 4, 4, 4, 2])
    for mask in (M_FOURS_OPEN, M_FOURS_FILLED):
        legal, pts, bonus = s.options(mask, 0, 1, rid)
        assert bonus == 0
        assert legal_set(legal) == open_set(mask)
        assert _pts(pts, mask) == {c: int(t.score[rid, c]) for c in open_set(mask)}
        assert s.joker_situation(mask, 1, rid) is None
    assert int(t.score[rid, 3]) == 16 and int(t.score[rid, 7]) == 18 and int(t.score[rid, 8]) == 0


def test_natural_yahtzee_full_house_house_rule(solver_natural_fh, solver_hasbro):
    s = solver_natural_fh
    assert s.rules.key == "custom_b100_hasbro_fh"
    legal, pts, bonus = s.options(M_BOX_OPEN, 0, 0, YZ4)
    assert legal_set(legal) == open_set(M_BOX_OPEN)
    assert pts[8] == 25 and pts[YAHTZEE] == 50 and pts[9] == 0 and pts[10] == 0
    assert bonus == 0
    # the Hasbro Joker rule is otherwise unchanged
    legal, pts, bonus = s.options(M_FOURS_OPEN, 0, 1, YZ4)
    assert legal_set(legal) == {FOURS} and bonus == 100
    # a strictly larger option set can never lower the value of any state; in fact the rule never
    # changes optimal play (50 in the Yahtzee box plus bonus eligibility always beats FH 25), so
    # the tables coincide. A real difference would show up at the 1e-3 level or above.
    assert s.fresh_ev >= solver_hasbro.fresh_ev
    assert np.abs(s.EV - solver_hasbro.EV).max() < 1e-9


def test_rules_validation_and_presets():
    with pytest.raises(ValueError):
        Rules(joker="bogus")
    with pytest.raises(ValueError):
        Rules(joker="Hasbro")
    with pytest.raises(ValueError):
        Rules(yahtzee_bonus=-1)
    assert Rules() == HASBRO
    assert PRESETS == {"hasbro": HASBRO, "verhoeff": VERHOEFF, "plain": PLAIN}
    assert [r.key for r in (HASBRO, VERHOEFF, PLAIN)] == ["hasbro", "verhoeff", "plain"]
    assert (HASBRO.joker_code, VERHOEFF.joker_code, PLAIN.joker_code) == (1, 2, 0)
    assert PLAIN.yahtzee_bonus == 0 and HASBRO.yahtzee_bonus == 100
    assert Rules(yahtzee_bonus=50).key == "custom_b50_hasbro_nofh"
