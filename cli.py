#!/usr/bin/env python3
"""
cli.py - command-line front end for the Yahtzee solver (engine.py + distribution.py).

    python cli.py recommend --dice 1,2,3,4,5 --rolls 2 [--scores '{"11": 50, "3": 12}']
    python cli.py ev [--scores ...]
    python cli.py pmf [--scores ...] [--locked N | --final] [--max-open 7]
    python cli.py match --p1 '{...}' --p2 '{...}' [--p1-bonuses N --p2-bonuses N] [--exact]
    python cli.py precompute [--force]
    python cli.py interactive [--scores ...]

Global options (before or after the subcommand): --rules {hasbro,verhoeff,plain}
(default hasbro), --json for machine-readable output, --table-dir DIR.

A scorecard is a JSON object mapping a box (index 0-12 or a name such as "sixes", "3k",
"fh", "yahtzee") to the points written in it; leave open boxes out. A value that starts
with @ names a file holding the JSON.

Accounting: expected_final = locked + bonus_chips * 100 + EV_remaining, where locked is
the sum of the box scores WITHOUT the 35 upper bonus. The engine's EV already contains
that 35 whenever the upper subtotal has reached 63, so when a displayed total includes
the earned bonus the displayed remaining EV has the 35 removed. The two always add up.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np

from dice import dice_list_to_counts, roll_id
from distribution import (
    MAX_OPEN_FOR_EXACT, TooManyBoxesOpen, normal_win_probabilities, pmf_remaining, pmf_stats,
    win_probabilities,
)
from engine import (
    DEFAULT_TABLE_DIR, FULL_MASK, NUM_CATS, PRESETS, Rules, ScoreState, Solver,
    YAHTZEE_SCORED, YAHTZEE_SCRATCHED, YAHTZEE_UNFILLED, parse_rolls_remaining, parse_scorecard,
)
from engine import parse_dice as engine_parse_dice
from scoring import CATEGORY_NAMES, UPPER_BONUS_THRESHOLD

RULES_DESCRIPTION = {
    "hasbro": "official Hasbro rules: forced Joker, 100-point Yahtzee bonus",
    "verhoeff": "Verhoeff variant: no forcing, Joker values once the matching upper box is filled",
    "plain": "no Yahtzee bonus, no Joker rule",
}
YAHTZEE_STATUS_TEXT = {YAHTZEE_UNFILLED: "open", YAHTZEE_SCRATCHED: "scratched (0)", YAHTZEE_SCORED: "scored 50"}
CATEGORY_ALIASES = {
    "aces": 0, "ones": 0, "twos": 1, "threes": 2, "fours": 3, "fives": 4, "sixes": 5,
    "3k": 6, "3oak": 6, "threeofakind": 6, "trips": 6,
    "4k": 7, "4oak": 7, "fourofakind": 7, "quads": 7,
    "fh": 8, "fullhouse": 8, "house": 8,
    "ss": 9, "smallstraight": 9, "small": 9,
    "ls": 10, "largestraight": 10, "large": 10,
    "y": 11, "yz": 11, "yahtzee": 11,
    "ch": 12, "chance": 12,
}
_NORMALISED_NAMES = [re.sub(r"[\s_\-]", "", n.lower()) for n in CATEGORY_NAMES]


class CliError(Exception):
    """A user-facing error: printed without a traceback, exit status 2."""


@dataclass
class Context:
    rules: Rules
    json: bool
    table_dir: Path
    _solver: Optional[Solver] = None

    def solver(self) -> Solver:
        """Load (or build) the table for the chosen rules once per process."""
        if self._solver is None:
            self._solver = Solver(self.rules, table_dir=self.table_dir, verbose=not self.json)
        return self._solver


# --------------------------------------------------------------------------------------
# Parsing helpers
# --------------------------------------------------------------------------------------
def resolve_category(token) -> int:
    """Map an index (0-12) or a box name / alias to the category index."""
    if isinstance(token, bool):
        raise CliError(f"invalid category {token!r}")
    if isinstance(token, int):
        idx = token
    else:
        s = str(token).strip().lower()
        if re.fullmatch(r"-?\d+", s):
            idx = int(s)
        else:
            key = re.sub(r"[\s_\-]", "", s)
            if key in CATEGORY_ALIASES:
                return CATEGORY_ALIASES[key]
            matches = [i for i, n in enumerate(_NORMALISED_NAMES) if key and n.startswith(key)]
            if len(matches) == 1:
                return matches[0]
            if not matches:
                raise CliError(f"unknown category {token!r}; use 0-12 or a name such as "
                               "sixes, 3k, 4k, fh, ss, ls, yahtzee, chance")
            raise CliError(f"ambiguous category {token!r}: " + ", ".join(CATEGORY_NAMES[i] for i in matches))
    if not 0 <= idx < NUM_CATS:
        raise CliError(f"category index {idx} out of range (0-12)")
    return idx


def load_scores(text: Optional[str]) -> ScoreState:
    """Parse a scorecard JSON string (or @file) into a validated ScoreState."""
    if text is None or not text.strip():
        return parse_scorecard({})
    raw = text.strip()
    if raw.startswith("@"):
        try:
            raw = Path(raw[1:]).read_text()
        except OSError as e:
            raise CliError(f"cannot read scores file: {e}")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise CliError("scores must be a JSON object such as '{\"11\": 50, \"3\": 12}' "
                       f"({e.msg} at column {e.colno})")
    if not isinstance(data, dict):
        raise CliError("scores must be a JSON object mapping a box (0-12 or name) to its points")
    normalised: Dict[int, object] = {}
    for k, v in data.items():
        if v is None:
            continue
        c = resolve_category(k)
        if c in normalised:
            raise CliError(f"box {CATEGORY_NAMES[c]} appears twice in the scorecard")
        normalised[c] = v
    try:
        return parse_scorecard(normalised)
    except ValueError as e:
        raise CliError(f"invalid scorecard: {e}")


def parse_dice_arg(text: str) -> List[int]:
    """Accept '1,2,3,4,5', '1 2 3 4 5' or '12345'."""
    s = text.strip().strip(",")
    parts = re.split(r"[,\s]+", s) if re.search(r"[,\s]", s) else list(s)
    try:
        dice = [int(p) for p in parts if p]
    except ValueError:
        raise CliError(f"dice must be five numbers from 1 to 6, got {text!r}")
    try:
        return engine_parse_dice(dice)
    except ValueError as e:
        raise CliError(f"{e} (got {text!r})")


def parse_rolls_arg(text) -> int:
    try:
        return parse_rolls_remaining(int(str(text).strip()))
    except ValueError:
        raise CliError(f"rolls left must be 0, 1 or 2, got {text!r}")


def check_bonuses(st: ScoreState, bonuses: int, label: str = "bonuses") -> None:
    """Chips only exist while the Yahtzee box holds 50, at most one per box filled after it."""
    if bonuses <= 0:
        return
    if st.yahtzee_status != YAHTZEE_SCORED:
        raise CliError(f"{label}: Yahtzee bonus chips need a Yahtzee box holding 50")
    if bonuses > len(st.filled) - 1:
        raise CliError(f"{label}: at most one bonus chip per box filled after the Yahtzee box")


def parse_bonuses_arg(value, label: str = "bonuses") -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise CliError(f"{label} must be a whole number of Yahtzee bonus chips")
    if n < 0 or n > 12:
        raise CliError(f"{label} must be between 0 and 12 bonus chips")
    return n


def rid_of(dice: List[int]) -> int:
    return roll_id(dice_list_to_counts(dice))


# --------------------------------------------------------------------------------------
# Output helpers
# --------------------------------------------------------------------------------------
def _jsonable(o):
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating):
        return float(o)
    if isinstance(o, np.bool_):
        return bool(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, Path):
        return str(o)
    raise TypeError(f"not JSON serialisable: {type(o).__name__}")


def emit_json(obj: dict) -> None:
    print(json.dumps(obj, indent=2, default=_jsonable))


def emit_error(msg: str, as_json: bool) -> None:
    if as_json:
        print(json.dumps({"ok": False, "error": msg}))
    else:
        print(f"error: {msg}", file=sys.stderr)


def state_summary(solver: Solver, st: ScoreState, bonuses: int = 0) -> dict:
    check_bonuses(st, bonuses)
    """Everything the text and JSON views need about one scorecard."""
    ev = solver.ev(st.mask, st.upper, st.yb)
    std = solver.std(st.mask, st.upper, st.yb)
    chips_points = bonuses * solver.rules.yahtzee_bonus
    return {
        "rules": solver.rules.key,
        "game_over": st.mask == FULL_MASK,
        "boxes_open": st.boxes_remaining,
        "open_boxes": [CATEGORY_NAMES[c] for c in st.open_boxes],
        "upper_subtotal": st.upper_raw,
        "upper_bonus_earned": st.upper_bonus_earned,
        "yahtzee_status": YAHTZEE_STATUS_TEXT[st.yahtzee_status],
        "yahtzee_bonus_chips": bonuses,
        "yahtzee_bonus_points": chips_points,
        "locked": st.locked,
        "current_total": st.locked + st.upper_bonus_earned + chips_points,
        "ev_remaining": ev,
        "ev_remaining_after_earned_bonus": ev - st.upper_bonus_earned,
        "std_remaining": std,
        "expected_final": st.locked + chips_points + ev,
    }


def summarise(solver: Solver, scores: Optional[str], bonuses: int = 0) -> Tuple[ScoreState, dict]:
    st = load_scores(scores)
    return st, state_summary(solver, st, bonuses)


def format_state(summary: dict, label: Optional[str] = None) -> List[str]:
    """Human-readable lines describing a scorecard state."""
    head = f"{label}: " if label else ""
    open_txt = ", ".join(summary["open_boxes"]) if summary["open_boxes"] else "none"
    n = summary["boxes_open"]
    lines = [f"{head}{n} {'box' if n == 1 else 'boxes'} open ({open_txt})"]
    bonus_txt = ("earned" if summary["upper_bonus_earned"] else
                 f"needs {UPPER_BONUS_THRESHOLD - summary['upper_subtotal']} more")
    lines.append(f"  Upper subtotal {summary['upper_subtotal']}/{UPPER_BONUS_THRESHOLD} (35 bonus {bonus_txt})"
                 f"    Yahtzee box: {summary['yahtzee_status']}"
                 f"    bonus chips: {summary['yahtzee_bonus_chips']}")
    if summary["game_over"]:
        lines.append(f"  Game over. Final total {summary['current_total']}")
    else:
        lines.append(f"  Score so far {summary['current_total']}    "
                     f"expected remaining {summary['ev_remaining_after_earned_bonus']:.2f} "
                     f"(std {summary['std_remaining']:.2f})    "
                     f"expected final {summary['expected_final']:.2f}")
    return lines


def joker_note(rec: dict, rules: Rules) -> Optional[str]:
    """One sentence on how the Yahtzee bonus / Joker rule applies to this roll."""
    if not rec["is_yahtzee_roll"]:
        return None
    parts = []
    if rec.get("joker_bonus"):
        parts.append(f"+{rec['joker_bonus']} Yahtzee bonus (the Yahtzee box holds 50)")
    situation = rec["joker_rule"]
    if rec["yahtzee_status"] == YAHTZEE_UNFILLED:
        parts.append("the Yahtzee box is open, so this is a natural 50 if you take it")
    elif situation == "forced_upper":
        parts.append(f"Hasbro Joker rule: the matching upper box ({rec['forced_category_name']}) "
                     "is open, so the roll MUST be scored there")
    elif situation == "lower_only":
        parts.append("Hasbro Joker rule: matching upper box filled, so an open lower box must be used "
                     "at Joker values (FH 25, SS 30, LS 40, 3K/4K/Chance = dice total)")
    elif situation == "zero_upper":
        parts.append("Hasbro Joker rule: only upper boxes remain and the matching one is filled, "
                     "so the roll scores 0 in an open upper box")
    elif situation == "joker":
        parts.append("Verhoeff Joker: Yahtzee box and matching upper box both filled, so FH/SS/LS "
                     "score 25/30/40 and nothing is forced")
    elif rules.joker == "verhoeff":
        parts.append("Verhoeff variant: matching upper box still open, so boxes score their normal "
                     "values and nothing is forced")
    elif rules.joker == "none":
        parts.append("plain rules: no Joker, the extra Yahtzee scores at normal values")
    if rec["yahtzee_status"] == YAHTZEE_SCRATCHED and rules.yahtzee_bonus:
        parts.append("no bonus because the Yahtzee box holds 0")
    return "; ".join(parts) if parts else None


def multiset_diff(dice: List[int], keep_counts) -> List[int]:
    counts = list(dice_list_to_counts(dice))
    return [f + 1 for f in range(6) for _ in range(counts[f] - keep_counts[f])]


def format_recommendation(rec: dict, summary: dict, rules: Rules, max_rows: Optional[int] = None) -> List[str]:
    """Text view of Solver.recommend output."""
    base = summary["locked"] + summary["yahtzee_bonus_points"]   # final = base + EV (EV carries the 35)
    lines = [f"Dice {' '.join(map(str, rec['dice']))}    rolls left {rec['rolls_remaining']}"]
    options = rec["category_options"]
    best = options[0]
    if rec["action"] == "score":
        lines.append(f"SCORE {best['name']} for {best['points']} points"
                     + (f" (+{best['bonus']} bonus)" if best["bonus"] else ""))
        lines.append(f"  expected final {base + rec['expected_value']:.2f}")
    elif rec["keep_all"]:
        lines.append(f"STOP ROLLING and score {best['name']} for {best['points']} points"
                     + (f" (+{best['bonus']} bonus)" if best["bonus"] else ""))
        lines.append(f"  expected final {base + rec['expected_value']:.2f}")
    else:
        keep = rec["keep_dice"]
        reroll = multiset_diff(rec["dice"], rec["keep_counts"])
        keep_txt = " ".join(map(str, keep)) if keep else "nothing"
        lines.append(f"KEEP {keep_txt}, reroll {' '.join(map(str, reroll))}")
        lines.append(f"  expected final {base + rec['expected_value']:.2f}"
                     f"    (stopping now: {best['name']} for {best['points']}, "
                     f"expected final {base + best['expected_value']:.2f})")
    note = joker_note(rec, rules)
    if note:
        lines.append(f"  Joker rule: {note}")
    lines.append("")
    lines.append(f"  {'Box':<17}{'Pts':>5}{'Exp. final':>12}")
    rows = options if max_rows is None else options[:max_rows]
    for i, o in enumerate(rows):
        mark = "*" if i == 0 else " "
        tag = "  forced" if o["is_forced"] else ""
        lines.append(f"{mark} {o['name']:<17}{o['points']:>5}{base + o['expected_value']:>12.2f}{tag}")
    if max_rows is not None and len(options) > max_rows:
        lines.append(f"  ... {len(options) - max_rows} more")
    return lines


def histogram(pmf: np.ndarray, offset: int = 0, max_bins: int = 20) -> dict:
    """Equal-width bins over the central 99.8% of the mass; tails reported separately."""
    cdf = np.cumsum(pmf)
    nz = np.flatnonzero(pmf > 1e-15)
    lo = max(int(np.searchsorted(cdf, 0.001)), int(nz[0]))
    hi = min(max(int(np.searchsorted(cdf, 0.999)), lo), int(nz[-1]))
    span = hi - lo + 1
    width = next((w for w in (1, 2, 5, 10, 20, 25, 50, 100) if math.ceil(span / w) <= max_bins), None)
    if width is None:
        width = math.ceil(span / max_bins)
    first = ((lo + offset) // width) * width - offset
    bins = []
    a = first
    while a <= hi:
        b = a + width - 1
        mass = float(pmf[max(a, 0):min(b + 1, len(pmf))].sum())
        bins.append({"from": a + offset, "to": b + offset, "p": mass})
        a += width
    last_b = min(bins[-1]["to"] - offset, len(pmf) - 1)
    below = float(cdf[first - 1]) if first > 0 else 0.0
    above = float(1.0 - cdf[last_b]) if last_b < len(pmf) - 1 else 0.0
    return {"width": width, "bins": bins, "p_below": max(below, 0.0), "p_above": max(above, 0.0)}


def format_histogram(h: dict, bar_width: int = 40) -> List[str]:
    peak = max(b["p"] for b in h["bins"]) or 1.0
    lines = []
    if h["p_below"] > 5e-4:
        lines.append(f"  {'below':>9} | {'':<{bar_width}} {100 * h['p_below']:5.1f}%")
    for b in h["bins"]:
        label = str(b["from"]) if h["width"] == 1 else f"{b['from']}-{b['to']}"
        bar = "#" * int(round(b["p"] / peak * bar_width))
        lines.append(f"  {label:>9} | {bar:<{bar_width}} {100 * b['p']:5.1f}%")
    if h["p_above"] > 5e-4:
        lines.append(f"  {'above':>9} | {'':<{bar_width}} {100 * h['p_above']:5.1f}%")
    return lines


# --------------------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------------------
def cmd_recommend(args, ctx: Context) -> int:
    dice = parse_dice_arg(args.dice)
    rolls = parse_rolls_arg(args.rolls)
    bonuses = parse_bonuses_arg(args.bonuses)
    solver = ctx.solver()
    st, summary = summarise(solver, args.scores, bonuses)
    if st.mask == FULL_MASK:
        raise CliError("every box is filled; the game is over")
    rec = solver.recommend(dice, st.mask, st.upper, st.yahtzee_status, rolls)
    if ctx.json:
        rec["joker_note"] = joker_note(rec, solver.rules)
        rec["state"] = summary
        rec["expected_final"] = summary["locked"] + summary["yahtzee_bonus_points"] + rec["expected_value"]
        emit_json({"ok": True, **rec})
        return 0
    print(f"Rules: {solver.rules.key} ({RULES_DESCRIPTION.get(solver.rules.key, 'custom')})")
    print("\n".join(format_state(summary)))
    print()
    print("\n".join(format_recommendation(rec, summary, solver.rules)))
    return 0


def cmd_ev(args, ctx: Context) -> int:
    bonuses = parse_bonuses_arg(args.bonuses)
    solver = ctx.solver()
    st, summary = summarise(solver, args.scores, bonuses)
    if ctx.json:
        emit_json({"ok": True, **summary, "fresh_game_ev": solver.fresh_ev,
                   "fresh_game_std": solver.std(0, 0, 0)})
        return 0
    print(f"Rules: {solver.rules.key} ({RULES_DESCRIPTION.get(solver.rules.key, 'custom')})")
    print("\n".join(format_state(summary)))
    if st.mask == 0:
        print(f"  Fresh game: expected final {solver.fresh_ev:.6f}, std {solver.std(0, 0, 0):.4f}")
    return 0


def _exact_pmf(solver: Solver, st: ScoreState, max_open: int, who: str = "") -> np.ndarray:
    try:
        return pmf_remaining(solver, st.mask, st.upper, st.yb, max_open=max_open)
    except TooManyBoxesOpen as e:
        prefix = f"{who}: " if who else ""
        raise CliError(f"{prefix}{e}. Raise --max-open (each extra box costs a few times more), "
                       "or use 'ev' for the exact mean and std of this state.")


def cmd_pmf(args, ctx: Context) -> int:
    bonuses = parse_bonuses_arg(args.bonuses)
    if args.max_open < 0 or args.max_open > NUM_CATS:
        raise CliError("--max-open must be between 0 and 13")
    if args.locked is not None and args.final:
        raise CliError("give either --locked N or --final, not both")
    solver = ctx.solver()
    st, summary = summarise(solver, args.scores, bonuses)
    if args.locked is not None:
        if args.locked < 0:
            raise CliError("--locked must be >= 0")
        offset, what = args.locked, "final"
    elif args.final:
        offset, what = st.locked + summary["yahtzee_bonus_points"], "final"
    else:
        # the raw PMF carries the 35 upper bonus; once earned it is already in "score so far"
        offset, what = -st.upper_bonus_earned, "remaining"
    t0 = time.time()
    pmf = _exact_pmf(solver, st, args.max_open)
    elapsed = time.time() - t0
    stats = pmf_stats(pmf)
    nz = np.flatnonzero(pmf > 1e-15)
    support = [int(nz[0]) + offset, int(nz[-1]) + offset]
    shifted = {"mean": stats["mean"] + offset, "std": stats["std"], "p10": stats["p10"] + offset,
               "p50": stats["p50"] + offset, "p90": stats["p90"] + offset, "mass": stats["mass"]}
    hist = histogram(pmf, offset)
    if ctx.json:
        emit_json({"ok": True, "state": summary, "distribution_of": what, "offset": offset,
                   "stats": shifted, "support": support, "histogram": hist,
                   "ev_check": {"table_mean": summary["ev_remaining"], "table_std": summary["std_remaining"]},
                   "seconds": elapsed, "pmf": pmf[:int(nz[-1]) + 1]})
        return 0
    print(f"Rules: {solver.rules.key} ({RULES_DESCRIPTION.get(solver.rules.key, 'custom')})")
    print("\n".join(format_state(summary)))
    print()
    label = "final score" if what == "final" else "remaining score"
    if what == "final":
        extra = f" ({offset} banked points added)"
    elif offset:
        extra = f" (the earned {-offset} upper bonus is counted in the score so far, not here)"
    else:
        extra = ""
    print(f"Exact distribution of the {label} under optimal play{extra}, {elapsed:.2f}s")
    print(f"  mean {shifted['mean']:.2f}    std {shifted['std']:.2f}    "
          f"p10 {shifted['p10']}    p50 {shifted['p50']}    p90 {shifted['p90']}    "
          f"range {support[0]}-{support[1]}")
    print("\n".join(format_histogram(hist)))
    return 0


def cmd_match(args, ctx: Context) -> int:
    b1 = parse_bonuses_arg(args.p1_bonuses, "--p1-bonuses")
    b2 = parse_bonuses_arg(args.p2_bonuses, "--p2-bonuses")
    if args.max_open < 0 or args.max_open > NUM_CATS:
        raise CliError("--max-open must be between 0 and 13")
    solver = ctx.solver()
    try:
        st1, s1 = summarise(solver, args.p1, b1)
    except CliError as e:
        raise CliError(f"--p1: {e}")
    try:
        st2, s2 = summarise(solver, args.p2, b2)
    except CliError as e:
        raise CliError(f"--p2: {e}")
    locked1 = st1.locked + s1["yahtzee_bonus_points"]
    locked2 = st2.locked + s2["yahtzee_bonus_points"]
    t0 = time.time()
    if args.exact:
        pmf1 = _exact_pmf(solver, st1, args.max_open, "player 1")
        pmf2 = _exact_pmf(solver, st2, args.max_open, "player 2")
        p_win, p_tie, p_lose = win_probabilities(pmf1, locked1, pmf2, locked2)
        method = "exact"
    else:
        p_win, p_tie, p_lose = normal_win_probabilities(s1["expected_final"], s1["std_remaining"],
                                                        s2["expected_final"], s2["std_remaining"])
        method = "normal"
    elapsed = time.time() - t0
    if ctx.json:
        emit_json({"ok": True, "rules": solver.rules.key, "method": method, "seconds": elapsed,
                   "p1": s1, "p2": s2, "p_win": p_win, "p_tie": p_tie, "p_lose": p_lose})
        return 0
    print(f"Rules: {solver.rules.key} ({RULES_DESCRIPTION.get(solver.rules.key, 'custom')})")
    print("\n".join(format_state(s1, "Player 1")))
    print("\n".join(format_state(s2, "Player 2")))
    print()
    how = ("exact score distributions" if method == "exact"
           else "normal approximation from the exact means and standard deviations; ties not modelled")
    print(f"Player 1 wins {100 * p_win:.1f}%    tie {100 * p_tie:.1f}%    Player 2 wins {100 * p_lose:.1f}%")
    print(f"  ({how}, {elapsed:.2f}s)")
    return 0


def cmd_precompute(args, ctx: Context) -> int:
    rules = ctx.rules
    path = ctx.table_dir / f"ev_{rules.key}.npz"
    try:
        ctx.table_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise CliError(f"cannot use table directory {ctx.table_dir}: {e}")
    solver: Optional[Solver] = None
    action = "loaded"
    t0 = time.time()
    if not args.force:
        try:
            solver = Solver(rules, table_dir=ctx.table_dir, build_if_missing=False, verbose=False)
        except FileNotFoundError:
            solver = None
    if solver is None:
        backup = None
        if path.exists():
            backup = path.with_name(path.name + ".bak")
            path.replace(backup)
        try:
            if not ctx.json:
                print(f"Building tables for rules {rules.key} into {path} ...", flush=True)
            solver = Solver(rules, table_dir=ctx.table_dir, verbose=False)
        except BaseException:
            if backup is not None and backup.exists() and not path.exists():
                backup.replace(path)
            raise
        if backup is not None and backup.exists():
            backup.unlink()
        action = "built"
    elapsed = time.time() - t0
    fresh_std = solver.std(0, 0, 0)
    size_mb = path.stat().st_size / 1e6 if path.exists() else 0.0
    if ctx.json:
        emit_json({"ok": True, "rules": rules.key, "action": action, "table": path, "size_mb": size_mb,
                   "fresh_ev": solver.fresh_ev, "fresh_std": fresh_std, "seconds": elapsed})
        return 0
    print(f"rules={rules.key}  {action}  table={path} ({size_mb:.1f} MB)  {elapsed:.1f}s")
    print(f"fresh-game expected score {solver.fresh_ev:.6f}   std {fresh_std:.4f}")
    return 0


# --------------------------------------------------------------------------------------
# Interactive session
# --------------------------------------------------------------------------------------
INTERACTIVE_HELP = """Commands
  <dice> [rolls]     e.g. '1 1 3 5 6', '11356 1' or '1,1,3,5,6 0'. Rolls left defaults
                     to 2 for the first dice of a turn, then counts down.
  score <box> [pts]  write the turn into a box, e.g. 'score 3k' (points taken from the
                     last dice entered) or 'score chance 23'. Boxes: 0-12 or names
                     (ones..sixes, 3k, 4k, fh, ss, ls, yahtzee, chance). 'zero <box>' too.
  card               show the scorecard
  ev                 expected remaining score and standard deviation
  undo               take back the last score
  bonus N            set the number of Yahtzee bonus chips already earned
  help               this text
  quit               leave"""


class Interactive:
    """Simple turn loop: enter dice and rolls left, get advice, enter what you scored."""

    def __init__(self, solver: Solver, card: Dict[int, int], bonuses: int,
                 out: Callable[[str], None] = print):
        self.solver = solver
        self.card = dict(card)
        self.bonuses = bonuses
        self.out = out
        self.history: List[Tuple[Dict[int, int], int]] = []
        self.rolls_left: Optional[int] = None      # None: a new turn starts with the next dice
        self.last: Optional[Tuple[List[int], int]] = None   # (dice, rolls left) of the last advice

    # ----- state -----
    def state(self) -> ScoreState:
        return parse_scorecard(self.card)

    def summary(self) -> dict:
        return state_summary(self.solver, self.state(), self.bonuses)

    def game_over(self) -> bool:
        return self.state().mask == FULL_MASK

    def show_state(self) -> None:
        self.out("\n".join(format_state(self.summary())))

    def show_card(self) -> None:
        st = self.state()
        for c, name in enumerate(CATEGORY_NAMES):
            pts = self.card.get(c)
            self.out(f"  {c:>2}  {name:<17}{'-' if pts is None else pts:>4}")
            if c == 5:
                self.out(f"      {'Upper subtotal':<17}{st.upper_raw:>4}/{UPPER_BONUS_THRESHOLD}"
                         f"   bonus {st.upper_bonus_earned}")
        chips = self.bonuses * self.solver.rules.yahtzee_bonus
        self.out(f"      {'Yahtzee bonus':<17}{chips:>4}   ({self.bonuses} chips)")
        self.out(f"      {'Total':<17}{st.locked + st.upper_bonus_earned + chips:>4}")

    # ----- actions -----
    def advise(self, dice: List[int], rolls: Optional[int]) -> None:
        st = self.state()
        if st.mask == FULL_MASK:
            raise CliError("every box is filled; the game is over")
        if rolls is None:
            rolls = 2 if self.rolls_left is None else max(0, self.rolls_left - 1)
        rec = self.solver.recommend(dice, st.mask, st.upper, st.yahtzee_status, rolls)
        summary = state_summary(self.solver, st, self.bonuses)
        self.out("\n".join(format_recommendation(rec, summary, self.solver.rules, max_rows=6)))
        self.rolls_left = rolls
        self.last = (dice, rolls)
        if rolls == 0 or rec.get("keep_all"):
            self.out("  (enter 'score <box>' to write it down)")

    def score(self, tokens: List[str], zero: bool = False) -> None:
        if not tokens:
            raise CliError("usage: score <box> [points]")
        c = resolve_category(tokens[0])
        if c in self.card:
            raise CliError(f"{CATEGORY_NAMES[c]} is already filled with {self.card[c]}")
        st = self.state()
        bonus_earned = 0
        if zero:
            pts = 0
        elif len(tokens) > 1:
            try:
                pts = int(tokens[1])
            except ValueError:
                raise CliError(f"points must be a whole number, got {tokens[1]!r}")
        elif self.last is not None:
            dice, _ = self.last
            legal, pts_arr, bonus = self.solver.options(st.mask, st.upper, st.yb, rid_of(dice))
            if not legal[c]:
                forced = [CATEGORY_NAMES[i] for i in range(NUM_CATS) if legal[i]]
                raise CliError(f"with {' '.join(map(str, dice))} the Joker rule does not allow "
                               f"{CATEGORY_NAMES[c]}; allowed: {', '.join(forced)}. "
                               "Give the points explicitly to override.")
            pts = int(pts_arr[c])
        else:
            raise CliError("no dice entered this turn; give the points: score <box> <points>")
        if self.last is not None and self.solver.rules.yahtzee_bonus and st.yb:
            dice, _ = self.last
            if len(set(dice)) == 1:
                bonus_earned = 1
        new_card = dict(self.card)
        new_card[c] = pts
        try:
            parse_scorecard(new_card)
        except ValueError as e:
            raise CliError(str(e))
        self.history.append((dict(self.card), self.bonuses))
        self.card = new_card
        self.bonuses += bonus_earned
        self.rolls_left = None
        self.last = None
        msg = f"Scored {pts} in {CATEGORY_NAMES[c]}."
        if bonus_earned:
            msg += f" Yahtzee bonus chip +{self.solver.rules.yahtzee_bonus} (now {self.bonuses})."
        self.out(msg)
        self.show_state()

    def undo(self) -> None:
        if not self.history:
            raise CliError("nothing to undo")
        self.card, self.bonuses = self.history.pop()
        self.rolls_left = None
        self.last = None
        self.out("Undone.")
        self.show_state()

    # ----- dispatch -----
    def handle(self, line: str) -> bool:
        """Process one input line. Returns False when the session should end."""
        tokens = line.strip().split()
        if not tokens:
            return True
        cmd = tokens[0].lower()
        if cmd in ("quit", "exit", "q"):
            return False
        if cmd in ("help", "h", "?"):
            self.out(INTERACTIVE_HELP)
        elif cmd in ("card", "c"):
            self.show_card()
        elif cmd in ("ev", "state"):
            self.show_state()
        elif cmd in ("undo", "u"):
            self.undo()
        elif cmd in ("score", "s"):
            self.score(tokens[1:])
        elif cmd in ("zero", "scratch", "z"):
            self.score(tokens[1:], zero=True)
        elif cmd == "bonus":
            if len(tokens) != 2:
                raise CliError("usage: bonus N")
            n = parse_bonuses_arg(tokens[1])
            check_bonuses(self.state(), n)
            self.bonuses = n
            self.show_state()
        else:
            self.dice_line(tokens)
        return not self.game_over()

    def dice_line(self, tokens: List[str]) -> None:
        """'1 1 3 5 6', '11356', '1,1,3,5,6', each optionally followed by the rolls left."""
        text = " ".join(tokens)
        rolls_token: Optional[str] = None
        if len(tokens) == 6:
            text, rolls_token = " ".join(tokens[:5]), tokens[5]
        elif len(tokens) == 2:
            text, rolls_token = tokens[0], tokens[1]
        elif len(tokens) not in (1, 5):
            raise CliError(f"unrecognised input {' '.join(tokens)!r}; type 'help' for the commands")
        try:
            dice = parse_dice_arg(text)
        except CliError:
            raise CliError(f"unrecognised input {' '.join(tokens)!r}; type 'help' for the commands")
        rolls = parse_rolls_arg(rolls_token.lstrip("rR")) if rolls_token is not None else None
        self.advise(dice, rolls)

    def run(self, prompt_in: Callable[[str], str] = input) -> int:
        self.out(f"Yahtzee solver, rules {self.solver.rules.key} "
                 f"({RULES_DESCRIPTION.get(self.solver.rules.key, 'custom')}). Type 'help' for commands.")
        self.show_state()
        if self.game_over():
            return 0
        while True:
            if self.rolls_left is None:
                prompt = f"[turn {len(self.card) + 1}, new roll] > "
            else:
                prompt = f"[turn {len(self.card) + 1}, {self.rolls_left} roll{'s' if self.rolls_left != 1 else ''} left] > "
            try:
                line = prompt_in(prompt)
            except EOFError:
                self.out("")
                return 0
            try:
                if not self.handle(line):
                    break
            except CliError as e:
                self.out(f"error: {e}")
            except ValueError as e:
                self.out(f"error: {e}")
        if self.game_over():
            s = self.summary()
            self.out(f"Game complete. Final total {s['current_total']}.")
        return 0


def cmd_interactive(args, ctx: Context) -> int:
    bonuses = parse_bonuses_arg(args.bonuses)
    card = scores_dict(args.scores)
    solver = ctx.solver()
    if ctx.json:
        print("note: --json is ignored by interactive mode", file=sys.stderr)
    return Interactive(solver, card, bonuses).run()


def scores_dict(text: Optional[str]) -> Dict[int, int]:
    """The validated {category: points} dict behind a --scores value."""
    if load_scores(text).filled == ():
        return {}
    raw = text.strip()
    if raw.startswith("@"):
        raw = Path(raw[1:]).read_text()
    return {resolve_category(k): int(v) for k, v in json.loads(raw).items() if v is not None}


# --------------------------------------------------------------------------------------
# Argument parsing
# --------------------------------------------------------------------------------------
_JSON_ERRORS = False      # set by main(): argparse errors become {"ok": false, "error": ...} on stdout


class _Parser(argparse.ArgumentParser):
    """argparse parser whose usage errors honour --json."""

    def error(self, message):
        if _JSON_ERRORS:
            print(json.dumps({"ok": False, "error": message}), flush=True)
            self.exit(2)
        super().error(message)


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--rules", choices=sorted(PRESETS), default=argparse.SUPPRESS,
                        help="rule set: hasbro (default), verhoeff or plain")
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS,
                        help="machine-readable JSON output")
    common.add_argument("--table-dir", default=argparse.SUPPRESS, metavar="DIR",
                        help="directory holding the ev_<rules>.npz tables")
    scores_help = ("scorecard as JSON, e.g. '{\"11\": 50, \"3\": 12}' (box index or name to points; "
                   "@file reads a file). Default: fresh game")
    bonuses_help = "Yahtzee bonus chips already earned (100 points each)"

    p = _Parser(
        prog="cli.py", description="Optimal-play Yahtzee solver: advice, expectations, distributions.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""examples
  python cli.py recommend --dice 1,1,3,5,6 --rolls 2
  python cli.py recommend --dice 6,6,6,6,6 --rolls 0 --scores '{"yahtzee": 50, "3": 12}'
  python cli.py ev --scores '{"0": 3, "1": 6, "2": 9}'
  python cli.py pmf --scores '{"0":3,"1":6,"2":9,"3":12,"4":15,"5":18}' --final
  python cli.py match --p1 '{"11": 50, "3": 12}' --p2 '{"11": 0}' --p1-bonuses 1
  python cli.py --rules plain precompute
  python cli.py interactive""")
    p.add_argument("--rules", choices=sorted(PRESETS), default="hasbro",
                   help="rule set: hasbro (default), verhoeff or plain")
    p.add_argument("--json", action="store_true", default=False, help="machine-readable JSON output")
    p.add_argument("--table-dir", default=None, metavar="DIR",
                   help="directory holding the ev_<rules>.npz tables")
    sub = p.add_subparsers(dest="command", metavar="command", parser_class=_Parser)

    r = sub.add_parser("recommend", parents=[common], help="best keep or box for the current dice")
    r.add_argument("--dice", required=True, help="five dice, e.g. 1,1,3,5,6 or 11356")
    r.add_argument("--rolls", required=True, help="rolls left after this one: 2, 1 or 0")
    r.add_argument("--scores", default=None, help=scores_help)
    r.add_argument("--bonuses", default=0, help=bonuses_help)
    r.set_defaults(func=cmd_recommend)

    e = sub.add_parser("ev", parents=[common], help="expected remaining score and std for a scorecard")
    e.add_argument("--scores", default=None, help=scores_help)
    e.add_argument("--bonuses", default=0, help=bonuses_help)
    e.set_defaults(func=cmd_ev)

    d = sub.add_parser("pmf", parents=[common], help="exact distribution of the remaining or final score")
    d.add_argument("--scores", default=None, help=scores_help)
    d.add_argument("--bonuses", default=0, help=bonuses_help)
    d.add_argument("--locked", type=int, default=None, metavar="N",
                   help="points already banked (without the 35 upper bonus): show the FINAL score")
    d.add_argument("--final", action="store_true", help="like --locked with the scorecard's own banked points")
    d.add_argument("--max-open", type=int, default=MAX_OPEN_FOR_EXACT, metavar="K",
                   help=f"refuse states with more than K open boxes (default {MAX_OPEN_FOR_EXACT})")
    d.set_defaults(func=cmd_pmf)

    m = sub.add_parser("match", parents=[common], help="win / tie / lose probabilities for two players")
    m.add_argument("--p1", required=True, help="player 1 scorecard JSON")
    m.add_argument("--p2", required=True, help="player 2 scorecard JSON")
    m.add_argument("--p1-bonuses", default=0, help="player 1 Yahtzee bonus chips")
    m.add_argument("--p2-bonuses", default=0, help="player 2 Yahtzee bonus chips")
    m.add_argument("--exact", action="store_true",
                   help="use the exact score distributions (each player at most --max-open open boxes)")
    m.add_argument("--max-open", type=int, default=MAX_OPEN_FOR_EXACT, metavar="K",
                   help=f"cap on open boxes for --exact (default {MAX_OPEN_FOR_EXACT})")
    m.set_defaults(func=cmd_match)

    b = sub.add_parser("precompute", parents=[common], help="build the table for the chosen rules")
    b.add_argument("--force", action="store_true", help="rebuild even if a table exists")
    b.set_defaults(func=cmd_precompute)

    i = sub.add_parser("interactive", parents=[common], help="play a game with advice at every roll")
    i.add_argument("--scores", default=None, help="resume from this scorecard JSON")
    i.add_argument("--bonuses", default=0, help=bonuses_help)
    i.set_defaults(func=cmd_interactive)
    return p


def main(argv: Optional[List[str]] = None) -> int:
    global _JSON_ERRORS
    argv_list = list(sys.argv[1:] if argv is None else argv)
    _JSON_ERRORS = "--json" in argv_list
    parser = build_parser()
    args = parser.parse_args(argv_list)
    if args.command is None:
        parser.print_help()
        return 2
    as_json = bool(args.json)
    try:
        ctx = Context(rules=PRESETS[args.rules], json=as_json,
                      table_dir=Path(args.table_dir) if args.table_dir else DEFAULT_TABLE_DIR)
        return args.func(args, ctx)
    except CliError as e:
        emit_error(str(e), as_json)
        return 2
    except ValueError as e:
        emit_error(str(e), as_json)
        return 2
    except OSError as e:
        emit_error(str(e), as_json)
        return 1
    except KeyboardInterrupt:
        print("", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
