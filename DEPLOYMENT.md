# Render deployment

Public app: https://ysolver-vr0n.onrender.com/ (branch `backend-solver-hardening`).

Deploy the Flask app as one Python web service. The current deployment settings
are in `render.yaml`; they explicitly select `plan: free` and attach no disk.
Keep Free selected when creating the service in the dashboard. Do not omit the
Blueprint plan: Render otherwise selects a paid compute plan for a new service.

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

## Free hosting behavior

The Free instance provides 0.1 CPU and 512 MB RAM. It runs the same 10,000-game
simulations and automatic exact endgames as the local app; the compute plan does
not reduce the sample count or change the solver's accuracy. Calculations can
take longer, and concurrent visitors share the existing single calculation slot.
The browser allows two minutes for a probability request, including retries
while another calculation is running. It explains the longer wait after ten
seconds. An uncached opening Yahtzee calculation measured 34.6 seconds on the
Free instance; the tested exact endgame took 0.67 seconds. Results matched the
local solver. These are individual measurements, not latency guarantees.

Render stops a Free service after 15 minutes without inbound traffic. Opening it
again starts it, usually taking about a minute, with Render's loading page shown
while it wakes. The solver's startup checks also run before it accepts requests.
Server files and in-memory result caches are lost when the service stops.

Free compute is subject to monthly usage quotas. For strictly zero spending,
check workspace billing as well: with a payment method, bandwidth overages can
be billed, and extra build minutes can be billed unless a spend limit stops them.
Without a payment method, Render suspends affected free services or new builds
when the included usage runs out. Do not add paid resources or a payment method
for this deployment. See [Render's Free plan documentation](https://render.com/docs/free)
and [Blueprint compute plans](https://render.com/docs/blueprint-spec#plan).

## Saved games

`GAME_RESULTS_FILE` defaults to `/tmp/ysolver/game_results.json`. It starts empty
and never uses the sample `game_results.json` committed to the repository.
Existing history at the configured path is preserved during startup.

That default is **ephemeral**: Render erases it on restart, deployment, or idle
shutdown. Free services cannot attach persistent disks, so server-side completed
game history is temporary in this deployment. Keep one service instance with
the current file-based history implementation.

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
watch deployed memory and latency under actual traffic. If the free instance
cannot handle the workload reliably, investigate optimization or another free
host without changing the simulation sample count or upgrading to paid compute.
The browser probability request timeout is 120 seconds, including busy retries.
