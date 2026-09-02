# ysolver

A Yahtzee assistant. It is a web app and a command line tool that play the game optimally
(expected value maximising, exact dynamic program over every reachable state) and report exact
odds: expected final score, standard deviation, best keep or best box for the current roll, and
in the end game the full score distribution and the win probability against a second player.

## Rule sets and the numbers

The engine is one parameterised dynamic program. Three rule sets are built in.

| Rule set  | Fresh-game EV | Std dev | Published figure          | Notes                                                  |
|-----------|---------------|---------|---------------------------|--------------------------------------------------------|
| HASBRO    | 254.5877      | 59.61   | (none)                    | Default. Official Hasbro Joker rule, forced upper box. |
| VERHOEFF  | 254.5896      | 59.61   | 254.5896, SD 59.6117      | The variant behind the famous 254.5896.                |
| PLAIN     | 245.8708      | 39.82   | 245.87, SD 39.82          | No Yahtzee bonus, no Joker rule.                       |

Full precision, as printed by `python engine.py info --rules <name>`:
HASBRO 254.587729 / 59.6076, VERHOEFF 254.589609 / 59.6114, PLAIN 245.870775 / 39.8201.
Expected values do not depend on how ties between equal-EV keeps are broken; standard deviations
do, in the fourth decimal. This solver stands pat on ties (see tie-breaking below), which is why its
SDs sit about 0.0003 below Verhoeff's 59.6117 and 0.0007 below his 39.82 talk figure.

The widely quoted 254.5896 is not the strict Hasbro number. Verhoeff's rules page never forces
the matching upper box ("you may choose any dice pattern for scoring, as long as its box is
empty") and lets Full House, Small Straight and Large Straight count in full only once both the
Yahtzee box and the matching upper box are filled, zeroes included; the official rule forces the
matching upper box whenever it is open, which costs 0.0019 points of expected value. The plain
numbers match the slide in Verhoeff's Yahtzee talk (Yahtzee-talk-NWD.pdf) for play without the Extra Yahtzee Bonus and Jokers: grand total 245.87, SD 39.82.

## The Hasbro Joker rule as implemented

When you roll a Yahtzee and the Yahtzee box is already filled, whether it holds 50 or 0:

1. If the upper box matching the dice is open, you must score there (the total of the dice).
2. Otherwise, if any lower box is open, you may score in any open lower box. Full House scores 25,
   Small Straight 30, Large Straight 40, and Three of a Kind, Four of a Kind and Chance score the
   total of the dice. This is the Joker.
3. Otherwise you must take a zero in an open upper box.

You receive the 100 point Yahtzee bonus only if the Yahtzee box holds 50. A Yahtzee rolled while
the Yahtzee box is still open scores anywhere at normal values (50 in the Yahtzee box). The whole
rule lives in one function, `_fill_options` in `engine.py`, which the precompute, the runtime
policy and the distribution code all share. `Rules` also carries one optional house rule,
`natural_yahtzee_fh` (a natural Yahtzee may score Full House 25 while the Yahtzee box is open);
it is off in all three presets.

## How it works

State. A game position is `(mask, upper, yb)`: `mask` is the 13 bit set of filled boxes in
`scoring.Category` order (0 to 5 Ones through Sixes, 6 Three of a Kind, 7 Four of a Kind, 8 Full
House, 9 Small Straight, 10 Large Straight, 11 Yahtzee, 12 Chance), `upper` is the upper section
subtotal clamped to 63, and `yb` is 1 when the Yahtzee box holds 50. That is 8192 x 64 x 2 table
slots, of which 786,432 are consistent states (`yb` can be 1 only when the Yahtzee box is filled).

Per turn, three stages solved backwards:

    V3[roll]   best box to score the final roll in           (rules applied here)
    V2[roll]   best keep after the second roll  = max over keeps k of roll of  T[k] . V3
    V1[roll]   best keep after the first roll   = max over keeps k of roll of  T[k] . V2
    EV[state]  = P . V1                                       (P = first-roll distribution)

`T` is the 462 keeps x 252 rolls transition matrix; it depends only on the keep, so it is stored
once. Tables are built one level of filled-box count at a time with numba, in parallel over masks.

Two tables are produced per rule set: `EV` (expected remaining score) and `M2` (expected square of
the remaining score) under the same optimal policy, so `std = sqrt(M2 - EV^2)` is exact for every
state. The 35 point upper bonus is credited at the end of the game inside `EV`, so `EV[mask, 63, *]`
already contains it. Accounting for a display is therefore
`expected_final = locked box points + 100 x Yahtzee bonus chips already earned + EV_remaining`.

Tie-breaking. Two keeps whose values are within `TIE_TOL = 1e-10` of each other are treated as
tied, and the tie goes to the highest keep id, both in the precompute (`_max_over_subkeeps`) and
at runtime (`_argmax_sub`). Keep ids are ordered by the number of dice kept, so a tie goes to the
keep that rerolls the fewest dice: standing pat beats a reroll that cannot change the outcome. The
precompute and the runtime reach the same values through different BLAS paths, so without the
tolerance a 1e-13 rounding difference could make them pick different keeps; with it, the keep the
app recommends is exactly the keep the `M2` table assumed, and the exact distribution's variance
equals `M2 - EV^2` (checked to about 1e-10). The margins were measured on the three shipped tables:
cross-path noise stays below 1e-13 and genuinely different keeps are never closer than 4e-9.

How sure is it. The values are exact for the rule set, so the open question at any spot is how much
the choice matters, not whether the number is right. Every recommendation therefore carries a
confidence report (`Solver.decision_report`, the `confidence` field of `/api/recommend`, a line in
`cli.py recommend`, a badge in the UI): the gap in expected final points between the best play and
the runner-up, labelled clear (3 or more points), solid (1 to 3), close (0.25 to 1) or toss-up
(under 0.25, either play is as good), plus forced when the Joker rule leaves one legal box. Exact
ties are flagged with the tie-break that decided them. As a live sanity check, `cli.py simulate`,
`/api/simulate` and the "Simulate this spot" button play the table's own policy from the current
scorecard with random dice and report the sample mean against the table EV with its standard error;
the two should agree within a few standard errors, and a z beyond 3 should happen about 0.3% of the
time. Win probabilities are computed from the exact score distributions whenever that is cheap
(each player at most four open boxes, or five with at most three upper boxes open); a button
offers the exact figure up to seven open boxes; beyond that a normal approximation from each
player's exact mean and standard deviation is used and the response says so (`confidence` on
`/api/win_probability`). The approximation was calibrated on 324 matchups against exact
distributions and 200,000-game simulations: absolute error usually (90th percentile) within 5
points with 8 or more boxes open, 7 points at 5 to 7 open, and 10 points below that with a worst
case of 22, which is why the exact figure is used automatically late in the game.

Simulation check. An independent Monte Carlo simulator (its own dice, scoring, Joker legality and
bonus accounting, consulting the engine only for decisions) played 400,000 games under HASBRO,
400,000 under VERHOEFF and 100,000 under PLAIN: means within 1.2 standard errors of the table
EVs, standard deviations within 0.25%, and under VERHOEFF every one of Verhoeff's 54 published
statistics (per-box means and zero rates, bonus rates, Yahtzee counts, median 248) reproduced within
3 standard errors. A further 400 individual states were simulated 20,000 games each with a
standard-normal spread of z scores and no outliers, and an exact mini dynamic program agreed with
the tables to 1e-13 on 239 end-game states. A naive keep-the-most-common-face policy scores 162
under the same simulator, 92 points below optimal.

Exact end-game distributions. `distribution.pmf_remaining` walks every outcome path under the
optimal policy and returns the exact probability mass function of the remaining score, bonuses
included. It is limited to 7 open boxes (`MAX_OPEN_FOR_EXACT`); on a 2025 laptop the slowest
7-box states measured (five or six upper boxes open) take about 5 s and the slowest 6-box states
about 2 s, while states with few upper boxes open take well under a second. `win_probabilities`
turns two players' distributions into P(win), P(tie), P(lose); earlier in the game
`normal_win_probabilities` uses the exact mean and standard deviation instead.

## Verification

- `tests/reference_solver.py` is an independent clean-room reference solver: plain numpy, its own
  roll and keep enumeration, vectorised over `(upper, yb)` rather than over masks. The engine
  agrees with it at all 786,432 states to under 1e-12 (largest observed difference 9.7e-13) for
  HASBRO, VERHOEFF and PLAIN; the tests assert 1e-9.
- The fast suite compares the engine with 300 reference states per rule set stored in
  `tests/golden_states.json` (regenerate with `tests/make_golden_states.py`); the slow suite
  re-solves each rule set from scratch and compares every state.
- Golden tests pin the fresh-game EV and standard deviation of all three rule sets, including the
  published VERHOEFF figure.
- Brute-force one-box checks: with a single box left, the expected value and the score distribution
  are recomputed by direct enumeration of every three-roll sequence and compared with the tables
  and with `pmf_remaining`.
- `pytest` runs the fast suite: 327 tests, about 10 s, with 3 slow tests skipped.
  `YSOLVER_SLOW=1 pytest` also runs those 3, which rebuild the reference tables (about half a
  minute per rule set on a fast laptop, a few minutes on slower hardware). Set
  `YSOLVER_REF_CACHE=<dir>` to keep the reference arrays on disk between runs.

## Repository layout

Live code:

- `engine.py`: rules, tables, the dynamic program, the `Solver` policy API, `parse_scorecard`,
  `parse_dice`, and the `precompute` / `info` command line.
- `distribution.py`: exact remaining-score distributions and win probabilities.
- `dice.py`: the 252 roll multisets, multinomial probabilities, dice/counts conversion.
- `scoring.py`: the 13 categories, score tables, Joker score table.
- `app.py`: Flask web app and JSON API (`gunicorn app:app`). Routes: `GET /`, `/api/modes`,
  `/api/game_history`, `/api/game_details/<id>`, `/api/article`; `POST /api/recommend`,
  `/api/score_options`, `/api/game_ev`, `/api/win_probability`, `/api/win_probability_exact`,
  `/api/save_game`. Errors come back as JSON `{"error": ...}`.
- `cli.py`: command line interface.
- `tests/`: `reference_solver.py`, `golden_states.json`, `make_golden_states.py`, `conftest.py`
  and the pytest suite.
- `tables/`: `ev_hasbro.npz` (10.6 MB), the one table that goes into git, through Git LFS
  (`.gitattributes` maps `tables/*.npz` to LFS, `.gitignore` excludes every other table). Other
  rule sets are written here on first use: `ev_verhoeff.npz` is also 10.6 MB, `ev_plain.npz` 5.1 MB.
- `templates/index.html`: the single page UI.
- `requirements.txt`, `render.yaml`: dependencies and the Render service definition.

One-offs kept in the repo:

- `video/`: a Remotion (TypeScript) promo animation.
- `pmf_edge_case_animation.py`, `yahtzee_probability_animation.py`: manim animation scripts
  (`manim -qh <file> <SceneName>`; manim is not in `requirements.txt`).
- `research_categories.md`, `research_keeping.md`, `research_upper_bonus.md`,
  `research_yahtzee_timing.md`: solver-driven notes on common mistakes.
- `you-are-probably-playing-yahtzee-wrong.md`: the article the app serves at `/api/article`.
- `game_results.json`: saved game history read and written by the app's history endpoints.
- `transitions.py`: an older keep and reroll helper. The engine does not use it; only
  `tests/test_dice_transitions.py` imports it.

## How to run

    python3 -m venv .venv
    . .venv/bin/activate
    pip install -r requirements.txt

    # build a table (optional; the app and CLI build a missing table on first use)
    python engine.py precompute                    # HASBRO, writes tables/ev_hasbro.npz
    python engine.py precompute --rules verhoeff   # or plain; --force rebuilds; --table-dir DIR elsewhere
    python engine.py info --rules hasbro           # fresh-game EV and std from the saved table

    # web app
    python app.py                                  # http://127.0.0.1:8080
    PORT=8080 python app.py                        # with PORT set it binds 0.0.0.0:$PORT
    FLASK_DEBUG=1 python app.py                    # Flask debug mode
    gunicorn app:app --bind 0.0.0.0:$PORT --timeout 120 --workers 1 --threads 4

    # command line
    python cli.py recommend --dice 1,1,3,5,6 --rolls 2                        # best keep or box for this roll
    python cli.py ev --scores '{"0": 3, "1": 6, "2": 9}'                      # expected score and std for a state
    python cli.py pmf --scores '{"0":3,"1":6,"2":9,"3":12,"4":15,"5":18}' --final   # exact end-game distribution
    python cli.py match --p1 '{"11": 50, "3": 12}' --p2 '{"11": 0}' --p1-bonuses 1   # two-player win probability
    python cli.py simulate --scores '{"11": 50, "3": 12}' --games 5000                   # Monte Carlo check of the table
    python cli.py precompute --rules verhoeff                                 # build a table
    python cli.py interactive                                                 # play a game with advice at every roll
    python cli.py <subcommand> --help                                         # options for each subcommand

`--rules {hasbro,verhoeff,plain}`, `--json` and `--table-dir DIR` are accepted before or after the
subcommand. `pmf` needs 7 or fewer open boxes (`--max-open` raises the cap); `match` needs `--p1`
and `--p2`. Scorecards are JSON objects mapping box index (or name) to points; `@file` reads one
from a file.

The first call into the engine in a fresh environment compiles the numba kernels, which takes
about a second; the compiled kernels are cached on disk after that. `render.yaml` pins Python 3.12;
the numbers in this file were produced locally with Python 3.14, NumPy 2.5 and numba 0.67.

## Deployment on Render

`render.yaml` defines one Python web service: `pip install -r requirements.txt`, then
`gunicorn app:app --bind 0.0.0.0:$PORT --timeout 120 --workers 1 --threads 4` on Python 3.12.
One worker means the 10.6 MB table is loaded once; four threads serve concurrent requests; the
120 s timeout leaves room for an exact seven-box distribution or a table rebuild.

`tables/ev_hasbro.npz` goes through Git LFS. If the build does not fetch LFS objects the file
arrives as a small pointer; `Solver._load` treats a file under 1000 bytes as missing, and also
rejects a table whose `TABLE_VERSION` or rules do not match, so the table is rebuilt at startup
(about 3 s of compute on a 10-core laptop, longer on a small Render instance, plus about a second
of numba compilation) and a deploy without LFS still works. To fetch the shipped table locally
run `git lfs pull`.

## What changed in this rebuild

The previous solver (`ev_solver.py`, `precompute*.py`, `pmf_solver*.py`, `match.py`, the `.pkl`
caches) was removed and replaced by `engine.py` and `distribution.py`.

- Joker after a scratched Yahtzee. The old code applied the Joker rule (forced upper box, Joker
  values) only when the Yahtzee box held 50; after a 0 a further Yahtzee was scored from the
  normal tables with no forcing. And when the Joker did apply with the matching upper box already
  filled, the old code let the player put a zero in another upper box while lower boxes were still
  open. The official rule applies after a 0 as well and allows the upper-box zero only when no
  lower box is open. The old fresh-game EV was 254.49 against 254.5877 now, about 0.10 points,
  and recommendations in those positions were wrong.
- NumPy 2 crash. The old code kept the Yahtzee face as an `int8` array and tested the forced box
  with `mask & (1 << face)`; under NumPy 2 the 13-bit Python `mask` no longer fits the `int8`
  result and raises `OverflowError`, so every Yahtzee rolled after a 50 crashed the old solver.
- Double-counted upper bonus in win probability. The old app added 35 to the current total when
  the upper section reached 63 and also used an EV of remaining play that already contained the
  bonus. Displayed totals and win probabilities were off by 35 points for that player.
- Win probability sigma. The old normal approximation guessed each player's standard deviation as
  7 x sqrt(open boxes); it now uses the exact standard deviation from the `M2` table, and the
  exact distribution when both players have 7 or fewer open boxes.
- Precompute time and size. The old Joker cache took 23.6 minutes to build (recorded in the old
  status notes) and held 1.57 M pickled states (8192 x 64 x 3) of EV only in a 12.6 MB `.pkl`,
  next to a 136 MB `.pkl` for the no-Joker tables. A rule set now builds in about 3 s on a 10-core
  laptop into one 10.6 MB compressed `.npz` holding both `EV` and `M2`.
- One rules function (`_fill_options`) instead of at least six copies of the scoring logic spread
  across `ev_solver.py`, `precompute_fast.py`, `precompute_joker.py` and `pmf_solver_joker.py`,
  each of which could drift.
- Tests. The old `tests.py` held 44 unittest cases; the solver classes loaded the 136 MB pickle in
  `setUpClass` (or ran a roughly ten-minute precompute when it was absent) and none of them checked
  the tables against an independent computation. There are now 327 fast pytest tests plus 3 slow
  ones, with a clean-room reference solver.
- Exact standard deviation for every state (the `M2` table) and an exact end-game distribution
  that uses the same policy as the tables.
