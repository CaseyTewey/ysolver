# Render deployment

Deploy the Flask app as one Python web service. The current deployment settings
are in `render.yaml`; they do not select a paid instance or attach a disk.

- Python: `3.14.6`.
- Build: `python -m pip install -r requirements-render.txt && python deploy.py build`.
- Start: `gunicorn --config gunicorn.conf.py app:app`.
- Health check: `/api/health`.
- Use the branch containing the current solver and these deployment files.

The build regenerates the Joker continuation tables from source, so Git LFS
pointer files cannot produce a broken deployment. The larger traditional-mode
cache is not needed by the web app. The deployment dependency file pins the
tested stack and its transitive dependencies; its numerical packages have Linux
x86_64 wheels for Python 3.14.

Build and startup warm the recommendation, exact-odds, and 10,000-simulation API
paths. Gunicorn accepts requests only after worker warmup succeeds. A single
worker with four HTTP threads preserves the existing one-calculation-at-a-time
CPU guard; lightweight and cached requests can still run concurrently. The
worker restarts after 2,000–2,200 requests to periodically release accumulated
solver caches. Readiness fails if startup warmup fails.

The Numba cache uses portable CPU instructions and lives in `.numba-cache/` by
default. `NUMBA_CACHE_DIR` can override it. `OPENBLAS_NUM_THREADS` and
`NUMBA_NUM_THREADS` are set to one in the Render environment.

## Saved games

`GAME_RESULTS_FILE` defaults to `/tmp/ysolver/game_results.json`. It starts empty
and never uses the sample `game_results.json` committed to the repository.
Existing history at the configured path is preserved during startup.

That default is **ephemeral**: Render can erase it on restart or deployment. To
retain completed games, attach a persistent disk at `/var/data` and set
`GAME_RESULTS_FILE=/var/data/game_results.json`. Build does not access this path
because Render disks are available only at runtime. Keep one service instance
with the current file-based history implementation.

Current games and Undo/Redo are autosaved in each browser, independently of the
server's completed-game history. Browser saves are specific to the site's
domain: a localhost save does not automatically appear on the Render URL.
Completed-game history is shared by visitors; the app currently has no accounts
or private per-user histories.

## Deployment verification

Check the root page, its static JavaScript/CSS, and `/api/health`, then try an
early-game simulation, an exact endgame, and a dice recommendation. Confirm that
the new service's completed-game history is empty, and that loading a position,
Undo/Redo, and a browser refresh work on the hosted domain.

Local macOS measurements with this configuration reached about 302 MiB peak
RSS after cold JIT compilation, full-game simulations, and a mixed-upper-section
four-category exact case. This is a sizing reference, not a Linux memory bound;
watch deployed memory and latency under actual traffic before selecting a final
instance size. The existing browser request timeout is 30 seconds.
