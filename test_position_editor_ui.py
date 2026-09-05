"""Exercise the real custom-position editor, validation requests, and history."""

import json
import subprocess

import pytest

from api_state import parse_position
from test_game_flow_ui import HARNESS, NODE, TEMPLATE


# The shared lightweight DOM registers nodes but does not interpret selected
# options. Add those browser semantics here so prefill is tested from the real
# generated <select> markup rather than assigning the expected values manually.
EDITOR_HARNESS = HARNESS.replace(
    "register(html);",
    r"""
const registerIds = register;
register = function(markup) {
    registerIds(markup);
    for (const [, id, options] of String(markup).matchAll(/<select[^>]*id="([^"$]+)"[^>]*>([\s\S]*?)<\/select>/g)) {
        const choices = [...options.matchAll(/<option value="([^"]*)"([^>]*)>/g)];
        const selected = choices.find(choice => /\bselected\b/.test(choice[2])) || choices[0];
        if (selected && elements.has(id)) elements.get(id).value = selected[1];
    }
};
register(html);
""",
)

LATE_POSITION = parse_position({
    'player1_scores': {'0': 0, '1': 4, '2': 6, '3': 12, '4': 15, '5': 30,
                       '6': 21, '10': 40, '11': 50, '12': 12},
    'player1_yahtzee_bonuses': 1,
    'player2_scores': {'1': 8, '2': 9, '3': 12, '4': 15, '5': 24,
                       '8': 25, '9': 30, '10': 40, '11': 50},
    'active_player': 2, 'rolls_remaining': 0, 'dice': [4, 4, 4, 3, 2],
})['position']

HELPERS = '\nconst latePosition = ' + json.dumps(LATE_POSITION) + r""";
function openLatePosition() {
    run(`openPositionEditor(${JSON.stringify(latePosition)})`);
}
function validated(draft) {
    const scores = p => Object.fromEntries(Array.from({length:13},(_,cat)=>[cat,draft[`player${p}_scores`][cat]??null]));
    return {...draft,player1_scores:scores(1),player2_scores:scores(2),
        player1_yahtzee_status:draft.player1_scores[11]===undefined?0:draft.player1_scores[11]===50?2:1,
        player2_yahtzee_status:draft.player2_scores[11]===undefined?0:draft.player2_scores[11]===50?2:1,
        current_turn:Math.min(26,1+Object.keys(draft.player1_scores).length+Object.keys(draft.player2_scores).length),
        completed:Object.keys(draft.player1_scores).length+Object.keys(draft.player2_scores).length===26};
}
"""

CASES = {
    'opening_prefills_current_scores_and_dice_without_changing_game_or_history': r"""
        await score(11,50,[6,6,6,6,6],{is_yahtzee_roll:true});
        await score(11,0);
        await score(5,30,[6,6,6,6,6],{is_yahtzee_roll:true,joker_bonus_available:true});
        element('die-1').value='4';
        run('setRolls(1); persistGameSession();');
        const before = value('captureGameState()');
        const history = run('sessionStore.historyLength');
        const persisted = [...storage.entries()];
        run('openPositionEditor()');
        assert.equal(element('position-1-11').value,'50');
        assert.equal(element('position-1-5').value,'30');
        assert.equal(element('position-1-0').value,'');
        assert.equal(element('position-2-11').value,'0');
        assert.equal(String(element('position-bonus-1').value),'1');
        assert.equal(String(element('position-player').value),'2');
        assert.equal(String(element('position-rolls').value),'1');
        assert.equal(String(element('position-die-1').value),'4');
        assert.match(element('position-preview').textContent,/Turn 4 of 26/);
        assert.match(element('position-preview').textContent,/Player 1: 180 points/);
        element('position-1-0').value='0';
        run('updatePositionPreview()');
        assert.deepEqual(value('captureGameState()'),before);
        assert.equal(run('sessionStore.historyLength'),history);
        assert.deepEqual([...storage.entries()],persisted);
        run('closePositionEditor()');
        assert.deepEqual(value('captureGameState()'),before);
        assert.equal(element('position-overlay').classList.contains('hidden'),true);
    """,
    'clear_draft_is_preview_only_and_zero_stays_distinct_from_unplayed': r"""
        await score(0,1);
        const before = value('captureGameState()');
        run('openPositionEditor(); clearPositionDraft();');
        assert.deepEqual(value('readPositionDraft().player1_scores'),{});
        assert.deepEqual(value('readPositionDraft().player2_scores'),{});
        assert.match(element('position-preview').textContent,/Turn 1 of 26/);
        element('position-1-0').value='0';
        run('updatePositionPreview()');
        assert.deepEqual(value('readPositionDraft().player1_scores'),{'0':0});
        assert.match(element('position-preview').textContent,/Turn 2 of 26/);
        assert.deepEqual(value('captureGameState()'),before);
    """,
    'loads_turn_twenty_position_and_requests_move_for_the_imported_player_and_dice': r"""
        await score(0,1);
        const before = value('captureGameState()');
        const history = run('sessionStore.historyLength');
        openLatePosition();
        const pending = run('applyPositionEditor()');
        const validation = requests.at(-1);
        assert.equal(validation.url,'/api/validate_position');
        const draft = JSON.parse(validation.options.body);
        assert.equal(draft.player1_scores['0'],0);
        assert.equal(draft.player2_scores['0'],undefined);
        assert.equal(draft.active_player,2);
        assert.equal(draft.rolls_remaining,0);
        assert.equal(draft.player1_yahtzee_bonuses,1);
        assert.deepEqual(draft.dice,[4,4,4,3,2]);
        assert.equal(element('position-apply').disabled,true);
        answer(validation,{position:latePosition}); await pending;
        assert.equal(run('currentTurn'),20);
        assert.equal(run('activePlayer'),2);
        assert.equal(run('calculateFinalScore(1)'),325);
        assert.equal(run('calculateFinalScore(2)'),248);
        assert.equal(run('rollsRemaining'),0);
        assert.equal(run('sessionStore.historyLength'),history+1);
        assert.equal(run('sessionStore.undoLabel'),'loaded position');
        const solve = requests.at(-1);
        assert.equal(solve.url,'/api/recommend');
        const solveBody = JSON.parse(solve.options.body);
        assert.deepEqual(solveBody.scores,draft.player2_scores);
        assert.deepEqual(solveBody.dice,draft.dice);
        assert.equal(solveBody.yahtzee_status,2);
        assert.equal(solveBody.rolls_remaining,0);
        answer(solve,recommendation(6,17)); await flush();
        assert.equal(run('lastRecommendation.category'),6);
        assert.equal(element('confirm-score-btn').disabled,false);
        const imported=value('captureGameState()');
        assert.equal(element('undo-btn').disabled,true,'Undo Last must not jump across an imported game');
        run('goBack()');
        assert.deepEqual(value('captureGameState()'),imported);
        run('restorePreviousPosition()');
        assert.deepEqual(value('playerScores'),before.playerScores);
        assert.deepEqual(value('gameLog'),before.gameLog);
        assert.equal(run('currentTurn'),before.currentTurn);
        run('goForward()');
        assert.equal(run('currentTurn'),20);
        assert.equal(run('calculateFinalScore(1)'),325);
        assert.equal(run('calculateFinalScore(2)'),248);
        assert.deepEqual(value('getDice()'),latePosition.dice);
        assert.deepEqual(value('gameLog'),[]);
    """,
    'backend_validation_failure_keeps_game_and_all_history_untouched': r"""
        await score(0,1); await score(0,1); run('goBack()');
        const before = value('captureGameState()');
        const history = [run('sessionStore.historyLength'),run('sessionStore.redoLength')];
        const persisted = [...storage.entries()];
        run('openPositionEditor()');
        element('position-bonus-1').value='1';
        const pending=run('applyPositionEditor()');
        answer(requests.at(-1),{error:'player1_yahtzee_bonuses requires a scored Yahtzee'},400);
        await pending;
        assert.deepEqual(value('captureGameState()'),before);
        assert.deepEqual([run('sessionStore.historyLength'),run('sessionStore.redoLength')],history);
        assert.deepEqual([...storage.entries()],persisted);
        assert.equal(element('position-overlay').classList.contains('hidden'),false);
        assert.equal(element('position-apply').disabled,false);
        assert.match(element('position-error').textContent,/requires a scored Yahtzee/);
    """,
    'cancel_pending_validation_prevents_its_late_success_from_replacing_game': r"""
        await score(0,1);
        const before=value('captureGameState()');
        const history=run('sessionStore.historyLength');
        openLatePosition();
        const pending=run('applyPositionEditor()');
        const request=requests.at(-1);
        run('closePositionEditor()');
        answer(request,{position:latePosition}); await pending;
        assert.deepEqual(value('captureGameState()'),before);
        assert.equal(run('sessionStore.historyLength'),history);
        assert.equal(requests.at(-1).url,'/api/validate_position');
        assert.equal(element('position-overlay').classList.contains('hidden'),true);
    """,
    'late_old_request_does_not_enable_button_during_new_validation': r"""
        openLatePosition();
        const oldPending=run('applyPositionEditor()');
        const oldRequest=requests.at(-1);
        run('closePositionEditor(); clearPositionDraft();');
        const currentPending=run('applyPositionEditor()');
        const currentRequest=requests.at(-1);
        assert.equal(element('position-apply').disabled,true);
        answer(oldRequest,{position:latePosition}); await oldPending;
        assert.equal(element('position-apply').disabled,true,'Old request must not change new request controls');
        answer(currentRequest,{error:'Invalid position'},400); await currentPending;
        assert.equal(element('position-apply').disabled,false);
        assert.equal(run('currentTurn'),1);
    """,
    'editing_dice_while_validation_pending_cannot_apply_an_obsolete_draft': r"""
        const before=value('captureGameState()');
        openLatePosition();
        const pending=run('applyPositionEditor()');
        const request=requests.at(-1);
        element('position-die-1').value='6';
        answer(request,{position:latePosition}); await pending;
        assert.deepEqual(value('captureGameState()'),before);
        assert.equal(element('position-overlay').classList.contains('hidden'),false);
        assert.equal(element('position-apply').disabled,false);
        assert.ok(element('position-error').textContent.length>0,'Changed draft should explain why it was not loaded');
        assert.equal(run('sessionStore.historyLength'),0);
    """,
    'corrupt_persisted_scores_and_logs_leave_a_fresh_working_game': r"""
        const fresh=value('captureGameState()');
        const corruptions=[
            state=>{state.playerScores['1']['0']=99;},
            state=>{state.gameLog=[null];},
            state=>{state.gameLog=[{}];},
            state=>{state.currentTurnData={};},
            state=>{state.currentTurnData={rolls:'bad'};},
        ];
        for(const corrupt of corruptions) {
            const bad=structuredClone(fresh); corrupt(bad);
            storage.set('ysolver.session.v1',JSON.stringify({version:1,current:bad,undo:[],redo:[]}));
            assert.doesNotThrow(()=>run('initializeGameSession()'),'Corrupt stored data must never break startup');
            assert.deepEqual(value('playerScores'),{'1':{},'2':{}});
            assert.deepEqual(value('gameLog'),[]);
            assert.equal(run('currentTurn'),1);
            assert.equal(run('sessionStore.historyLength'),0);
            assert.ok(Array.isArray(value('currentTurnData.rolls')));
        }
    """,
    'partial_dice_import_refreshes_odds_but_does_not_guess_missing_dice': r"""
        openLatePosition();
        element('position-die-2').value='';
        const pending=run('applyPositionEditor()');
        const request=requests.at(-1);
        const draft=JSON.parse(request.options.body);
        const probabilityCount=probabilityStates.length;
        answer(request,{position:validated(draft)}); await pending;
        assert.equal(run('currentTurn'),20);
        assert.deepEqual(value('getDice()'),[4,null,4,3,2]);
        assert.equal(requests.at(-1).url,'/api/validate_position');
        assert.ok(probabilityStates.length>probabilityCount);
        assert.equal(run('lastRecommendation'),null);
        assert.equal(element('confirm-score-btn').disabled,true);
    """,
    'imported_roll_can_be_recalculated_repeatedly_and_still_scored_and_undone': r"""
        openLatePosition();
        const pending=run('applyPositionEditor()');
        answer(requests.at(-1),{position:latePosition}); await pending;
        answer(requests.at(-1),recommendation(6,17)); await flush();
        for(let retry=0;retry<4;retry++) await showRecommendation(6,17,latePosition.dice);
        assert.equal(run('validGameSnapshot(captureGameState())'),true);
        assert.doesNotThrow(()=>run('selectScoringOption(6,17)'));
        assert.equal(run('playerScores[2][6]'),17);
        assert.equal(run('currentTurn'),21);
        assert.equal(run('calculateFinalScore(2)'),265);
        run('goBack()');
        assert.equal(run('playerScores[2][6]'),undefined);
        assert.equal(run('currentTurn'),20);
        assert.equal(run('calculateFinalScore(2)'),248);
        const imported=value('captureGameState()');
        run('goBack()');
        assert.deepEqual(value('captureGameState()'),imported,'Undo stops at the loaded game baseline');
        run('restorePreviousPosition()');
        assert.deepEqual(value('playerScores'),{'1':{},'2':{}});
        assert.equal(run('currentTurn'),1);
        run('goForward()');
        assert.equal(run('currentTurn'),20);
        assert.equal(run('calculateFinalScore(2)'),248);
    """,
}


@pytest.mark.skipif(NODE is None, reason='Node is needed for the frontend editor harness')
@pytest.mark.parametrize('case', CASES)
def test_position_editor_ui(case):
    script = EDITOR_HARNESS + HELPERS + CASES[case] + '\n})().then(() => {completed = true}).catch(error => {completed = true; console.error(error); process.exitCode = 1});\n'
    completed = subprocess.run([NODE, '-e', script, str(TEMPLATE)], capture_output=True, text=True, timeout=15)
    assert completed.returncode == 0, completed.stdout + completed.stderr
