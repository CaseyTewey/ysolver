"""Exercise the browser's actual session model in Node without a DOM or packages."""
from pathlib import Path
import shutil
import subprocess

import pytest


NODE = shutil.which('node')
MODEL = Path(__file__).parent / 'static' / 'game-session.js'

HARNESS = r"""
const assert = require('node:assert/strict');
const { SessionStore, DEFAULT_KEY, VERSION } = require(process.argv[1]);
const clone = value => JSON.parse(JSON.stringify(value));
function memoryStorage() {
    const data = new Map();
    return { data, getItem: key => data.get(key) ?? null, setItem: (key, value) => data.set(key, value) };
}
function fresh() {
    return { turn: 1, activePlayer: 1, dice: [null, null, null, null, null], rollsRemaining: 2,
        scores: {1: {}, 2: {}}, bonuses: {1: 0, 2: 0}, log: [], recommendation: null };
}
function valid(state) {
    return Number.isInteger(state.turn) && state.turn >= 1 && state.turn <= 27 &&
        [1, 2].includes(state.activePlayer) && Array.isArray(state.dice) && state.dice.length === 5 &&
        state.dice.every(value => value === null || (Number.isInteger(value) && value >= 1 && value <= 6)) &&
        typeof state.scores === 'object' && Array.isArray(state.log);
}
const storage = memoryStorage();
const store = new SessionStore({ storage, validate: valid });
"""

CASES = {
    'twenty_scoring_turns_and_dice_edits_undo_only_the_last_action': r"""
        let state = fresh();
        store.initialize(state);
        const befores = [];
        const afters = [];
        for (let turn = 1; turn <= 20; turn++) {
            state.dice = [6, 6, 6, turn % 6 + 1, 6];
            state.rollsRemaining = turn % 3;
            state.recommendation = { category: Math.floor((turn - 1) / 2), ev: 13 + turn,
                keeps: [0, 1, 2], extra: {dice: state.dice.slice()} };
            store.replaceCurrent(state); // Typing and recommendations do not flood Undo.
            assert.equal(store.historyLength, turn - 1);
            befores.push(clone(state));
            const player = state.activePlayer;
            const category = Math.floor((turn - 1) / 2);
            state.scores[player][category] = category * 2;
            if (turn === 20) state.bonuses[player] += 1;
            state.log.push({turn, player, category, dice: state.dice.slice(), bonus: turn === 20 ? 100 : 0});
            state.turn++;
            state.activePlayer = player === 1 ? 2 : 1;
            state.dice = [null, null, null, null, null];
            state.rollsRemaining = 2;
            state.recommendation = null;
            store.commit(state, `Score turn ${turn}`);
            afters.push(clone(state));
        }
        assert.equal(store.historyLength, 20);
        assert.equal(store.undoLabel, 'Score turn 20');
        const undone = store.undo();
        assert.deepEqual(undone, befores[19]);
        assert.equal(undone.turn, 20);
        assert.equal(undone.log.length, 19);
        assert.equal(Object.keys(undone.scores[1]).length + Object.keys(undone.scores[2]).length, 19);
        assert.equal(undone.bonuses[2], 0);
        assert.equal(store.redoLabel, 'Score turn 20');
        assert.deepEqual(store.redo(), afters[19]);
        for (let index = 19; index >= 0; index--) assert.deepEqual(store.undo(), befores[index]);
        assert.equal(store.undo(), null);
        for (let index = 0; index < 20; index++) {
            // Redo restores the actual complete state preceding each Undo, which
            // also includes dice edits performed before the subsequent score.
            const expected = index === 19 ? afters[19] : befores[index + 1];
            assert.deepEqual(store.redo(), expected);
        }
        assert.equal(store.redo(), null);
    """,
    'snapshots_do_not_alias_inputs_outputs_undo_or_redo_stacks': r"""
        const first = fresh();
        const result = store.reset(first);
        first.scores[1][0] = 99;
        result.log.push({turn: 99});
        assert.deepEqual(store.current, fresh());
        const second = fresh(); second.turn = 2; second.scores[1][11] = 50;
        const committed = store.commit(second);
        second.scores[1][11] = 0;
        committed.scores[1][11] = 0;
        assert.equal(store.current.scores[1][11], 50);
        const undone = store.undo(); undone.dice[0] = 6; undone.scores[2][11] = 50;
        assert.deepEqual(store.current, fresh());
        const redone = store.redo(); redone.scores[1][11] = 0;
        const got = store.current; got.log.push('mutated');
        assert.equal(store.current.scores[1][11], 50);
        assert.equal(store.current.log.length, 0);
        assert.deepEqual(store.undo(), fresh());
    """,
    'reload_retains_current_dice_logs_undo_and_redo': r"""
        store.reset(fresh());
        const one = fresh(); one.turn = 2; one.scores[1][11] = 50; one.log = [{turn: 1, score: 50}];
        store.commit(one, 'Score Yahtzee');
        const two = clone(one); two.turn = 3; two.scores[2][5] = 30;
        store.commit(two, 'Score Sixes');
        store.undo();
        const midway = store.current; midway.dice = [4, null, null, null, null];
        store.replaceCurrent(midway);
        const reloaded = new SessionStore({ storage, validate: valid });
        const loaded = reloaded.load();
        assert.deepEqual(loaded, midway);
        assert.equal(reloaded.historyLength, 1);
        assert.equal(reloaded.redoLength, 1);
        loaded.scores[1][11] = 0;
        assert.equal(reloaded.current.scores[1][11], 50);
        assert.deepEqual(reloaded.redo(), two);
        assert.deepEqual(reloaded.undo(), midway);
        assert.deepEqual(reloaded.undo(), fresh());
    """,
    'no_op_actions_preserve_history_and_redo_and_object_order_is_irrelevant': r"""
        store.reset(fresh());
        const next = fresh(); next.turn = 2; next.scores[1] = {0: 2, 1: 4};
        store.commit(next, 'Score');
        store.commit(clone(next), 'No change');
        assert.equal(store.historyLength, 1);
        assert.equal(store.undoLabel, 'Score');
        store.undo();
        const reordered = Object.fromEntries(Object.entries(fresh()).reverse());
        store.commit(reordered, 'Still no change');
        assert.equal(store.historyLength, 0);
        assert.equal(store.redoLength, 1);
        const edited = fresh(); edited.dice[0] = 5;
        store.replaceCurrent(edited); // Explicit default permits returning to the undone result.
        assert.equal(store.redoLength, 1);
        const changed = clone(edited); changed.dice[1] = 5;
        store.replaceCurrent(changed, {clearRedo: true});
        assert.equal(store.redoLength, 0);
        assert.equal(store.historyLength, 0);
    """,
    'new_action_after_undo_discards_redo_but_retains_previous_history': r"""
        store.reset(fresh());
        for (let turn = 2; turn <= 4; turn++) {
            const state = fresh(); state.turn = turn; store.commit(state, `Turn ${turn}`);
        }
        store.undo(); store.undo();
        assert.equal(store.current.turn, 2);
        assert.equal(store.redoLength, 2);
        const branch = store.current; branch.scores[2][8] = 25;
        store.commit(branch, 'Alternative Full House');
        assert.equal(store.canRedo, false);
        assert.equal(store.historyLength, 2);
        assert.equal(store.undo().turn, 2);
        assert.equal(store.undo().turn, 1);
    """,
    'import_is_one_reversible_transaction_and_reset_is_an_explicit_boundary': r"""
        store.reset(fresh());
        const before = fresh(); before.turn = 2; before.scores[1][11] = 50;
        store.commit(before, 'Score Yahtzee');
        const imported = fresh(); imported.turn = 20; imported.activePlayer = 2;
        imported.scores[1] = {0: 0, 1: 4, 2: 6, 3: 12, 4: 15, 5: 30, 6: 21, 10: 40, 11: 50, 12: 12};
        imported.scores[2] = {1: 8, 2: 9, 3: 12, 4: 15, 5: 24, 8: 25, 9: 30, 10: 40, 11: 50};
        imported.bonuses[1] = 1;
        store.commit(imported, 'Load custom game');
        assert.deepEqual(store.undo(), before);
        assert.deepEqual(store.redo(), imported);
        store.reset(fresh());
        assert.equal(store.canUndo, false);
        assert.equal(store.canRedo, false);
        assert.deepEqual(store.initialize(imported), fresh());
    """,
    'bounds_history_and_serialized_size_without_dropping_current_game': r"""
        const bounded = new SessionStore({storage, validate: state => Number.isInteger(state.turn)});
        bounded.reset({turn: 0});
        for (let turn = 1; turn <= 105; turn++) bounded.commit({turn}, `Turn ${turn}`);
        assert.equal(bounded.historyLength, 100);
        assert.equal(JSON.parse(storage.getItem(DEFAULT_KEY)).undo.length, 100);
        for (let turn = 104; turn >= 5; turn--) assert.equal(bounded.undo().turn, turn);
        assert.equal(bounded.undo(), null);
        assert.equal(bounded.redoLength, 100);
        const small = new SessionStore({ storage, key: 'small', maxBytes: 1024 });
        small.reset({turn: 0, description: 'a'.repeat(250)});
        for (let turn = 1; turn <= 20; turn++) small.commit({turn, description: 'a'.repeat(250)});
        assert.equal(small.current.turn, 20);
        assert.ok(small.historyLength > 0 && small.historyLength < 20);
        assert.ok(storage.getItem('small').length <= 1024);
        assert.equal(small.undo().turn, 19);
        assert.equal(small.redo().turn, 20);
        assert.throws(() => small.commit({description: 'b'.repeat(2000)}), RangeError);
        assert.equal(small.current.turn, 20);
    """,
    'malformed_storage_is_rejected_atomically_including_corrupt_history': r"""
        store.reset(fresh());
        const second = fresh(); second.turn = 2; store.commit(second, 'Score');
        const saved = JSON.parse(storage.getItem(DEFAULT_KEY));
        const invalid = [
            'not JSON', 'null', '[]', '{}',
            JSON.stringify({...saved, version: VERSION + 1}),
            JSON.stringify({...saved, current: {...second, dice: [9, 2, 3, 4, 5]}}),
            JSON.stringify({...saved, undo: [{snapshot: {turn: 1}, label: 'Broken snapshot'}]}),
            JSON.stringify({...saved, redo: [{snapshot: fresh(), label: 8}]}),
            JSON.stringify({...saved, redo: [{snapshot: fresh(), label: 'a'.repeat(121)}]}),
            JSON.stringify({...saved, undo: Array(101).fill(saved.undo[0])}),
            JSON.stringify({...saved, undo: Array(100).fill(saved.undo[0]), redo: [saved.undo[0]]})
        ];
        for (const raw of invalid) {
            storage.setItem(DEFAULT_KEY, raw);
            assert.equal(store.load(), null);
            assert.ok(store.storageError instanceof Error);
            assert.deepEqual(store.current, second);
            assert.equal(store.historyLength, 1);
            const empty = new SessionStore({storage, validate: valid});
            assert.equal(empty.load(), null);
            assert.equal(empty.current, null);
        }
        storage.setItem(DEFAULT_KEY, JSON.stringify(saved));
        assert.deepEqual(store.load(), second);
        assert.equal(store.storageError, null);
        assert.deepEqual(store.undo(), fresh());
    """,
    'storage_denial_and_quota_failures_leave_undo_and_gameplay_functional': r"""
        let blocked = true;
        const reports = [];
        const flaky = {
            getItem(key) { if (blocked) throw new Error('Access denied'); return storage.getItem(key); },
            setItem(key, value) { if (blocked) throw new Error('Quota exceeded'); storage.setItem(key, value); }
        };
        const session = new SessionStore({storage: flaky, validate: valid,
            onStorageError(error) { reports.push(error.message); throw new Error('Broken reporting UI'); }});
        assert.equal(session.load(), null);
        session.reset(fresh());
        const second = fresh(); second.turn = 2;
        session.commit(second, 'Score');
        assert.equal(session.current.turn, 2);
        assert.equal(session.undo().turn, 1);
        assert.equal(session.redo().turn, 2);
        assert.ok(reports.includes('Access denied'));
        assert.ok(reports.includes('Quota exceeded'));
        blocked = false;
        assert.equal(session.persist(), true);
        assert.equal(session.storageError, null);
        const restored = new SessionStore({storage, validate: valid});
        assert.equal(restored.load().turn, 2);
        assert.equal(restored.undo().turn, 1);
    """,
    'invalid_snapshots_are_atomic_and_cannot_mutate_through_validator': r"""
        store.reset(fresh());
        const cyclic = fresh(); cyclic.self = cyclic;
        const sparse = fresh(); sparse.dice = Array(5); sparse.dice[4] = 6;
        const disguisedSparse = fresh(); disguisedSparse.extra = [1, , 3]; disguisedSparse.extra.other = 2;
        for (const value of [null, [], {...fresh(), dice: [1, 2, 3, 4, 9]},
            {...fresh(), bad: undefined}, {...fresh(), bad: NaN}, {...fresh(), bad: Infinity},
            {...fresh(), bad: new Date()}, {...fresh(), bad: () => 3}, cyclic, sparse, disguisedSparse]) {
            assert.throws(() => store.commit(value), TypeError);
            assert.deepEqual(store.current, fresh());
            assert.equal(store.historyLength, 0);
        }
        assert.throws(() => store.commit({...fresh(), turn: 2}, 42), TypeError);
        assert.deepEqual(store.current, fresh());
        const mutatingValidator = new SessionStore({validate(state) { state.nested.number = 99; return true; }});
        mutatingValidator.reset({nested: {number: 1}});
        assert.equal(mutatingValidator.current.nested.number, 1);
    """,
}


@pytest.mark.skipif(NODE is None, reason='Node is required for frontend session tests')
@pytest.mark.parametrize('case', CASES, ids=CASES)
def test_session_model(case):
    result = subprocess.run(
        [NODE, '-e', HARNESS + '\n' + CASES[case], str(MODEL)],
        capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
