"""Atomic local game history with process-safe read/modify/write locking."""

from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import tempfile


@contextmanager
def _locked(path, exclusive=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(path) + '.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        try:
            yield path
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _read(path):
    if not path.exists():
        return []
    with path.open() as source:
        records = json.load(source)
    if not isinstance(records, list) or any(not isinstance(item, dict) for item in records):
        raise ValueError('Game history must be an array of game objects')
    return records


def load_games(path):
    with _locked(path) as locked_path:
        return _read(locked_path)


def append_game(path, game):
    with _locked(path, exclusive=True) as locked_path:
        records = _read(locked_path)
        existing_ids = [item.get('game_id', 0) for item in records]
        next_id = max((value for value in existing_ids if type(value) is int), default=0) + 1
        saved = dict(game, game_id=next_id)
        records.append(saved)
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', dir=locked_path.parent, delete=False) as target:
                temp_path = target.name
                json.dump(records, target, indent=2, allow_nan=False)
                target.flush()
                os.fsync(target.fileno())
            os.replace(temp_path, locked_path)
            temp_path = None
        finally:
            if temp_path is not None:
                os.unlink(temp_path)
        return next_id, len(records)
