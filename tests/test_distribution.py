"""distribution.py: exact remaining-score PMFs under the optimal policy, and win probabilities."""
import numpy as np
import pytest

from distribution import (
    MAX_OPEN_FOR_EXACT, TooManyBoxesOpen, normal_win_probabilities, pmf_mean_var, pmf_remaining,
    pmf_stats, shift, win_probabilities,
)
from engine import FULL_MASK, max_remaining


def mask_open(*cats) -> int:
    m = FULL_MASK
    for c in cats:
        m &= ~(1 << c)
    return m


# (open boxes, upper, yb): 1 to 7 open boxes, both yb values, upper 63 included
STATES = [
    ((12,), 63, 1),
    ((5, 11), 33, 0),
    ((3, 8, 12), 40, 1),
    ((0, 6, 9, 12), 63, 0),
    ((1, 4, 7, 10, 12), 20, 1),
    ((2, 3, 6, 8, 9, 11), 15, 0),
    ((0, 1, 5, 7, 8, 10, 12), 27, 1),
]
IDS = [f"{len(o)}open_u{u}_yb{yb}" for o, u, yb in STATES]


@pytest.fixture(scope="module")
def pmfs(solver_hasbro) -> dict:
    return {(open_boxes, upper, yb): pmf_remaining(solver_hasbro, mask_open(*open_boxes), upper, yb)
            for open_boxes, upper, yb in STATES}


@pytest.mark.parametrize("state", STATES, ids=IDS)
def test_pmf_is_a_distribution_on_the_right_support(solver_hasbro, pmfs, state):
    open_boxes, upper, yb = state
    pmf = pmfs[state]
    assert abs(pmf.sum() - 1.0) < 1e-12
    assert (pmf >= 0).all()
    assert len(pmf) == max_remaining(solver_hasbro.rules, mask_open(*open_boxes), upper, yb) + 1
    if upper >= 63:                       # the 35 bonus is always collected once secured
        assert pmf[:35].sum() == 0.0


@pytest.mark.parametrize("state", STATES, ids=IDS)
def test_pmf_mean_and_variance_match_solver(solver_hasbro, pmfs, state):
    open_boxes, upper, yb = state
    mask = mask_open(*open_boxes)
    mean, var = pmf_mean_var(pmfs[state])
    assert abs(mean - solver_hasbro.ev(mask, upper, yb)) < 1e-9
    sv = solver_hasbro.variance(mask, upper, yb)
    assert abs(var - sv) <= 1e-9 * max(sv, 1.0)   # same tie-break as the tables, so M2 - EV^2 is exact


def test_pmf_stats_keys_and_order(pmfs):
    for pmf in pmfs.values():
        st = pmf_stats(pmf)
        assert set(st) == {"mean", "std", "p10", "p50", "p90", "mass"}
        assert abs(st["mass"] - 1.0) < 1e-12
        assert 0 <= st["p10"] <= st["p50"] <= st["p90"] < len(pmf)
        mean, var = pmf_mean_var(pmf)
        assert st["mean"] == mean and abs(st["std"] - var ** 0.5) < 1e-12


@pytest.mark.parametrize("preset", ["verhoeff", "plain"])
def test_pmf_other_presets(solvers, preset):
    s = solvers[preset]
    mask, upper, yb = mask_open(3, 8, 12), 40, 1
    pmf = pmf_remaining(s, mask, upper, yb)
    assert abs(pmf.sum() - 1.0) < 1e-12
    assert abs(pmf_mean_var(pmf)[0] - s.ev(mask, upper, yb)) < 1e-9


def test_terminal_pmfs(solver_hasbro):
    done = pmf_remaining(solver_hasbro, FULL_MASK, 63, 0)
    assert done.tolist() == [0.0] * 35 + [1.0]
    assert pmf_remaining(solver_hasbro, FULL_MASK, 62, 1).tolist() == [1.0]


def test_too_many_boxes_open(solver_hasbro):
    assert MAX_OPEN_FOR_EXACT == 7
    with pytest.raises(TooManyBoxesOpen):
        pmf_remaining(solver_hasbro, mask_open(0, 1, 2, 3, 4, 5, 6, 7), 0, 0)
    assert issubclass(TooManyBoxesOpen, ValueError)
    with pytest.raises(TooManyBoxesOpen):
        pmf_remaining(solver_hasbro, mask_open(0, 1, 2), 0, 0, max_open=2)


def test_win_probabilities_symmetric(pmfs):
    for pmf in pmfs.values():
        p_win, p_tie, p_lose = win_probabilities(pmf, 100, pmf, 100)
        assert abs(p_win - p_lose) < 1e-12
        assert abs(p_win + p_tie + p_lose - 1.0) < 1e-12
        assert p_tie > 0


def test_win_probabilities_ahead_by_200_is_certain(pmfs):
    state = ((0, 6, 9, 12), 63, 0)       # at most 5 + 30 + 30 + 30 + 35 = 130 points remain
    pmf = pmfs[state]
    assert len(pmf) - 1 <= 130
    p_win, p_tie, p_lose = win_probabilities(pmf, 300, pmf, 100)
    assert abs(p_win - 1.0) < 1e-12 and p_tie == 0.0 and p_lose < 1e-12
    p_win, p_tie, p_lose = win_probabilities(pmf, 100, pmf, 300)
    assert p_win == 0.0 and p_tie == 0.0 and abs(p_lose - 1.0) < 1e-12


def test_win_probabilities_match_outer_product(pmfs):
    f1 = pmfs[((3, 8, 12), 40, 1)]
    f2 = pmfs[((5, 11), 33, 0)]
    for l1, l2 in ((150, 120), (100, 180), (0, 0)):
        p_win, p_tie, p_lose = win_probabilities(f1, l1, f2, l2)
        assert abs(p_win + p_tie + p_lose - 1.0) < 1e-12
        i = np.arange(len(f1))[:, None] + l1
        j = np.arange(len(f2))[None, :] + l2
        joint = np.outer(f1, f2)
        assert abs(p_win - joint[i > j].sum()) < 1e-12
        assert abs(p_tie - joint[i == j].sum()) < 1e-12
        assert abs(p_lose - joint[i < j].sum()) < 1e-12


def test_normal_win_probabilities():
    assert normal_win_probabilities(200.0, 30.0, 200.0, 30.0) == (0.5, 0.0, 0.5)
    p_win, p_tie, p_lose = normal_win_probabilities(230.0, 30.0, 200.0, 40.0)
    assert 0.5 < p_win < 1.0 and p_tie == 0.0 and abs(p_win + p_lose - 1.0) < 1e-12
    assert normal_win_probabilities(10.0, 0.0, 5.0, 0.0) == (1.0, 0.0, 0.0)
    assert normal_win_probabilities(5.0, 0.0, 10.0, 0.0) == (0.0, 0.0, 1.0)
    assert normal_win_probabilities(5.0, 0.0, 5.0, 0.0) == (0.0, 1.0, 0.0)


def test_shift():
    pmf = np.array([0.25, 0.5, 0.25])
    out = shift(pmf, 10)
    assert len(out) == 13 and abs(out.sum() - 1.0) < 1e-15 and out[10:].tolist() == pmf.tolist()
    with pytest.raises(ValueError):
        shift(pmf, 2, 4)              # would drop probability mass: refused, never truncated
    assert shift(pmf, 0, 3).tolist() == pmf.tolist()


def test_pmf_variance_matches_table_on_random_states(solver_hasbro):
    """
    The precompute (2-D BLAS) and the runtime (1-D BLAS) reach keep values through different
    routines; TIE_TOL makes both pick the same keep on EV ties, so the exact distribution's
    variance must equal M2 - EV^2 everywhere, not just on the hand-picked STATES above.
    """
    import random
    from engine import FULL_MASK, YAHTZEE
    rng = random.Random(20260902)
    for _ in range(40):
        n_open = rng.choice([2, 3, 4, 5])
        mask = FULL_MASK
        for c in rng.sample(range(13), n_open):
            mask &= ~(1 << c)
        yb = rng.randint(0, 1) if (mask >> YAHTZEE) & 1 else 0
        upper = rng.choice([0, 12, 30, 45, 62, 63])
        mean, var = pmf_mean_var(pmf_remaining(solver_hasbro, mask, upper, yb))
        assert abs(mean - solver_hasbro.ev(mask, upper, yb)) < 1e-9
        sv = solver_hasbro.variance(mask, upper, yb)
        assert abs(var - sv) <= 1e-9 * max(sv, 1.0), (mask, upper, yb, var, sv)
