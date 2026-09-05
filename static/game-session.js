(function (root, factory) {
    'use strict';
    const api = factory();
    if (typeof module === 'object' && module.exports) module.exports = api;
    else root.YSolverSession = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
    'use strict';

    const VERSION = 1;
    const MAX_HISTORY = 100;
    const DEFAULT_KEY = 'ysolver.session.v1';

    // Session snapshots are plain JSON data. Reject values JSON.stringify would
    // silently drop or change, so a reload restores exactly what was committed.
    function copyJSON(value, ancestors = new Set()) {
        if (value === null || typeof value === 'string' || typeof value === 'boolean') return value;
        if (typeof value === 'number' && Number.isFinite(value)) return value;
        if (typeof value !== 'object' || ancestors.has(value)) {
            throw new TypeError('A session snapshot must contain finite, acyclic JSON data.');
        }
        const prototype = Object.getPrototypeOf(value);
        if (!Array.isArray(value) && prototype !== Object.prototype && prototype !== null) {
            throw new TypeError('A session snapshot must contain plain objects and arrays.');
        }
        ancestors.add(value);
        const result = Array.isArray(value) ? [] : {};
        for (const key of Object.keys(value)) {
            Object.defineProperty(result, key, {
                value: copyJSON(value[key], ancestors), enumerable: true, writable: true, configurable: true
            });
        }
        if (Array.isArray(value) && result.length !== value.length) {
            throw new TypeError('A session snapshot cannot contain a sparse array.');
        }
        // A sparse array with a populated last element also needs this check.
        if (Array.isArray(value) && (Object.keys(value).length !== value.length ||
            Object.keys(value).some((key, index) => key !== String(index)))) {
            throw new TypeError('A session snapshot cannot contain a sparse array or custom array properties.');
        }
        ancestors.delete(value);
        return result;
    }

    function canonicalJSON(value) {
        if (value === null || typeof value !== 'object') return JSON.stringify(value);
        if (Array.isArray(value)) return '[' + value.map(canonicalJSON).join(',') + ']';
        return '{' + Object.keys(value).sort().map(key => JSON.stringify(key) + ':' + canonicalJSON(value[key])).join(',') + '}';
    }

    function isSnapshot(value) {
        return value !== null && typeof value === 'object' && !Array.isArray(value);
    }

    function labelText(value) {
        if (typeof value !== 'string') throw new TypeError('An action label must be text.');
        return value.slice(0, 120);
    }

    /**
     * Owns a current snapshot and complete before/after states for undo and redo.
     * Call replaceCurrent(captureBefore) immediately before a synchronous action,
     * then commit(captureAfter, label) once that entire action has completed.
     * Dice entry can call replaceCurrent on its own without creating an undo step.
     * The supplied validator checks the app-specific shape and returns true.
     */
    class SessionStore {
        constructor({ storage = null, key = DEFAULT_KEY, validate = isSnapshot,
            onStorageError = null, maxHistory = MAX_HISTORY, maxBytes = 4 * 1024 * 1024 } = {}) {
            if (typeof key !== 'string' || !key.length) throw new TypeError('A session storage key is required.');
            if (typeof validate !== 'function') throw new TypeError('A session validator is required.');
            if (onStorageError !== null && typeof onStorageError !== 'function') throw new TypeError('onStorageError must be a function.');
            if (!Number.isInteger(maxHistory) || maxHistory < 1 || maxHistory > MAX_HISTORY) {
                throw new RangeError('Session history must be between 1 and 100 actions.');
            }
            if (!Number.isInteger(maxBytes) || maxBytes < 1024 || maxBytes > 8 * 1024 * 1024) {
                throw new RangeError('Session storage size must be between 1 KiB and 8 MiB.');
            }
            this._storage = storage;
            this._key = key;
            this._validate = validate;
            this._onStorageError = onStorageError;
            this._maxHistory = maxHistory;
            this._maxBytes = maxBytes;
            this._current = null;
            this._undo = [];
            this._redo = [];
            this._storageError = null;
        }

        get current() { return this._current === null ? null : copyJSON(this._current); }
        get canUndo() { return this._undo.length > 0; }
        get canRedo() { return this._redo.length > 0; }
        get historyLength() { return this._undo.length; }
        get redoLength() { return this._redo.length; }
        get undoLabel() { return this.canUndo ? this._undo[this._undo.length - 1].label : null; }
        get redoLabel() { return this.canRedo ? this._redo[this._redo.length - 1].label : null; }
        get storageError() { return this._storageError; }

        _snapshot(value) {
            const snapshot = copyJSON(value);
            if (!isSnapshot(snapshot) || this._validate(copyJSON(snapshot)) !== true) {
                throw new TypeError('Invalid game session snapshot.');
            }
            const minimum = JSON.stringify({ version: VERSION, current: snapshot, undo: [], redo: [] });
            if (minimum.length > this._maxBytes) throw new RangeError('The game session is too large to store.');
            return snapshot;
        }

        _failure(error) {
            this._storageError = error;
            if (this._onStorageError) {
                try { this._onStorageError(error); } catch (_) { /* Saving must not break gameplay. */ }
            }
        }

        _envelope() {
            return { version: VERSION, current: this._current, undo: this._undo, redo: this._redo };
        }

        _trim() {
            if (this._undo.length > this._maxHistory) this._undo.splice(0, this._undo.length - this._maxHistory);
            if (this._redo.length > this._maxHistory) this._redo.splice(0, this._redo.length - this._maxHistory);
            // Preserve the current game even if a long game log fills the budget.
            // The farthest undo/redo states are dropped first, never the next step.
            while (JSON.stringify(this._envelope()).length > this._maxBytes) {
                if (this._undo.length >= this._redo.length && this._undo.length) this._undo.shift();
                else if (this._redo.length) this._redo.shift();
                else break;
            }
        }

        persist() {
            this._trim();
            if (!this._storage || this._current === null) return false;
            try {
                this._storage.setItem(this._key, JSON.stringify(this._envelope()));
                this._storageError = null;
                return true;
            } catch (error) {
                this._failure(error);
                return false;
            }
        }

        load() {
            if (!this._storage) return null;
            try {
                const raw = this._storage.getItem(this._key);
                if (raw === null || raw === undefined) return null;
                if (typeof raw !== 'string' || raw.length > this._maxBytes) throw new TypeError('Invalid stored session size.');
                const saved = JSON.parse(raw);
                if (!isSnapshot(saved) || saved.version !== VERSION || !Array.isArray(saved.undo) || !Array.isArray(saved.redo) ||
                    saved.undo.length + saved.redo.length > MAX_HISTORY) {
                    throw new TypeError('Invalid stored session format.');
                }
                const current = this._snapshot(saved.current);
                const entries = values => values.map(entry => {
                    if (!isSnapshot(entry) || typeof entry.label !== 'string' || entry.label.length > 120) {
                        throw new TypeError('Invalid stored session action.');
                    }
                    return { snapshot: this._snapshot(entry.snapshot), label: entry.label };
                });
                const undo = entries(saved.undo), redo = entries(saved.redo);
                // Only replace live state after every persisted snapshot validates.
                this._current = current;
                this._undo = undo;
                this._redo = redo;
                this._trim();
                this._storageError = null;
                return this.current;
            } catch (error) {
                this._failure(error);
                return null;
            }
        }

        initialize(snapshot) {
            return this._current === null ? this.reset(snapshot) : this.current;
        }

        reset(snapshot) {
            const next = this._snapshot(snapshot);
            this._current = next;
            this._undo = [];
            this._redo = [];
            this.persist();
            return this.current;
        }

        replaceCurrent(snapshot, { clearRedo = false } = {}) {
            const next = this._snapshot(snapshot);
            if (this._current !== null && canonicalJSON(this._current) === canonicalJSON(next)) return this.current;
            this._current = next;
            if (clearRedo) this._redo = [];
            this.persist();
            return this.current;
        }

        commit(snapshot, label = 'Change') {
            const next = this._snapshot(snapshot);
            const action = labelText(label);
            if (this._current !== null && canonicalJSON(this._current) === canonicalJSON(next)) return this.current;
            if (this._current !== null) this._undo.push({ snapshot: this._current, label: action });
            this._current = next;
            this._redo = [];
            this.persist();
            return this.current;
        }

        undo() {
            if (!this.canUndo) return null;
            const previous = this._undo.pop();
            this._redo.push({ snapshot: this._current, label: previous.label });
            this._current = previous.snapshot;
            this.persist();
            return this.current;
        }

        redo() {
            if (!this.canRedo) return null;
            const next = this._redo.pop();
            this._undo.push({ snapshot: this._current, label: next.label });
            this._current = next.snapshot;
            this.persist();
            return this.current;
        }
    }

    return Object.freeze({ SessionStore, VERSION, DEFAULT_KEY });
});
