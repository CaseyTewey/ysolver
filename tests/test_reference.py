"""engine.py against the clean-room reference solver (tests/reference_solver.py).

The fast test uses tests/golden_states.json, 300 random states per preset sampled from the
reference tables (regenerate with tests/make_golden_states.py). The slow test re-solves every
preset and compares all 786,432 reachable states.
"""
import json
from pathlib import Path

import numpy as np
import pytest

from engine import FULL_MASK, YAHTZEE
from reference_solver import EXPECTED_FRESH_EV, PRESETS as REF_PRESETS, solve_reference

GOLDEN_PATH = Path(__file__).with_name("golden_states.json")
PRESET_NAMES = ("hasbro", "verhoeff", "plain")


@pytest.fixture(scope="module")
def golden() -> dict:
    return json.loads(GOLDEN_PATH.read_text())


def test_golden_file_is_well_formed(golden):
    assert set(golden["presets"]) == set(PRESET_NAMES) == set(REF_PRESETS)
    for name in PRESET_NAMES:
        g = golden["presets"][name]
        states = np.array(g["states"])
        assert states.shape == (300, 4)
        m, u, y = states[:, 0].astype(int), states[:, 1].astype(int), states[:, 2].astype(int)
        assert ((m >= 0) & (m <= FULL_MASK)).all() and ((u >= 0) & (u <= 63)).all()
        assert set(y.tolist()) <= {0, 1}
        assert (y[((m >> YAHTZEE) & 1) == 0] == 0).all()
        assert len({tuple(s[:3]) for s in states.astype(int).tolist()}) == 300
        assert abs(g["fresh_ev"] - EXPECTED_FRESH_EV[name]) < 1e-6


def test_engine_matches_golden_states(preset_solver, golden):
    name, s = preset_solver
    g = golden["presets"][name]
    assert abs(s.fresh_ev - g["fresh_ev"]) < 1e-9
    states = np.array(g["states"])
    m, u, y = states[:, 0].astype(int), states[:, 1].astype(int), states[:, 2].astype(int)
    diff = np.abs(s.EV[m, u, y] - states[:, 3])
    assert diff.max() < 1e-9, f"{name}: max diff {diff.max():.3e} at state {states[diff.argmax()]}"


def test_solve_reference_rejects_unknown_preset():
    with pytest.raises(ValueError):
        solve_reference("official")


@pytest.mark.slow
def test_full_tables_match_reference(preset_solver):
    name, s = preset_solver
    V = solve_reference(name)
    assert V.shape == (8192, 64, 2)
    assert abs(V[0, 0, 0] - EXPECTED_FRESH_EV[name]) < 1e-6
    yz = ((np.arange(FULL_MASK + 1) >> YAHTZEE) & 1) == 1
    d0 = np.abs(s.EV[:, :, 0] - V[:, :, 0])
    d1 = np.abs(s.EV[yz, :, 1] - V[yz, :, 1])
    assert d0.size + d1.size == 786_432
    assert max(d0.max(), d1.max()) < 1e-9, f"{name}: max diff yb0 {d0.max():.3e}, yb1 {d1.max():.3e}"
