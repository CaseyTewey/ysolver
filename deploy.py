"""Build and warm the public Joker solver without depending on Git LFS downloads."""

import argparse
import os
from pathlib import Path
import time

ROOT = Path(__file__).resolve().parent


def configure_environment():
    """Use the same portable compiled-code cache during build and runtime."""
    os.environ.setdefault('NUMBA_CPU_NAME', 'generic')
    os.environ.setdefault('NUMBA_NUM_THREADS', '1')
    os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')
    os.environ.setdefault('NUMBA_CACHE_DIR', str(ROOT / '.numba-cache'))
    os.environ.setdefault('GAME_RESULTS_FILE', '/tmp/ysolver/game_results.json')
    Path(os.environ['NUMBA_CACHE_DIR']).mkdir(parents=True, exist_ok=True)


def prepare_history():
    """Create a separate empty history once; preserve existing saved games."""
    from game_storage import load_games

    history = Path(os.environ['GAME_RESULTS_FILE'])
    history.parent.mkdir(parents=True, exist_ok=True)
    try:
        with history.open('x') as target:
            target.write('[]\n')
    except FileExistsError:
        pass
    load_games(history)  # Fail startup for invalid or inaccessible persisted data.


def warm_application(application, *, prepare_storage=True):
    """Exercise the actual HTTP paths before Gunicorn accepts requests."""
    start = time.monotonic()
    if prepare_storage:
        prepare_history()
    # This one-category endgame compiles the exact path without filling its cache
    # with arbitrary games. The initial 10,000-game estimate is useful to visitors.
    endgame = {str(category): 0 for category in range(13) if category != 12}
    checks = [
        ('/api/recommend', {'scores': {}, 'dice': [1, 2, 3, 4, 5],
                            'rolls_remaining': 2}, None),
        ('/api/win_probability', {'player1_scores': endgame,
                                  'player2_scores': endgame}, 'exact_pmf_joker'),
        ('/api/win_probability', {'player1_scores': {},
                                  'player2_scores': {}}, 'monte_carlo'),
    ]
    with application.test_client() as client:
        for path, payload, method in checks:
            response = client.post(path, json=payload)
            body = response.get_json(silent=True) or {}
            if response.status_code != 200 or (method and body.get('method') != method):
                raise RuntimeError(f'Solver warmup failed for {path}: {response.status_code}')
    print(f'Solver ready: recommendation, exact odds, and simulations warmed '
          f'in {time.monotonic() - start:.1f}s.', flush=True)


def build():
    from precompute_joker import get_joker_tables, load_cache

    # A hosting checkout may contain an LFS pointer instead of the pickle. Building
    # from the versioned scoring engine also prevents a stale/incompatible cache.
    tables = get_joker_tables(force_recompute=True, verbose=True)
    if load_cache() is None or not 254.58 < tables['ev_remaining'][0, 0, 0] < 254.60:
        raise RuntimeError('Built Joker tables failed validation')
    from app import app
    # Persistent disks are mounted only at runtime, never during a Render build.
    warm_application(app, prepare_storage=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('build', 'warmup'))
    arguments = parser.parse_args()
    configure_environment()
    if arguments.command == 'build':
        build()
    else:
        from app import app
        warm_application(app)
