"""Run real gameplay handlers with a deterministic DOM, HTTP, and clock.

Unlike snapshot-only tests, these regressions score through the same public
handler the category buttons call. No game-state or history mutation is mocked.
This is a dependency-free logic harness; browser/layout checks are separate.
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
const path = require('node:path');
const vm = require('node:vm');
const templatePath = process.argv[1];
const html = fs.readFileSync(templatePath, 'utf8');
const elements = new Map();
const listeners = new Map();
const requests = [];
const timers = new Map();
const alerts = [];
const probabilityStates = [];
const storage = new Map();
let nextTimer = 1;
let document;
function node(id = '') {
    const classes = new Set();
    const childSelectors = new Map();
    const result = {
        id, textContent: '', value: '', disabled: false, style: {}, dataset: {},
        tagName: 'DIV', attributes: {}, children: [],
        parentNode: {insertBefore(child) {if (child.id) elements.set(child.id, child)}},
        classList: {
            add(...names) {names.forEach(name => classes.add(name))},
            remove(...names) {names.forEach(name => classes.delete(name))},
            contains(name) {return classes.has(name)},
            toggle(name, force) {
                const active = force === undefined ? !classes.has(name) : force;
                if (active) classes.add(name); else classes.delete(name);
                return active;
            }
        },
        addEventListener(type, callback) {listeners.set(`${id}:${type}`, callback)},
        focus() {document.activeElement = result},
        remove() {elements.delete(id)},
        appendChild(child) {result.children.push(child); if (child.id) elements.set(child.id, child); return child},
        replaceChildren(...children) {result.children = children},
        setAttribute(key, value) {result.attributes[key] = String(value)},
        getAttribute(key) {return result.attributes[key] ?? null},
        removeAttribute(key) {delete result.attributes[key]},
        querySelector(selector) {
            if (!childSelectors.has(selector)) childSelectors.set(selector, node());
            return childSelectors.get(selector);
        },
        querySelectorAll(selector) {
            if (selector === '.toggle-btn') return [result.querySelector('.score-btn'), result.querySelector('.zero-btn')];
            return [];
        },
        insertAdjacentHTML(where, markup) {register(markup)},
        getBoundingClientRect() {return {left: 0, top: 0, width: 100, height: 100}}
    };
    Object.defineProperty(result, 'innerHTML', {
        get() {return result.markup || ''},
        set(markup) {result.markup = markup; register(markup)}
    });
    return result;
}
function register(markup) {
    for (const [, id] of String(markup).matchAll(/id="([^"$]+)"/g)) {
        if (!elements.has(id)) elements.set(id, node(id));
    }
}
register(html);
const groups = new Map([['.player-btn', [node(), node()]], ['.scorecard', [node(), node()]], ['.roll-btn', [node(), node(), node()]]]);
document = {
    body: node('body'), activeElement: {tagName: 'BODY'},
    getElementById(id) {return elements.get(id) || null},
    createElement(tag) {const value = node(); value.tagName = tag.toUpperCase(); return value},
    querySelector(selector) {return selector.startsWith('#') ? elements.get(selector.slice(1)) : null},
    querySelectorAll(selector) {return groups.get(selector) || []},
    addEventListener(type, callback) {listeners.set(`document:${type}`, callback)}
};
const localStorage = {
    getItem(key) {return storage.get(key) ?? null},
    setItem(key, value) {storage.set(key, String(value))},
    removeItem(key) {storage.delete(key)}
};
const context = vm.createContext({
    document, localStorage, sessionStorage: localStorage,
    console: {log() {}, error() {}, warn() {}}, AbortController, DOMException,
    alerts, probabilityStates, structuredClone,
    alert(message) {alerts.push(message)}, confirm() {return true},
    fetch(url, options) {return new Promise((resolve, reject) => requests.push({url, options, resolve, reject}))},
    setTimeout(callback, delay = 0) {const id = nextTimer++; timers.set(id, {callback, delay}); return id},
    clearTimeout(id) {timers.delete(id)},
    requestAnimationFrame(callback) {return nextTimer++}, cancelAnimationFrame() {},
    addEventListener(type, callback) {listeners.set(`window:${type}`, callback)},
    location: {hash: '', reload() {}}, crypto: {randomUUID() {return 'test-session'}}
});
context.window = context;
const run = source => vm.runInContext(source, context);
for (const [, attrs, inline] of html.matchAll(/<script([^>]*)>([\s\S]*?)<\/script>/g)) {
    const src = attrs.match(/src="([^"]+)"/);
    if (src) {
        const scriptPath = path.join(path.dirname(templatePath), '..', src[1].replace(/^\//, ''));
        vm.runInContext(fs.readFileSync(scriptPath, 'utf8'), context, {filename: scriptPath});
    } else vm.runInContext(inline, context, {filename: templatePath});
}
run(`
    updateWinProbabilities = () => { probabilityStates.push(JSON.parse(JSON.stringify(winProbabilityRequestBody()))); };
    triggerYahtzeeCelebration = () => {};
    showJokerBonusAnimation = () => {};
    updateLastCalcInfo = () => {};
    initScorecard(1); initScorecard(2); initTurn();
    if (typeof initializeGameSession === 'function') initializeGameSession();
`);
const element = id => {assert.ok(elements.has(id), `Missing element: ${id}`); return elements.get(id)};
const value = source => JSON.parse(JSON.stringify(run(source)));
const flush = () => new Promise(resolve => setImmediate(resolve));
async function flushTimers() {
    for (let pass = 0; pass < 10 && timers.size; pass++) {
        const ready = [...timers]; timers.clear();
        for (const [, timer] of ready) timer.callback();
        await flush();
    }
}
function fillDice(dice = [1, 2, 3, 4, 5]) {
    for (let i = 1; i <= 5; i++) {
        element(`die-${i}`).value = String(dice[i - 1]);
        element(`visual-die-${i}`).textContent = String(dice[i - 1]);
    }
    run('allDiceFilled = true; diceEntered = 5;');
}
function recommendation(category, points, extra = {}) {
    return {action: 'score', mode: 'joker', category, points,
        category_name: `Category ${category}`, expected_value: 200,
        category_options: [{category, points, name: `Category ${category}`, expected_value: 200}],
        is_yahtzee_roll: false, ...extra};
}
function answer(request, data, status = 200) {
    request.resolve({ok: status < 400, status, headers: {get() {return null}}, json: async () => data});
}
async function showRecommendation(category, points, dice = [1, 2, 3, 4, 5], extra = {}) {
    fillDice(dice);
    const pending = run('getRecommendation()');
    const request = requests.at(-1);
    assert.equal(request.url, '/api/recommend');
    answer(request, recommendation(category, points, {dice, ...extra}));
    await pending;
}
async function score(category, points, dice, extra) {
    await showRecommendation(category, points, dice, extra);
    run(`selectScoringOption(${category}, ${points})`);
    await flush();
}
let completed = false;
process.on('beforeExit', () => {
    if (!completed) {
        console.error('Test did not complete: an unexpected unresolved async operation remains');
        process.exitCode = 1;
    }
});
(async () => {
"""


CASES = {
    'eighteen_category_clicks_undo_only_the_last_scored_turn': r"""
        for (let turn = 0; turn < 18; turn++) {
            const category = Math.floor(turn / 2);
            const points = category < 5 ? category + 1 : 0;
            await score(category, points);
            await flushTimers();
        }
        assert.equal(run('currentTurn'), 19);
        assert.equal(run('gameLog.length'), 18);
        assert.equal(run('Object.keys(playerScores[1]).length + Object.keys(playerScores[2]).length'), 18);
        run('goBack()');
        assert.equal(run('currentTurn'), 18);
        assert.equal(run('activePlayer'), 2);
        assert.equal(run('gameLog.length'), 17);
        assert.equal(run('Object.keys(playerScores[1]).length'), 9);
        assert.equal(run('Object.keys(playerScores[2]).length'), 8);
        assert.equal(run('playerScores[2][8]'), undefined);
        assert.equal(run('playerScores[1][8]'), 0, 'A scratched zero is still a filled category');
        assert.deepEqual(value('getDice()'), [1, 2, 3, 4, 5]);
        assert.equal(String(element('current-turn-num').textContent), '18');
        assert.equal(element('turn-player-name').textContent, 'Player 2');
        await flushTimers();
        assert.equal(run('currentTurn'), 18, 'An older turn-switch timer must not change restored state');
    """,
    'immediate_undo_and_redo_restore_the_whole_scoring_transaction': r"""
        await score(0, 1);
        assert.equal(run('currentTurn'), 2);
        run('goBack()');
        assert.deepEqual(value('playerScores'), {'1': {}, '2': {}});
        assert.equal(run('currentTurn'), 1);
        assert.equal(run('activePlayer'), 1);
        assert.equal(run('gameLog.length'), 0);
        await flushTimers();
        assert.equal(run('activePlayer'), 1);
        run('goForward()');
        assert.deepEqual(value('playerScores'), {'1': {'0': 1}, '2': {}});
        assert.equal(run('currentTurn'), 2);
        assert.equal(run('activePlayer'), 2);
        assert.equal(run('gameLog.length'), 1);
        assert.deepEqual(value('getDice()'), [null, null, null, null, null]);
    """,
    'joker_bonus_status_and_roll_log_are_undone_with_the_score': r"""
        await score(11, 50, [6, 6, 6, 6, 6], {is_yahtzee_roll: true});
        await flushTimers();
        await score(11, 0);
        await flushTimers();
        await score(5, 30, [6, 6, 6, 6, 6], {is_yahtzee_roll: true, joker_bonus_available: true});
        assert.equal(run('yahtzeeBonuses[1]'), 1);
        assert.equal(run('calculateFinalScore(1)'), 180);
        assert.equal(run('gameLog.length'), 3);
        assert.ok(run('gameLog[2].rolls.length') > 0, 'True Joker mode must record its rolls');
        run('goBack()');
        assert.equal(run('yahtzeeBonuses[1]'), 0);
        assert.equal(run('yahtzeeStatus[1]'), 2);
        assert.equal(run('yahtzeeStatus[2]'), 1);
        assert.equal(run('calculateFinalScore(1)'), 50);
        assert.equal(String(element('total-1').textContent), '50');
        assert.equal(element('joker-bonus-1').textContent, '-');
        assert.equal(run('gameLog.length'), 2);
        assert.equal(run('playerScores[1][5]'), undefined);
        run('goForward()');
        assert.equal(run('yahtzeeBonuses[1]'), 1);
        assert.equal(run('calculateFinalScore(1)'), 180);
        assert.equal(run('gameLog.length'), 3);
        assert.equal(run('gameLog[2].finalPoints'), 30);
    """,
    'manual_score_after_undo_creates_a_branch_and_clears_redo': r"""
        await score(0, 1); await score(0, 1);
        run('goBack()');
        element('score-2-1').value = '6';
        run("updateScore(2, 1, '6')");
        run('goForward()');
        assert.equal(run('playerScores[2][0]'), undefined);
        assert.equal(run('playerScores[2][1]'), 6);
        assert.equal(run('currentTurn'), 3);
        run('goBack()');
        assert.deepEqual(value('playerScores[2]'), {});
        assert.equal(run('currentTurn'), 2);
    """,
    'joker_pick_category_button_uses_real_scoring_flow': r"""
        await showRecommendation(0, 1);
        const pending = run('confirmTurn()');
        await flush();
        assert.equal(typeof context.categoryResolve, 'function', 'The visible Joker category picker must open');
        context.categoryResolve({id: 0, points: 1});
        await pending;
        assert.equal(run('playerScores[1][0]'), 1);
        assert.equal(run('gameLog.length'), 1);
        run('goBack()');
        assert.equal(run('playerScores[1][0]'), undefined);
        assert.equal(run('gameLog.length'), 0);
    """,
    'late_recommendation_after_manual_score_cannot_reactivate_old_options': r"""
        fillDice();
        const pending = run('getRecommendation()');
        const request = requests.at(-1);
        element('score-1-0').value = '1';
        run("updateScore(1, 0, '1')");
        answer(request, recommendation(11, 50, {is_yahtzee_roll: true, dice: [6, 6, 6, 6, 6]}));
        await pending;
        assert.equal(run('lastRecommendation'), null);
        assert.equal(element('category-options').innerHTML, '');
        assert.equal(element('confirm-score-btn').disabled, true);
        assert.equal(run('activePlayer'), 2);
        assert.deepEqual(value('playerScores[2]'), {});
    """,
    'latest_recommendation_wins_even_when_old_response_finishes_last': r"""
        fillDice([1, 2, 3, 4, 5]);
        const older = run('getRecommendation()');
        const oldRequest = requests.at(-1);
        fillDice([6, 6, 6, 6, 6]);
        const latest = run('getRecommendation()');
        const latestRequest = requests.at(-1);
        answer(latestRequest, recommendation(11, 50, {is_yahtzee_roll: true, dice: [6, 6, 6, 6, 6]}));
        await latest;
        answer(oldRequest, recommendation(12, 15, {dice: [1, 2, 3, 4, 5]}));
        await older;
        assert.equal(run('lastRecommendation.category'), 11);
        assert.equal(run('lastRecommendation.is_yahtzee_roll'), true);
        assert.match(element('category-options').innerHTML, /50 pts/);
    """,
    'partial_dice_are_not_silently_substituted_into_a_recommendation': r"""
        element('die-1').value = '6';
        const before = requests.length;
        await run('getRecommendation()');
        assert.equal(requests.length, before, 'Incomplete dice must not become artificial ones');
        assert.equal(run('lastRecommendation'), null);
        assert.equal(element('confirm-score-btn').disabled, true);
    """,
    'typing_a_reroll_can_be_undone_without_losing_the_previous_roll': r"""
        await showRecommendation(12, 15, [1, 2, 3, 4, 5], {
            action: 'keep', keep_dice: [1, 2], reroll: [3, 4, 5]
        });
        run('handleDiceInput(3, 6)');
        assert.equal(run('rollsRemaining'), 1);
        assert.deepEqual(value('getDice()'), [1, 2, 6, null, null]);
        run('goBack()');
        assert.equal(run('rollsRemaining'), 2);
        assert.deepEqual(value('getDice()'), [1, 2, 3, 4, 5]);
        assert.equal(run('currentTurn'), 1);
        assert.deepEqual(value('playerScores'), {'1': {}, '2': {}});
    """,
    'manual_player_switch_rejects_the_previous_players_pending_recommendation': r"""
        fillDice();
        const pending = run('getRecommendation()');
        const request = requests.at(-1);
        run('setActivePlayer(2)');
        answer(request, recommendation(12, 15, {dice: [1, 2, 3, 4, 5]}));
        await pending;
        assert.equal(run('activePlayer'), 2);
        assert.equal(element('turn-player-name').textContent, 'Player 2');
        assert.equal(run('lastRecommendation'), null);
        assert.equal(element('confirm-score-btn').disabled, true);
    """,
    'category_picker_cannot_score_an_option_from_an_old_game_state': r"""
        await showRecommendation(0, 1);
        const pending = run('confirmTurn()');
        await flush();
        const resolveOldPicker = context.categoryResolve;
        assert.equal(typeof resolveOldPicker, 'function');
        element('score-1-1').value = '6';
        run("updateScore(1, 1, '6')");
        if (context.categoryResolve === resolveOldPicker) resolveOldPicker({id: 0, points: 1});
        await pending;
        assert.equal(run('activePlayer'), 2);
        assert.deepEqual(value('playerScores[1]'), {'1': 6});
        assert.deepEqual(value('playerScores[2]'), {});
    """,
    'custom_position_load_has_an_explicit_restore_boundary_with_scores_bonuses_and_partial_roll': r"""
        await score(0, 1);
        const original = value('captureGameState()');
        run('openPositionEditor()');
        for (const player of [1, 2]) for (let category = 0; category < 13; category++) {
            element(`position-${player}-${category}`).value = '';
        }
        element('position-1-11').value = '50';
        element('position-1-5').value = '30';
        element('position-2-0').value = '0';
        element('position-2-11').value = '0';
        element('position-bonus-1').value = '1';
        element('position-bonus-2').value = '0';
        element('position-player').value = '1';
        element('position-rolls').value = '1';
        element('position-die-1').value = '6';
        const pending = run('applyPositionEditor()');
        const request = requests.at(-1);
        assert.equal(request.url, '/api/validate_position');
        const draft = JSON.parse(request.options.body);
        assert.deepEqual(draft.player1_scores, {'5': 30, '11': 50});
        assert.deepEqual(draft.player2_scores, {'0': 0, '11': 0});
        assert.equal(draft.player1_yahtzee_bonuses, 1);
        const position = {...draft, player1_yahtzee_status: 2, player2_yahtzee_status: 1,
            current_turn: 5, completed: false};
        answer(request, {position}); await pending;
        assert.equal(run('currentTurn'), 5);
        assert.equal(run('activePlayer'), 1);
        assert.equal(run('rollsRemaining'), 1);
        assert.equal(run('calculateFinalScore(1)'), 180);
        assert.deepEqual(value('getDice()'), [6, null, null, null, null]);
        assert.deepEqual(value('gameLog'), [], 'Imported turns must not invent move history');
        assert.equal(run('playerScores[2][0]'), 0);
        assert.equal(element('position-overlay').classList.contains('hidden'), true);
        assert.equal(element('undo-btn').disabled, true);
        assert.equal(element('restore-position-btn').classList.contains('hidden'), false);
        run('goBack()');
        assert.equal(run('currentTurn'), 5, 'Undo Last must stop at the loaded position');
        assert.equal(run('calculateFinalScore(1)'), 180);
        assert.deepEqual(value('getDice()'), [6, null, null, null, null]);
        run('restorePreviousPosition()');
        assert.deepEqual(value('playerScores'), original.playerScores);
        assert.deepEqual(value('gameLog'), original.gameLog);
        assert.equal(run('activePlayer'), original.activePlayer);
        assert.equal(run('currentTurn'), original.currentTurn);
        assert.equal(element('restore-position-btn').classList.contains('hidden'), true);
        run('goForward()');
        assert.equal(run('calculateFinalScore(1)'), 180);
        assert.deepEqual(value('getDice()'), [6, null, null, null, null]);
        assert.equal(element('undo-btn').disabled, true);
        assert.equal(element('restore-position-btn').classList.contains('hidden'), false);
    """,
    'scoring_after_import_undoes_one_turn_then_stops_at_the_import_baseline': r"""
        await score(0, 1);
        run(`applyValidatedPosition({
            player1_scores: {'0': 0, '1': 6, '2': 9, '3': 12, '4': 15, '5': 18, '11': 50},
            player2_scores: {'0': 0, '1': 6, '2': 9, '3': 12, '4': 15, '5': 18, '11': 0},
            player1_yahtzee_status: 2, player2_yahtzee_status: 1,
            player1_yahtzee_bonuses: 0, player2_yahtzee_bonuses: 0,
            active_player: 1, current_turn: 15, rolls_remaining: 2,
            dice: [null, null, null, null, null], completed: false
        })`);
        assert.equal(run('currentTurn'), 15);
        const imported = value('playerScores');
        await score(12, 15);
        assert.equal(run('currentTurn'), 16);
        assert.equal(element('undo-btn').disabled, false);
        assert.equal(element('restore-position-btn').classList.contains('hidden'), true);
        run('goBack()');
        assert.equal(run('currentTurn'), 15);
        assert.deepEqual(value('playerScores'), imported);
        assert.equal(element('undo-btn').disabled, true);
        assert.equal(element('restore-position-btn').classList.contains('hidden'), false);
        run('goBack()');
        assert.equal(run('currentTurn'), 15, 'A second Undo must not jump from turn 15 to the prior game');
        assert.deepEqual(value('playerScores'), imported);
        run('goForward()');
        assert.equal(run('currentTurn'), 16);
        assert.equal(run('playerScores[1][12]'), 15);
        assert.equal(element('undo-btn').disabled, false);
        assert.equal(element('restore-position-btn').classList.contains('hidden'), true);
    """,
    'reloading_saved_session_keeps_scored_turns_and_undo_history': r"""
        await score(0, 1); await score(0, 1);
        const saved = value('captureGameState()');
        assert.ok(storage.size > 0, 'The current game must be persisted');
        run('initializeGameSession()');
        assert.deepEqual(value('playerScores'), saved.playerScores);
        assert.deepEqual(value('gameLog'), saved.gameLog);
        assert.equal(run('currentTurn'), 3);
        run('goBack()');
        assert.equal(run('currentTurn'), 2);
        assert.equal(run('gameLog.length'), 1);
        assert.deepEqual(value('playerScores[2]'), {});
        run('goForward()');
        assert.deepEqual(value('playerScores'), saved.playerScores);
    """,
    'undo_restores_user_selected_keeps_with_unambiguous_dice_colors': r"""
        await showRecommendation(12, 15, [1, 2, 3, 4, 5], {
            action: 'keep', keep_dice: [1, 2], reroll: [3, 4, 5]
        });
        run('toggleDieKeep(1); toggleDieKeep(3);');
        assert.deepEqual(value('keptDiceIndices'), [2, 3]);
        run('advanceToNextRoll(); goBack();');
        assert.deepEqual(value('keptDiceIndices'), [2, 3]);
        for (let i = 1; i <= 5; i++) {
            const die = element(`visual-die-${i}`);
            assert.equal(die.classList.contains('keep'), [2, 3].includes(i));
            assert.equal(die.classList.contains('reroll'), ![2, 3].includes(i), `Die ${i} must have exactly one keep/reroll color`);
        }
    """,
    'repeated_recommendation_requests_do_not_invent_additional_rolls': r"""
        for (let i = 0; i < 5; i++) await showRecommendation(12, 15);
        assert.equal(run('currentTurnData.rolls.length'), 1);
        assert.equal(run('currentTurnData.rolls[0].rollsRemaining'), 2);
        run('setRolls(1)');
        await showRecommendation(12, 20, [2, 3, 4, 5, 6]);
        await showRecommendation(12, 20, [2, 3, 4, 5, 6]);
        assert.equal(run('currentTurnData.rolls.length'), 2);
        assert.deepEqual(value('currentTurnData.rolls.map(roll => roll.rollsRemaining)'), [2, 1]);
        run('selectScoringOption(12, 20)');
        assert.equal(run('gameLog[0].rolls.length'), 2);
        assert.equal(run('playerScores[1][12]'), 20);
        run('goBack()');
        assert.equal(run('currentTurnData.rolls.length'), 2);
        assert.equal(run('rollsRemaining'), 1);
        assert.deepEqual(value('getDice()'), [2, 3, 4, 5, 6]);
    """,
}


@pytest.mark.skipif(NODE is None, reason='Node is needed for the frontend flow harness')
@pytest.mark.parametrize('case', CASES)
def test_game_flow_ui(case):
    script = HARNESS + CASES[case] + '\n})().then(() => {completed = true}).catch(error => {completed = true; console.error(error); process.exitCode = 1});\n'
    completed = subprocess.run(
        [NODE, '-e', script, str(TEMPLATE)], capture_output=True, text=True, timeout=15,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
