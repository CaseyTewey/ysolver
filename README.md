# ysolver backend

A Yahtzee strategy service that chooses dice to keep and categories to score by maximizing expected final score. The HTTP API uses official Joker rules. The CLI supports Joker and traditional rules. The existing web UI is a client of this backend.

The engine enumerates 252 unordered five-dice rolls and all legal keeps. Dynamic programming stores expected remaining scores by filled-category mask, upper subtotal (capped at 63), and Yahtzee status. Match odds use 10,000 simulated matches early in the game and exact probability distributions in supported endgames. Both methods follow this same score-optimal policy.

## Run and test

The two `.pkl` caches use Git LFS. They must be actual binary files, not LFS pointer text. Python 3.14.6 was verified locally; CI is configured for Python 3.11 and 3.14.

```sh
git lfs pull
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
.venv/bin/python app.py
```

The development server listens on `http://127.0.0.1:8080`. Set `FLASK_DEBUG=1` explicitly for the Flask debugger. For a WSGI server:

```sh
.venv/bin/gunicorn app:app --bind 127.0.0.1:8080 --workers 2 --threads 4 --timeout 30
```

Rebuild a missing or incompatible Joker cache with:

```sh
.venv/bin/python precompute_joker.py --force
```

Current Joker cache version: `3.0-hasbro-joker`. A full rebuild took about 11 seconds locally. Fresh-game expected scores are 254.5877287345 for official Joker rules and 245.8707745141 for traditional mode. Startup rejects incompatible Joker tables instead of silently using old rules. The unchanged traditional pickle currently emits a nonfatal NumPy deprecation warning.

## Continue or enter a game in the browser

Use **Enter / edit game** to join a game already being played on paper or to correct a position. The editor starts with the current scorecards. **Clear this form** clears only the draft; the live game stays unchanged until **Load position & solve** succeeds. Cancel leaves the game unchanged.

- Fill both scorecards using the category selectors. **Unplayed** leaves a category available; **0 — scratch** consumes it for zero points.
- Enter the count of extra Yahtzees: `1` means an already-earned 100-point bonus. Record the original 50-point Yahtzee in its scorecard box. Upper bonuses and totals are calculated automatically.
- Choose the active player and rerolls left: `2` after the first roll, `1` after the second, or `0` when the dice must be scored. Current dice are optional and may be partially entered. Recommendations require all five dice; a complete roll triggers a recommendation after loading.
- Check the preview totals and turn number. The turn is derived from the number of filled categories, including scratches, rather than entered separately. Uneven scorecards are allowed for analysis, but an unfinished game's active player must have a category available.

Loading validates the draft before changing the live game and recalculates odds. **Undo Last stops at the starting point of a loaded game**, so it cannot jump back across an import. A separate **Restore previous game** control reverses the import; **Redo** can reopen it. An imported scorecard cannot reconstruct earlier rolls or decisions, so its turn log starts empty and records subsequent play. Undoing the import restores the previous log as well as the board.

Undo and Redo retain up to 100 actions, subject to a storage-size limit. A scoring action includes the score, any Yahtzee bonus, the turn log, cleared dice, and the next player together. The previous true-Joker scoring path omitted history snapshots, which let Undo jump back to an old dice or manual-edit action; all scoring paths now use complete transactions. Typing dice and receiving recommendations update the saved current state without creating an undo entry for each edit.

The current game, dice, and undo/redo history save automatically to this browser's `localStorage` and restore after refresh at the same site address. This is local browser persistence, with no account or device synchronization, and is separate from server-side completed-game history. If browser storage fails or is unavailable, play and undo/redo continue in memory and the UI reports that the tab should remain open. Invalid stored snapshots are rejected.

## API contract

POST requests require a JSON object. A scorecard is an object keyed by category strings `"0"` through `"12"`; missing or `null` categories are open. Values must be valid nonnegative integer category scores. Zero is accepted for a scratched box. The server derives `yahtzee_status` from category 11 when omitted; explicit inconsistent status is rejected. `yahtzee_bonuses` is a count of already-earned 100-point bonuses.

| Category | Index |
| --- | --- |
| Ones through Sixes | 0–5 |
| Three of a Kind / Four of a Kind | 6 / 7 |
| Full House / Small Straight / Large Straight | 8 / 9 / 10 |
| Yahtzee / Chance | 11 / 12 |

| Endpoint | Input and behavior |
| --- | --- |
| `GET /api/health` | Solver startup health, mode and optimization objective. |
| `GET /api/modes` | HTTP uses Joker mode. |
| `POST /api/validate_position` | Two scorecards and optional Yahtzee status/bonus fields using the `player1_` / `player2_` prefixes; `active_player` 1–2 (default 1); `rolls_remaining` 0–2 (default 2); optional `dice` with up to five slots, each 1–6 or `null`. Returns normalized `position` plus both players' totals and category counts. Validates and derives the turn without running the solver or saving a game. |
| `POST /api/recommend` | Exactly five `dice` in 1–6; `rolls_remaining` 0–2, default 2; `scores`; optional status/bonuses. Returns a legal keep or scoring action, remaining expected value, and every legal scoring option. Completed cards return 409. |
| `POST /api/score_options` | Same dice and scorecard; returns only legal Joker scoring options and the additional Yahtzee bonus. A completed card returns an empty list. |
| `POST /api/game_ev` | Scorecard/status/bonuses; returns current score, remaining EV, and projected final score. |
| `POST /api/win_probability` | `player1_scores`, `player2_scores`, with corresponding `player1_yahtzee_status`, `player1_yahtzee_bonuses`, etc. Automatically returns exact odds when each player has at most four categories open, deterministic results when both are finished, or a 10,000-match Monte Carlo estimate earlier. |
| `POST /api/win_probability_exact` | Exact-only compatibility endpoint with the same response shape. More than four open categories for either player returns 400. Both endpoints share cached exact results. Uncached probability calculations share one compute slot per worker; concurrent excess returns 503 with `Retry-After: 1`. |
| `POST /api/save_game` | Two complete scorecards and optional turn log/statistics/timestamp. Server derives totals and winner, allocates an ID, and saves atomically. |
| `GET /api/game_history` | Saved-game summaries. |
| `GET /api/game_details/<game_id>` | One saved game; missing IDs return 404. |

Invalid JSON or state returns JSON errors (400); unsupported content type returns 415; requests exceeding 1 MiB return 413. Internal errors do not disclose tracebacks to clients.

Probability responses identify the calculation with `method` (`monte_carlo`, `exact_pmf_joker`, or `deterministic`) and `is_exact`. Player EV/projection fields remain present for all methods and come from the dynamic-programming solver. Every response includes the three outcomes: Player 1 wins, a tie, and Player 2 wins.

For `monte_carlo`, the server uses a fixed 10,000 independent match samples, each pairing two independently simulated remaining games. Every keep and scoring decision follows the exact expected-score policy, including Joker rules and bonuses. Stable seeds derived from the scorecards, sample count, and simulation version make unchanged requests reproducible across workers. Clients cannot lower the API's sample count or change its confidence level.

Each outcome has a separate 95% Wilson confidence interval. At 10,000 samples, its endpoints extend at most about one percentage point from the estimated probability; this is sampling uncertainty under the stated policy, not a guaranteed bound on prediction error. The intervals are per outcome, without a simultaneous 95% guarantee for all three. They do not account for player mistakes, a different strategy, or rules/model errors.

The response fields expose both numeric results and their presentation:

- Each player has `win_probability` (percent), `win_probability_display`, and `win_probability_interval` (lower and upper percent bounds). Top-level tie equivalents are `tie_probability`, `tie_probability_display`, and `tie_probability_interval`.
- `simulation` contains `sample_count`, `confidence_level`, `target_margin_percentage_points`, the actual `max_margin_percentage_points`, and `counts` and `intervals` keyed by `player1`, `tie`, and `player2`. Interval bounds are rounded outward for display.
- Estimated display strings use values such as `~75.6%`, `<0.1%`, or `>99.9%`. Zero observed wins are not proof that winning is impossible, and wins in every sample are not certainty. Exact and completed results use ordinary percentages; their `simulation` is `null`, and their interval fields repeat the single result rather than representing sampling uncertainty.
- `distribution_basis: "start_of_turn"` and `objective: "maximize_expected_score"` identify the assumptions. `approximation` retains method, exact-feasibility, and cutoff metadata; the normal approximation is no longer the standard API calculation.

Separate 256-entry result caches for Monte Carlo and exact calculations reuse unchanged scorecards within each worker. Exact requests through either endpoint share the exact cache. Both methods share a single compute slot per worker for uncached work; cached results remain available while another state is being calculated. Busy calculations return 503 with `Retry-After: 1`, and failures return an error without changing methods. These caches and the compute gate are per process, not shared across WSGI workers.

The UI shows **Estimated odds · 10,000 simulations** with each player's 95% sampling interval, plus estimated ties and their interval. Once both players have at most four categories left, it automatically changes to **Exact odds (score-optimal play)**. Completed games show **Final result**. Sampling intervals are hidden for exact/final results. The UI clears old odds and intervals during updates, ignores outdated responses, and reuses the displayed result while scorecards are unchanged. Busy requests get up to six automatic retries with increasing delays (1, 2, 4, 5, 5, and 5 seconds for the standard response), within a 30-second overall timeout. A persistent error offers a retry control.

For a measured opening state—Player 1 has only Yahtzee filled with 50, and Player 2 has a fresh scorecard—the 10,000-match estimate was 75.58% Player 1 wins, 0.34% ties, and 24.08% Player 2 wins. An uncached calculation took about 2.45 seconds with the runtime warm and 4.18 seconds cold on the local test machine. These timings depend on hardware and runtime initialization; repeated requests can use the result cache.

Example recommendation:

```sh
curl http://127.0.0.1:8080/api/recommend \
  -H 'Content-Type: application/json' \
  -d '{"dice":[6,6,6,6,6],"rolls_remaining":0,"scores":{"11":50}}'
```

This forces Sixes for 30 points and awards a separate 100-point Yahtzee bonus.

### Score accounting

HTTP `current_score` includes any earned 35-point upper bonus and all earned Yahtzee bonuses. `ev_remaining` and recommendation `expected_value` exclude bonuses already included in current score. `expected_final = current_score + ev_remaining`. A completed card has zero remaining EV.

Internally, DP/PMF returns the upper bonus at the terminal state. Consequently, low-level PMF locked scores and CLI `score` include category points and earned Yahtzee bonuses **but exclude the upper bonus**. Do not feed HTTP `current_score` directly to a low-level PMF offset without subtracting an earned upper bonus.

Recommendations condition on the supplied dice and rolls remaining. Game EV and match distributions are evaluated at the start of a turn and do not condition on an in-progress roll. Both players are assumed to follow the score-optimal policy. This is not an opponent-adaptive strategy that maximizes match win probability.

### Joker rules

Once Yahtzee is filled with either 50 or 0, another five-of-a-kind must use the matching upper box if open. Otherwise it must use an open lower box, with Full House/Small Straight/Large Straight worth 25/30/40. Only when no lower box remains can another upper box be scratched. An additional 100 points is awarded only if the original Yahtzee scored 50. These rules follow [Hasbro's official explanation](https://hasbro-new.custhelp.com/app/answers/detail/a_id/211/~/i-have-already-rolled-a-yahtzee,-how-do-i-score-it,-if-i-roll-another-one%3F).

## CLI

```sh
.venv/bin/python cli.py expected-score
.venv/bin/python cli.py expected-score --mode traditional
.venv/bin/python cli.py recommend --dice 1,1,3,5,6 --mask 0 --upper 0 --rolls 2
.venv/bin/python cli.py solve --state sample_state.json
```

Joker is the default. Compact CLI states use a filled-category `mask`, `upper`, and locked `score`; when the Yahtzee bit is filled, specify status 1 (scratched) or 2 (scored). CLI distribution analysis is limited to three open categories per player. `solve` still returns early-game recommendations and EVs while explicitly marking unavailable distribution analysis.

## Verification and deployment boundaries

The test suite covers independent scoring and probability oracles, exhaustive Joker legality, every distinct keep, upper-bonus thresholds, last-category and multi-turn endgames, invalid inputs, cache consistency, concurrent access, complete matches, persistence, and CLI behavior. `pytest.ini` ensures both the original `tests.py` and new regression files run. GitHub Actions checks out LFS caches before testing.

The automatic-odds frontend logic tests run the shipped script in a Node harness with controlled responses and timers, requiring no npm packages. Node 24 is configured in CI. Local environments without Node skip those frontend tests; install Node to run the complete suite. They cover method changes, sampling intervals, rare-outcome displays, stale responses, unchanged-state reuse, retries, and timeouts. Session-model tests exercise a 20-turn game with dice edits, one-action undo/redo, full snapshot isolation, refresh restoration, reversible imports, history limits, malformed storage, and storage failures. Position-validation tests cover score legality, bonus consistency, partial dice, derived turns, completed cards, and rejection before applying a draft. Monte Carlo tests check the simulated policy, statistical intervals, reproducibility, accounting, and API integration.

History uses process-safe file locking and atomic replacement. Set `GAME_RESULTS_FILE` to a location on a persistent volume for deployment; the default is the existing repository JSON. Existing history is preserved, and corrupt history is never treated as an empty file during a save. This local-file store is intended for one host/shared filesystem, not distributed multi-host writes.

The current Render configuration has no persistent disk. Render's default filesystem is ephemeral across restarts/deploys; configure durable storage before relying on saved history. See [Render persistent disks](https://render.com/docs/disks). No deployment or infrastructure purchase was performed during this audit.

Early-game Monte Carlo estimates include discrete outcomes and ties but retain sampling uncertainty. Supported endgames automatically use exact distributions. Neither method conditions on the current dice or adapts its strategy to the opponent's score; both assume fresh turns and expected-score-optimal play. Full-game exact distributions and opponent-adaptive strategy remain outside the synchronous API. `match.compute_pivotal_categories` is an existing unfinished helper and is not exposed by the HTTP API.

The service accepts caller-supplied scorecards; it does not provide accounts, per-user private histories, server-authoritative dice, or turn enforcement. These are product/backend decisions before a public multi-user release. The tests cover the documented solver and frontend behaviors; they do not establish public deployment readiness or correctness of every browser and layout.
