"""Regenerate tests/golden_states.json from the clean-room reference solver.

    cd <repo> && .venv/bin/python tests/make_golden_states.py

Solves each preset with reference_solver.solve_reference (one to three minutes each, or
instant when YSOLVER_REF_CACHE points at a directory holding ref_<preset>.npy), then samples
300 random states per preset (yb=1 only when the Yahtzee box is filled) and records the fresh
value. The sample is fixed by SEED so the file is reproducible.
"""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from reference_solver import EXPECTED_FRESH_EV, PRESETS, solve_reference  # noqa: E402

SEED = 20260901
N_STATES = 300
YAHTZEE = 11
OUT = Path(__file__).with_name("golden_states.json")


def sample_states(V: np.ndarray, rng: np.random.Generator, n: int) -> list:
    seen = set()
    out = []
    while len(out) < n:
        mask = int(rng.integers(0, 8192))
        upper = int(rng.integers(0, 64))
        yb = int(rng.integers(0, 2)) if (mask >> YAHTZEE) & 1 else 0
        if (mask, upper, yb) in seen:
            continue
        seen.add((mask, upper, yb))
        out.append([mask, upper, yb, float(V[mask, upper, yb])])
    return out


def _dump(doc: dict) -> str:
    """JSON with one state per line, so diffs stay readable."""
    lines = ["{"]
    for key, val in doc.items():
        if key != "presets":
            lines.append(f"  {json.dumps(key)}: {json.dumps(val)},")
    lines.append('  "presets": {')
    names = list(doc["presets"])
    for i, name in enumerate(names):
        g = doc["presets"][name]
        lines.append(f"    {json.dumps(name)}: {{")
        lines.append(f'      "fresh_ev": {json.dumps(g["fresh_ev"])},')
        lines.append('      "states": [')
        for j, st in enumerate(g["states"]):
            lines.append("        " + json.dumps(st) + ("," if j < len(g["states"]) - 1 else ""))
        lines.append("      ]")
        lines.append("    }" + ("," if i < len(names) - 1 else ""))
    lines.append("  }")
    lines.append("}")
    return "\n".join(lines) + "\n"


def main() -> int:
    rng = np.random.default_rng(SEED)
    doc = {"source": "tests/reference_solver.py solve_reference (clean-room reference, independent of engine.py)",
           "seed": SEED, "states_per_preset": N_STATES, "state_format": ["mask", "upper", "yb", "ev_remaining"],
           "presets": {}}
    for name in PRESETS:
        V = solve_reference(name)
        fresh = float(V[0, 0, 0])
        if abs(fresh - EXPECTED_FRESH_EV[name]) > 1e-6:
            print(f"{name}: fresh EV {fresh:.6f} does not match {EXPECTED_FRESH_EV[name]}", file=sys.stderr)
            return 1
        doc["presets"][name] = {"fresh_ev": fresh, "states": sample_states(V, rng, N_STATES)}
        print(f"{name}: fresh EV {fresh:.6f}, {N_STATES} states sampled", flush=True)
    OUT.write_text(_dump(doc))
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
