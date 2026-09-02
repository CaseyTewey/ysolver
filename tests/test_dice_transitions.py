"""dice.py, transitions.py and the static tables behind engine.tables()."""
from math import comb, factorial, isclose

import numpy as np
import pytest

from dice import (
    counts_to_dice_list, dice_list_to_counts, enumerate_rolls, id_to_roll, multinomial_prob, roll_id,
)
from transitions import (
    compute_next_roll_dist, count_keeps, enumerate_keeps, get_keep_options, get_reroll_outcomes,
    get_transition_dist, precompute_all,
)
from engine import NUM_KEEPS, NUM_ROLLS, tables


# ----------------------------------------------------------------------------- dice.py
def test_252_unique_rolls():
    rolls = enumerate_rolls()
    assert len(rolls) == 252
    assert len(set(rolls)) == 252
    assert all(len(r) == 6 and sum(r) == 5 for r in rolls)


def test_roll_id_bijection():
    for i, counts in enumerate(enumerate_rolls()):
        assert roll_id(counts) == i
        assert id_to_roll(i) == counts


def test_multinomial_sums_to_one():
    total = sum(multinomial_prob(r) for r in enumerate_rolls())
    assert isclose(total, 1.0, rel_tol=1e-12)


def test_multinomial_specific_values():
    assert isclose(multinomial_prob((5, 0, 0, 0, 0, 0)), 1 / 7776, rel_tol=1e-12)
    assert isclose(multinomial_prob((1, 1, 1, 1, 1, 0)), 120 / 7776, rel_tol=1e-12)
    assert isclose(multinomial_prob((2, 2, 1, 0, 0, 0)), 30 / 7776, rel_tol=1e-12)
    assert isclose(multinomial_prob((0, 3, 0, 0, 0, 0)), 1 / 216, rel_tol=1e-12)
    assert multinomial_prob((0, 0, 0, 0, 0, 0)) == 1.0


def test_dice_list_conversion():
    dice = [1, 1, 3, 5, 6]
    counts = dice_list_to_counts(dice)
    assert counts == (2, 0, 1, 0, 1, 1)
    assert counts_to_dice_list(counts) == sorted(dice)


# ----------------------------------------------------------------------- transitions.py
def test_keep_count_matches_product_formula():
    counts = dice_list_to_counts([1, 1, 3, 5, 6])
    keeps = enumerate_keeps(counts)
    assert len(keeps) == 24 == count_keeps(counts)
    assert len(set(keeps)) == 24
    assert all(all(0 <= k <= c for k, c in zip(keep, counts)) for keep in keeps)


def test_keep_all_and_keep_none_are_options():
    counts = dice_list_to_counts([3, 3, 3, 4, 4])
    keeps = enumerate_keeps(counts)
    assert counts in keeps
    assert (0, 0, 0, 0, 0, 0) in keeps


def test_reroll_outcomes_sum_to_one():
    for n in range(6):
        outcomes = get_reroll_outcomes(n)
        assert len(outcomes) == comb(n + 5, 5)
        assert isclose(sum(p for _, p in outcomes), 1.0, rel_tol=1e-12)


def test_transition_rows_sum_to_one():
    precompute_all()
    rid = roll_id(dice_list_to_counts([1, 1, 3, 5, 6]))
    for keep in get_keep_options(rid):
        dist = get_transition_dist(rid, keep)
        assert isclose(sum(p for _, p in dist), 1.0, rel_tol=1e-12)
        assert all(all(a >= b for a, b in zip(id_to_roll(nid), keep)) for nid, _ in dist)


def test_keep_all_is_deterministic():
    counts = dice_list_to_counts([2, 2, 2, 3, 3])
    rid = roll_id(counts)
    dist = get_transition_dist(rid, counts)
    assert dist == [(rid, 1.0)]


# --------------------------------------------------------------------- engine.tables()
@pytest.fixture(scope="module")
def t():
    return tables()


def test_engine_rolls_match_dice_module(t):
    assert t.rolls.shape == (NUM_ROLLS, 6)
    assert [tuple(r) for r in t.rolls.tolist()] == enumerate_rolls()


def test_T_rows_sum_to_one(t):
    assert t.T.shape == (NUM_KEEPS, NUM_ROLLS)
    assert np.abs(t.T.sum(axis=1) - 1.0).max() < 1e-12
    assert (t.T >= 0).all()
    assert np.array_equal(t.Tt, t.T.T)


def test_462_keeps_unique_and_sized(t):
    assert t.keeps.shape == (462, 6)
    assert len({tuple(k) for k in t.keeps.tolist()}) == 462
    sizes = t.keeps.sum(axis=1)
    assert [int((sizes == s).sum()) for s in range(6)] == [comb(s + 5, 5) for s in range(6)]


def test_sub_multiset_index(t):
    assert t.sub_ptr.shape == (NUM_ROLLS + 1,)
    assert t.sub_ptr[0] == 0 and t.sub_ptr[-1] == 4368 == len(t.sub_idx)
    le = (t.keeps[None, :, :] <= t.rolls[:, None, :]).all(axis=-1)   # (252, 462)
    assert int(le.sum()) == 4368
    for r in range(NUM_ROLLS):
        ids = t.sub_idx[t.sub_ptr[r]:t.sub_ptr[r + 1]]
        assert np.array_equal(ids, np.nonzero(le[r])[0])   # exactly the sub-multisets, ascending


def test_keep_of_roll(t):
    assert np.array_equal(t.keeps[t.keep_of_roll], t.rolls)
    # keeping all five dice lands on the same roll with certainty
    assert np.all(t.T[t.keep_of_roll, np.arange(NUM_ROLLS)] == 1.0)


def test_P_sums_to_one_and_matches_dice_module(t):
    assert abs(t.P.sum() - 1.0) < 1e-12
    expected = np.array([multinomial_prob(tuple(r)) for r in t.rolls.tolist()])
    assert np.abs(t.P - expected).max() < 1e-15
    assert np.array_equal(t.T[0], t.P)   # keep nothing == first roll distribution


@pytest.mark.parametrize("keep", [(0, 0, 0, 0, 0, 0), (2, 0, 0, 0, 0, 0), (1, 1, 1, 0, 0, 0),
                                  (0, 0, 0, 0, 0, 5), (0, 2, 0, 2, 0, 0)])
def test_T_matches_transitions_module(t, keep):
    kid = [tuple(k) for k in t.keeps.tolist()].index(keep)
    row = np.zeros(NUM_ROLLS)
    for nid, p in compute_next_roll_dist(keep):
        row[nid] += p
    assert np.abs(t.T[kid] - row).max() < 1e-15


def test_T_matches_factorial_formula(t):
    keep_ids = {tuple(k): i for i, k in enumerate(t.keeps.tolist())}
    kid = keep_ids[(2, 0, 0, 0, 0, 0)]
    for target, d in [((2, 0, 0, 0, 0, 3), (0, 0, 0, 0, 0, 3)),
                      ((3, 1, 1, 0, 0, 0), (1, 1, 1, 0, 0, 0)),
                      ((2, 0, 2, 1, 0, 0), (0, 0, 2, 1, 0, 0))]:
        ways = factorial(3)
        for c in d:
            ways //= factorial(c)
        assert isclose(t.T[kid, roll_id(target)], ways / 6 ** 3, rel_tol=1e-12)
    assert t.T[kid, roll_id((1, 1, 1, 1, 1, 0))] == 0.0   # cannot lose a kept die


def test_six_yahtzee_rolls(t):
    assert int(t.is_yz.sum()) == 6
    assert t.yz_face[t.is_yz].tolist() == [5, 4, 3, 2, 1, 0]
    assert (t.yz_face[~t.is_yz] == -1).all()
    assert (t.rolls[t.is_yz].max(axis=1) == 5).all()
    for rid in np.nonzero(t.is_yz)[0]:
        assert t.score[rid, 11] == 50
        assert t.joker_score[rid, 8:11].tolist() == [25, 30, 40]
