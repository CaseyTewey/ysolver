"""Shared fixtures: one Solver per rule set for the whole session, and the 'slow' gate."""
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TESTS_DIR = Path(__file__).resolve().parent
for _p in (str(TESTS_DIR), str(ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from engine import Rules, Solver, PRESETS  # noqa: E402

TABLE_DIR = ROOT / "tables"
PRESET_NAMES = ("hasbro", "verhoeff", "plain")


def _make(name: str) -> Solver:
    return Solver(PRESETS[name], table_dir=TABLE_DIR, verbose=False)


@pytest.fixture(scope="session")
def solver_hasbro() -> Solver:
    return _make("hasbro")


@pytest.fixture(scope="session")
def solver_verhoeff() -> Solver:
    return _make("verhoeff")


@pytest.fixture(scope="session")
def solver_plain() -> Solver:
    return _make("plain")


@pytest.fixture(scope="session")
def solvers(solver_hasbro, solver_verhoeff, solver_plain) -> dict:
    return {"hasbro": solver_hasbro, "verhoeff": solver_verhoeff, "plain": solver_plain}


@pytest.fixture(scope="session", params=PRESET_NAMES)
def preset_solver(request, solvers):
    """(preset name, Solver), once per rule set."""
    return request.param, solvers[request.param]


@pytest.fixture(scope="session")
def solver_natural_fh(tmp_path_factory) -> Solver:
    """Hasbro rules plus the house rule 'a natural Yahtzee may score Full House 25'.

    Built into a temporary table directory (a few seconds) so the repo tables stay untouched.
    """
    table_dir = tmp_path_factory.mktemp("tables_natural_fh")
    return Solver(Rules(natural_yahtzee_fh=True), table_dir=table_dir, verbose=False)


def pytest_collection_modifyitems(config, items):
    if os.environ.get("YSOLVER_SLOW") == "1":
        return
    skip = pytest.mark.skip(reason="slow (minutes); set YSOLVER_SLOW=1 to run")
    for item in items:
        if "slow" in item.keywords:
            item.add_marker(skip)
