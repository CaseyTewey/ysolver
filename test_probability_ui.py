"""Exercise the shipped odds UI in Node, with controlled HTTP responses and timers.

This is a logic/DOM contract harness, not a browser or layout test. No npm
packages are needed. Environments without Node skip this optional frontend suite.
"""
from pathlib import Path
import shutil
import subprocess

import pytest


NODE = shutil.which('node')
TEMPLATE = Path(__file__).parent / 'templates' / 'index.html'

HARNESS = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync(process.argv[1], 'utf8');
const elements = new Map();
function mockElement() {
    const classes = new Set();
    return {
        textContent: '', style: {}, addEventListener() {},
        classList: {
            add: (name) => classes.add(name),
            remove: (name) => classes.delete(name),
            contains: (name) => classes.has(name),
            toggle(name, force) {
                const active = force === undefined ? !classes.has(name) : force;
                if (active) classes.add(name); else classes.delete(name);
            }
        }
    };
}
for (const [, id] of html.matchAll(/id="([^"]+)"/g)) {
    elements.set(id, mockElement());
}
const element = (id) => {
    assert.ok(elements.has(id), `Missing element: ${id}`);
    return elements.get(id);
};
const calls = [];
const timers = new Map();
let nextTimer = 1;
const dropChecks = [];
const context = vm.createContext({
    document: { getElementById: element, addEventListener() {} },
    console: { log() {}, error() {} },
    AbortController, DOMException,
    dropChecks,
    fetch(url, options) {
        return new Promise((resolve, reject) => calls.push({ url, options, resolve, reject }));
    },
    setTimeout(callback, delay) {
        const id = nextTimer++;
        timers.set(id, { callback, delay });
        return id;
    },
    clearTimeout: (id) => timers.delete(id)
});
for (const [, source] of html.matchAll(/<script>([\s\S]*?)<\/script>/g)) {
    vm.runInContext(source, context, { filename: 'templates/index.html' });
}
vm.runInContext('checkForBigDrop = (...values) => dropChecks.push(values); updateLastCalcInfo = () => {};', context);
const run = (source) => vm.runInContext(source, context);
const update = () => run('updateWinProbabilities()');
const flush = () => new Promise((resolve) => setImmediate(resolve));
const setScores = (one, two = {}) => run(`playerScores = ${JSON.stringify({1: one, 2: two})}`);
const closed = () => Object.fromEntries(Array.from({length: 13}, (_, i) => [i, 0]));
const change = (category, value) => run(`playerScores[1][${category}] = ${value}`);
function answer(index, data, status = 200, retry = '1') {
    calls[index].resolve({ ok: status < 400, status,
        headers: { get: () => retry }, json: async () => data });
}
function result(method = 'monte_carlo', p1 = 51, p2 = 49, tie = 0) {
    const display = (p) => p === 0 ? '<0.1%' : p === 100 ? '>99.9%' : `~${p}%`;
    const interval = (p) => p === 0 ? [0, 0.0384] : p === 100 ? [99.9616, 100] :
        [Math.max(0, p - 0.98), Math.min(100, p + 0.98)];
    return { method, is_exact: method !== 'monte_carlo', mode: 'joker', tie_probability: tie,
        tie_probability_display: display(tie), tie_probability_interval: interval(tie),
        player1: {win_probability: p1, expected_final: 250, win_probability_display: display(p1), win_probability_interval: interval(p1)},
        player2: {win_probability: p2, expected_final: 245, win_probability_display: display(p2), win_probability_interval: interval(p2)},
        approximation: { max_categories_for_exact: 4 },
        simulation: method === 'monte_carlo' ? { sample_count: 10000, confidence_level: 0.95 } : undefined
    };
}
function fireTimer(delay) {
    const entry = [...timers].find(([, timer]) => timer.delay === delay);
    assert.ok(entry, `Missing timer for ${delay} ms`);
    timers.delete(entry[0]);
    entry[1].callback();
}
const visible = (id) => !element(id).classList.contains('hidden');
assert.ok(!html.includes('calculateExactWinProb'));
assert.ok(!html.includes('/api/win_probability_exact'));
assert.ok(!html.includes('Rough estimate (uncalibrated)'));
(async () => {
"""

CASES = {
    'simulation_is_labeled_with_intervals_and_unchanged_state_is_deduplicated': r"""
        const pending = update();
        assert.equal(element('win-prob-1').textContent, '--');
        assert.equal(element('win-prob-method-1').textContent, 'Calculating odds…');
        await update();
        assert.equal(calls.length, 1);
        answer(0, result()); await pending;
        for (const player of [1, 2]) {
            assert.equal(element(`win-prob-method-${player}`).textContent, 'Estimated odds · 10,000 simulations');
        }
        assert.match(element('edge-case-reasons').textContent, /95% intervals describe simulation sampling uncertainty only/);
        assert.equal(element('win-prob-interval-1').textContent, '95% sampling interval: 50.02–51.98%');
        assert.equal(element('win-prob-interval-2').textContent, '95% sampling interval: 48.02–49.98%');
        assert.equal(visible('win-prob-interval-1'), true);
        assert.equal(visible('win-prob-interval-2'), true);
        assert.match(element('edge-case-reasons').textContent, /4 or fewer/);
        assert.match(element('edge-case-reasons').textContent, /current dice are not included/);
        assert.equal(element('win-prob-1').textContent, '~51%');
        assert.equal(element('win-prob-fill-1').style.width, '51%');
        assert.equal(visible('exact-result'), true);
        assert.match(element('exact-result-values').textContent, /Tie: <0.1%/);
        assert.equal(element('tie-probability-interval').textContent, 'Tie 95% sampling interval: 0.00–0.04%');
        run('rollsRemaining = 0; activePlayer = 2');
        await update();
        assert.equal(calls.length, 1);
        assert.equal(calls[0].url, '/api/win_probability');
        assert.equal(timers.size, 0);
    """,
    'exact_replaces_simulation_and_shows_zero_ties': r"""
        const estimated = update(); answer(0, result()); await estimated;
        change(0, 3);
        const exact = update();
        assert.equal(element('win-prob-1').textContent, '--');
        assert.equal(element('expected-1').textContent, '--');
        assert.equal(element('win-prob-interval-1').textContent, '');
        assert.equal(visible('win-prob-interval-1'), false);
        assert.equal(visible('tie-probability-interval'), false);
        assert.equal(element('win-prob-fill-1').style.width, '0%');
        assert.equal(visible('exact-result'), false);
        answer(1, result('exact_pmf_joker', 4.6, 95.4)); await exact;
        assert.equal(element('win-prob-method-1').textContent, 'Exact odds (score-optimal play)');
        assert.equal(element('win-prob-1').textContent, '4.6%');
        assert.equal(element('expected-1').textContent, 250);
        assert.equal(visible('win-prob-interval-1'), false);
        assert.equal(visible('win-prob-interval-2'), false);
        assert.equal(visible('tie-probability-interval'), false);
        assert.equal(visible('exact-result'), true);
        assert.match(element('exact-result-values').textContent, /Tie: 0%/);
        assert.equal(dropChecks.length, 0, 'Changing method must not trigger a bad-move animation');
        change(1, 6);
        const next = update();
        assert.equal(visible('exact-result'), false);
        assert.equal(element('exact-result-values').textContent, '');
        answer(2, result('exact_pmf_joker', 5, 95)); await next;
        assert.equal(dropChecks.length, 1);
    """,
    'finished_match_has_final_result_and_explicit_ties': r"""
        setScores(closed(), closed());
        const pending = update(); answer(0, result('deterministic', 0, 0, 100)); await pending;
        assert.equal(element('win-prob-method-2').textContent, 'Final result');
        assert.equal(element('win-prob-1').textContent, '0%');
        assert.equal(element('win-prob-2').textContent, '0%');
        assert.match(element('exact-result-values').textContent, /Tie: 100%/);
        assert.equal(element('edge-case-reasons').textContent, 'Both scorecards are complete.');
        assert.equal(visible('win-prob-interval-1'), false);
        assert.equal(visible('tie-probability-interval'), false);
    """,
    'zero_observed_wins_are_not_shown_as_impossible': r"""
        const pending = update(); answer(0, result('monte_carlo', 0, 100, 0)); await pending;
        assert.equal(element('win-prob-1').textContent, '<0.1%');
        assert.equal(element('win-prob-2').textContent, '>99.9%');
        assert.equal(element('win-prob-fill-1').style.width, '0%');
        assert.equal(element('win-prob-fill-2').style.width, '100%');
        assert.equal(element('win-prob-interval-1').textContent, '95% sampling interval: 0.00–0.04%');
        assert.equal(element('win-prob-interval-2').textContent, '95% sampling interval: 99.96–100.00%');
        assert.match(element('exact-result-values').textContent, /P1 wins: <0.1%/);
        assert.match(element('exact-result-values').textContent, /P2 wins: >99.9%/);
        assert.match(element('exact-result-values').textContent, /Tie: <0.1%/);
        assert.match(element('edge-case-reasons').textContent, /not observed.*still be possible/);
    """,
    'near_endpoint_display_preserves_backend_uncertainty': r"""
        const pending = update();
        const data = result('monte_carlo', 99.99, 0.01, 0);
        data.player1.win_probability_display = '>99.9%';
        data.player2.win_probability_display = '<0.1%';
        data.player1.win_probability_interval = [99.943, 99.998];
        data.player2.win_probability_interval = [0.002, 0.057];
        answer(0, data); await pending;
        assert.equal(element('win-prob-1').textContent, '>99.9%');
        assert.equal(element('win-prob-2').textContent, '<0.1%');
        assert.equal(element('win-prob-fill-1').style.width, '99.99%');
        assert.equal(element('win-prob-fill-2').style.width, '0.01%');
        assert.match(element('win-prob-method-1').textContent, /^Estimated odds/);
        assert.equal(visible('win-prob-interval-1'), true);
        assert.equal(element('win-prob-interval-1').textContent, '95% sampling interval: 99.94–100.00%');
        assert.equal(element('win-prob-interval-2').textContent, '95% sampling interval: 0.00–0.06%');
    """,
    'estimated_ties_keep_their_display_and_sampling_interval': r"""
        const pending = update(); answer(0, result('monte_carlo', 45, 45, 10)); await pending;
        assert.match(element('exact-result-values').textContent, /Tie: ~10%/);
        assert.equal(element('tie-probability-interval').textContent, 'Tie 95% sampling interval: 9.02–10.98%');
        assert.equal(visible('tie-probability-interval'), true);
    """,
    'late_response_cannot_overwrite_newer_scorecard': r"""
        const old = update();
        change(0, 3);
        const latest = update();
        assert.equal(calls[0].options.signal.aborted, true);
        answer(1, result('exact_pmf_joker', 70, 20, 10)); await latest;
        // A transport may still finish after cancellation; generation guards remain necessary.
        answer(0, result('monte_carlo', 2, 98)); await old;
        assert.equal(element('win-prob-1').textContent, '70%');
        assert.equal(element('win-prob-method-1').textContent, 'Exact odds (score-optimal play)');
        assert.equal(timers.size, 0);
    """,
    'late_json_body_cannot_overwrite_newer_scorecard': r"""
        const old = update();
        let resolveBody;
        calls[0].resolve({ok: true, status: 200, json: () => new Promise(resolve => {resolveBody = resolve})});
        await flush();
        change(0, 3);
        const latest = update();
        answer(1, result('exact_pmf_joker', 70, 20, 10)); await latest;
        resolveBody(result('monte_carlo', 2, 98)); await old;
        assert.equal(element('win-prob-1').textContent, '70%');
    """,
    'busy_solver_retries_automatically_then_shows_exact': r"""
        const pending = update();
        answer(0, {error: 'Solver busy'}, 503, '2'); await flush();
        assert.match(element('edge-case-reasons').textContent, /Retrying automatically/);
        assert.equal(element('win-prob-1').textContent, '--');
        fireTimer(2000); await flush();
        assert.equal(calls.length, 2);
        answer(1, result('exact_pmf_joker', 25, 70, 5)); await pending;
        assert.equal(element('win-prob-1').textContent, '25%');
        assert.match(element('exact-result-values').textContent, /Tie: 5%/);
        assert.equal(timers.size, 0);
    """,
    'busy_retries_are_bounded_with_visible_manual_retry': r"""
        const pending = update();
        const delays = [1000, 2000, 4000, 5000, 5000, 5000];
        for (let attempt = 0; attempt < 7; attempt++) {
            answer(attempt, {error: 'Solver busy'}, 503); await flush();
            if (attempt < 6) {fireTimer(delays[attempt]); await flush()}
        }
        await pending;
        assert.equal(calls.length, 7);
        assert.equal(element('win-prob-method-1').textContent, 'Odds unavailable');
        assert.equal(element('win-prob-1').textContent, '--');
        assert.equal(visible('win-prob-retry'), true);
        assert.equal(timers.size, 0);
        const retry = update();
        assert.equal(calls.length, 8);
        assert.equal(visible('win-prob-retry'), false);
        answer(7, result('monte_carlo')); await retry;
        assert.equal(element('win-prob-method-1').textContent, 'Estimated odds · 10,000 simulations');
    """,
    'score_change_aborts_pending_retry': r"""
        const old = update();
        answer(0, {error: 'Busy'}, 503); await flush();
        change(0, 3);
        const latest = update();
        await old;
        assert.equal([...timers.values()].filter(timer => timer.delay === 1000).length, 0);
        assert.equal(calls[0].options.signal.aborted, true);
        answer(1, result()); await latest;
        assert.equal(calls.length, 2);
        assert.equal(timers.size, 0);
    """,
    'server_failure_is_visible_without_unrequested_fallback': r"""
        const pending = update(); answer(0, {error: 'Exact calculation failed'}, 500); await pending;
        assert.equal(calls.length, 1);
        assert.equal(element('edge-case-reasons').textContent, 'Exact calculation failed');
        assert.equal(element('win-prob-1').textContent, '--');
        assert.equal(visible('win-prob-retry'), true);
        assert.equal(visible('exact-result'), false);
        const retry = update(); answer(1, result('exact_pmf_joker')); await retry;
        assert.equal(visible('win-prob-retry'), false);
    """,
    'timeout_cancels_transport_and_shows_retry': r"""
        const pending = update();
        fireTimer(30000);
        assert.equal(calls[0].options.signal.aborted, true);
        calls[0].reject(new DOMException('Aborted', 'AbortError')); await pending;
        assert.match(element('edge-case-reasons').textContent, /timed out/);
        assert.equal(element('win-prob-method-2').textContent, 'Odds unavailable');
        assert.equal(visible('win-prob-retry'), true);
    """,
    'earned_bonus_is_part_of_request_identity': r"""
        const pending = update(); answer(0, result()); await pending;
        run('yahtzeeBonuses[1] = 1; yahtzeeStatus[1] = 2; playerScores[1][11] = 50');
        const changed = update();
        const payload = JSON.parse(calls[1].options.body);
        assert.equal(payload.player1_yahtzee_bonuses, 1);
        assert.equal(payload.player1_yahtzee_status, 2);
        assert.equal(payload.player1_scores[11], 50);
        answer(1, result()); await changed;
        await update(); assert.equal(calls.length, 2);
    """,

}


@pytest.mark.skipif(NODE is None, reason='Node is needed for the dependency-free frontend logic harness')
@pytest.mark.parametrize('case', CASES)
def test_probability_ui(case):
    script = HARNESS + CASES[case] + '\n})().catch(error => {console.error(error); process.exitCode = 1});\n'
    completed = subprocess.run(
        [NODE, '-e', script, str(TEMPLATE)], capture_output=True, text=True, timeout=10,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
