/* Transactional browser session and a scorecard editor for joining a game. */
let sessionStore = null;
let sessionActionDepth = 0;
let restoringGameSession = false;
let recommendationRequestSequence = 0;
let recommendationRequestController = null;
let lastRecommendationKey = null;
let positionRequestSequence = 0;
let browserStorageAvailable = false;
const cloneGameData = value => JSON.parse(JSON.stringify(value));

function validCategoryScore(category, value) {
    if (!Number.isInteger(value) || value < 0) return false;
    if (category < 6) return value <= (category + 1) * 5 && value % (category + 1) === 0;
    const fixed = {8:25, 9:30, 10:40, 11:50};
    return fixed[category] ? value === 0 || value === fixed[category] : value === 0 || (value >= 5 && value <= 30);
}

function validGameSnapshot(state) {
    if (!state || ![1,2].includes(state.activePlayer) || ![0,1,2].includes(state.rollsRemaining) ||
        !Array.isArray(state.dice) || state.dice.length !== 5 ||
        state.dice.some(d => d !== null && (!Number.isInteger(d) || d < 1 || d > 6)) ||
        !Array.isArray(state.gameLog) || state.gameLog.length > 26) return false;
    const validRoll = roll => roll && [0,1,2].includes(roll.rollsRemaining) && Array.isArray(roll.dice) &&
        roll.dice.length === 5 && roll.dice.every(d=>Number.isInteger(d)&&d>=1&&d<=6);
    const validTurn = (turn, completed) => turn && [1,2].includes(turn.player) &&
        Number.isInteger(turn.turn) && turn.turn>=1 && turn.turn<=26 && Array.isArray(turn.rolls) &&
        turn.rolls.length<=3 && turn.rolls.every(validRoll) &&
        ['optimalEV','actualEV','evLoss'].every(key=>turn[key]===null || Number.isFinite(turn[key])) &&
        (!completed || (typeof turn.finalCategory==='string' && Number.isInteger(turn.finalPoints)));
    if (!state.gameLog.every(turn=>validTurn(turn,true)) ||
        (state.currentTurnData != null && !validTurn(state.currentTurnData,false))) return false;
    for (const p of [1,2]) {
        const scores = state.playerScores?.[p];
        if (!scores || typeof scores !== 'object' || Array.isArray(scores)) return false;
        for (const [cat, value] of Object.entries(scores)) {
            if (!/^(?:[0-9]|1[0-2])$/.test(cat) || !validCategoryScore(Number(cat), value)) return false;
        }
        const status = scores[11] === undefined ? 0 : scores[11] === 50 ? 2 : 1;
        const bonuses = state.yahtzeeBonuses?.[p];
        if (state.yahtzeeStatus?.[p] !== status || !Number.isInteger(bonuses) || bonuses < 0 || bonuses > 12 ||
            (bonuses > 0 && (status !== 2 || bonuses >= Object.keys(scores).length))) return false;
    }
    return true;
}

function captureGameState() {
    return cloneGameData({playerScores, yahtzeeStatus, yahtzeeBonuses, activePlayer, currentTurn,
        rollsRemaining, dice:getDice(), currentDieIndex, diceEntered, gameLog, currentTurnData,
        keptDiceIndices, waitingForAction, allDiceFilled, lastRecommendation, lastRecommendationKey});
}

function recommendationRequestBody() {
    return {dice:getDice(), rolls_remaining:rollsRemaining, scores:cloneGameData(playerScores[activePlayer]),
        mode:'joker', yahtzee_status:yahtzeeStatus[activePlayer], yahtzee_bonuses:yahtzeeBonuses[activePlayer]};
}

function recommendationStateKey() {
    return JSON.stringify([activePlayer, recommendationRequestBody()]);
}

function invalidateRecommendation() {
    recommendationRequestSequence++;
    recommendationRequestController?.abort();
    recommendationRequestController = null;
    lastRecommendation = null;
    lastRecommendationKey = null;
    const button = document.getElementById('confirm-score-btn');
    if (button) {button.disabled = true; button.textContent = 'Pick Category to Score';}
    const options = document.getElementById('category-options');
    if (options) options.innerHTML = '';
    const panel = document.getElementById('recommendation');
    if (panel) panel.innerHTML = '<div class="rec-action">Enter dice and get a move</div><div class="rec-details">Recommendations use the current player, scorecard and dice.</div>';
}

function updateSessionControls(message) {
    const undo = document.getElementById('undo-btn');
    const redo = document.getElementById('redo-btn');
    const atImportedStart = sessionStore?.undoLabel === 'loaded position';
    if (undo) {undo.disabled = !sessionStore?.canUndo || atImportedStart; undo.title = atImportedStart ? 'Start of this loaded game' : sessionStore?.undoLabel || 'Nothing to undo';}
    if (redo) {redo.disabled = !sessionStore?.canRedo; redo.title = sessionStore?.redoLabel || 'Nothing to redo';}
    document.getElementById('restore-position-btn')?.classList.toggle('hidden',!atImportedStart);
    const status = document.getElementById('session-status');
    if (status) status.textContent = !browserStorageAvailable || sessionStore?.storageError ? 'Browser storage unavailable. Keep this tab open.' :
        message || 'Saved in this browser';
}

function persistGameSession() {
    if (!sessionStore || restoringGameSession || sessionActionDepth) return;
    const snapshot = captureGameState();
    if (validGameSnapshot(snapshot)) sessionStore.replaceCurrent(snapshot);
    updateSessionControls();
}

function withGameAction(label, action) {
    if (restoringGameSession || sessionActionDepth || !sessionStore) return action();
    const before = captureGameState();
    sessionStore.replaceCurrent(before);
    sessionActionDepth++;
    try {
        const result = action();
        const after = captureGameState();
        if (!validGameSnapshot(after)) throw new Error('That change would create an invalid scorecard.');
        sessionStore.commit(after, label);
        updateSessionControls();
        return result;
    } catch (error) {
        restoreGameState(before);
        throw error;
    } finally {sessionActionDepth--;}
}

function restoreGameState(snapshot) {
    if (!validGameSnapshot(snapshot)) throw new Error('This saved position is invalid.');
    restoringGameSession = true;
    try {
        invalidateRecommendation();
        const state = cloneGameData(snapshot);
        playerScores = state.playerScores;
        yahtzeeStatus = state.yahtzeeStatus;
        yahtzeeBonuses = state.yahtzeeBonuses;
        activePlayer = state.activePlayer;
        currentTurn = Math.min(26, 1 + Object.keys(playerScores[1]).length + Object.keys(playerScores[2]).length);
        rollsRemaining = state.rollsRemaining;
        gameLog = state.gameLog;
        currentTurnData = state.currentTurnData || null;
        for (const p of [1,2]) {
            for (let cat=0;cat<13;cat++) {
                const input = document.getElementById(`score-${p}-${cat}`);
                const row = document.getElementById(`row-${p}-${cat}`);
                const value = playerScores[p][cat];
                if (input) input.value = value ?? '';
                row?.classList.toggle('filled', value !== undefined);
                const toggle = document.getElementById(`toggle-${p}-${cat}`);
                if (toggle) {
                    toggle.querySelector('.score-btn')?.classList.toggle('active', value > 0);
                    toggle.querySelector('.zero-btn')?.classList.toggle('active', value === 0);
                }
            }
            updateTotals(p); updateJokerBonusDisplay(p);
        }
        for (let i=1;i<=5;i++) {
            const input = document.getElementById(`die-${i}`);
            const visual = document.getElementById(`visual-die-${i}`);
            input.value = state.dice[i-1] ?? '';
            input.classList.toggle('filled', state.dice[i-1] !== null);
            visual.textContent = state.dice[i-1] ?? '?';
            visual.classList.remove('keep','reroll');
        }
        currentDieIndex = state.currentDieIndex >= 1 && state.currentDieIndex <= 5 ? state.currentDieIndex : 1;
        diceEntered = state.dice.filter(d=>d!==null).length;
        allDiceFilled = diceEntered === 5;
        keptDiceIndices = Array.isArray(state.keptDiceIndices) ? state.keptDiceIndices.filter(i=>Number.isInteger(i)&&i>=1&&i<=5) : [];
        waitingForAction = Boolean(state.waitingForAction);
        lastCelebratedYahtzee = null;
        setActivePlayer(activePlayer); setRolls(rollsRemaining); updateTurnDisplay(); updateCurrentDieIndicator();
        if (!currentTurnData) initTurn();
        updateGameLogDisplay();
        document.getElementById('end-game-overlay')?.classList.add('hidden');
        if (state.lastRecommendation && state.lastRecommendationKey === recommendationStateKey()) {
            lastRecommendation = state.lastRecommendation; lastRecommendationKey = state.lastRecommendationKey;
            displayRecommendation(lastRecommendation);
            keptDiceIndices = state.keptDiceIndices || [];
            for (let i=1;i<=5;i++) {
                const classes = document.getElementById(`visual-die-${i}`).classList;
                classes.toggle('keep',lastRecommendation.action==='keep' && keptDiceIndices.includes(i));
                classes.toggle('reroll',lastRecommendation.action==='keep' && !keptDiceIndices.includes(i));
            }
            document.getElementById('confirm-score-btn').disabled = false;
        }
        updateWinProbabilities();
    } finally {restoringGameSession = false;}
}

function goBack() {
    if (!sessionStore?.canUndo || sessionStore.undoLabel === 'loaded position') return;
    const label = sessionStore.undoLabel;
    sessionStore.replaceCurrent(captureGameState());
    restoreGameState(sessionStore.undo());
    updateSessionControls(`Undid ${label}. Redo is available.`);
}

function restorePreviousPosition() {
    if (sessionStore?.undoLabel !== 'loaded position') return;
    sessionStore.replaceCurrent(captureGameState());
    restoreGameState(sessionStore.undo());
    updateSessionControls('Previous game restored. Redo can reopen the loaded position.');
}

function goForward() {
    if (!sessionStore?.canRedo) return;
    const label = sessionStore.redoLabel;
    restoreGameState(sessionStore.redo());
    updateSessionControls(`Restored ${label}.`);
}

function initializeGameSession() {
    let storage = null;
    try {storage = window.localStorage;} catch (_) {}
    browserStorageAvailable = Boolean(storage);
    sessionStore = new YSolverSession.SessionStore({storage,validate:validGameSnapshot});
    const saved = sessionStore.load();
    if (saved) restoreGameState(saved); else sessionStore.initialize(captureGameState());
    updateSessionControls(saved ? 'Restored your saved game' : undefined);
    // A recovery/share link opens an editable preview; it never silently replaces a game.
    if (window.location.hash.startsWith('#position=')) {
        try {openPositionEditor(JSON.parse(decodeURIComponent(window.location.hash.slice(10))));}
        catch (_) {updateSessionControls('The position link could not be read. Your game is unchanged.');}
    }
}

function positionFromGame() {
    return {player1_scores:cloneGameData(playerScores[1]),player2_scores:cloneGameData(playerScores[2]),
        player1_yahtzee_bonuses:yahtzeeBonuses[1],player2_yahtzee_bonuses:yahtzeeBonuses[2],
        active_player:activePlayer,rolls_remaining:rollsRemaining,dice:getDice()};
}

function openPositionEditor(position) {
    positionRequestSequence++;
    const draft = position || positionFromGame();
    const rows = categories.map(category => {
        const values = category.id < 6 ? Array.from({length:6},(_,i)=>i*(category.id+1)) :
            category.fixedScore ? [0,category.fixedScore] : [0,...Array.from({length:26},(_,i)=>i+5)];
        const cells = [1,2].map(p => {
            const value = draft[`player${p}_scores`]?.[category.id];
            return `<td><select id="position-${p}-${category.id}" aria-label="Player ${p} ${category.name}" onchange="updatePositionPreview()"><option value="">Unplayed</option>${values.map(v=>`<option value="${v}" ${value===v?'selected':''}>${v===0?'0 — scratch':v}</option>`).join('')}</select></td>`;
        }).join('');
        return `<tr><th scope="row">${category.name}</th>${cells}</tr>`;
    }).join('');
    document.getElementById('position-score-rows').innerHTML = rows;
    for (const p of [1,2]) document.getElementById(`position-bonus-${p}`).value = draft[`player${p}_yahtzee_bonuses`] ?? 0;
    document.getElementById('position-player').value = draft.active_player ?? 1;
    document.getElementById('position-rolls').value = draft.rolls_remaining ?? 2;
    for (let i=1;i<=5;i++) document.getElementById(`position-die-${i}`).value = draft.dice?.[i-1] ?? '';
    document.getElementById('position-error').textContent = '';
    document.getElementById('position-apply').disabled = false;
    document.getElementById('position-overlay').classList.remove('hidden');
    updatePositionPreview();
    document.getElementById('position-1-0').focus();
}

function closePositionEditor() {
    positionRequestSequence++;
    document.getElementById('position-overlay').classList.add('hidden');
    if (window.location.hash.startsWith('#position=')) {
        window.history?.replaceState(null,'',window.location.pathname+window.location.search);
    }
    document.getElementById('position-open')?.focus();
}

function clearPositionDraft() {openPositionEditor({player1_scores:{},player2_scores:{},active_player:1,rolls_remaining:2,dice:[]});}

function readPositionDraft() {
    const draft = {active_player:Number(document.getElementById('position-player').value),
        rolls_remaining:Number(document.getElementById('position-rolls').value),dice:[]};
    for (const p of [1,2]) {
        draft[`player${p}_scores`] = {};
        for (let cat=0;cat<13;cat++) {
            const value = document.getElementById(`position-${p}-${cat}`).value;
            if (value !== '') draft[`player${p}_scores`][cat] = Number(value);
        }
        draft[`player${p}_yahtzee_bonuses`] = Number(document.getElementById(`position-bonus-${p}`).value);
    }
    for (let i=1;i<=5;i++) {
        const value = document.getElementById(`position-die-${i}`).value;
        draft.dice.push(value === '' ? null : Number(value));
    }
    return draft;
}

function updatePositionPreview() {
    const draft = readPositionDraft();
    const totals = [1,2].map(p => {
        const scores = draft[`player${p}_scores`];
        const upper = Object.entries(scores).reduce((sum,[cat,value])=>sum+(Number(cat)<6?value:0),0);
        return Object.values(scores).reduce((sum,v)=>sum+v,0)+(upper>=63?35:0)+100*draft[`player${p}_yahtzee_bonuses`];
    });
    const filled = Object.keys(draft.player1_scores).length+Object.keys(draft.player2_scores).length;
    document.getElementById('position-preview').textContent = `${filled===26?'Completed game':`Turn ${filled+1} of 26`} · Player 1: ${totals[0]} points · Player 2: ${totals[1]} points. Turn number follows the filled categories.`;
}

function applyValidatedPosition(position) {
    withGameAction('loaded position', () => {
        const scores = p => Object.fromEntries(Object.entries(position[`player${p}_scores`]).filter(([,v])=>v!==null));
        const snapshot = {playerScores:{1:scores(1),2:scores(2)},
            yahtzeeStatus:{1:position.player1_yahtzee_status,2:position.player2_yahtzee_status},
            yahtzeeBonuses:{1:position.player1_yahtzee_bonuses,2:position.player2_yahtzee_bonuses},
            activePlayer:position.active_player,currentTurn:position.current_turn,rollsRemaining:position.rolls_remaining,
            dice:position.dice,currentDieIndex:Math.max(1,position.dice.indexOf(null)+1),gameLog:[],
            currentTurnData:null,keptDiceIndices:[],waitingForAction:false,lastRecommendation:null,lastRecommendationKey:null};
        restoreGameState(snapshot);
    });
}

async function applyPositionEditor() {
    const draft = readPositionDraft();
    const sequence = ++positionRequestSequence;
    const button = document.getElementById('position-apply');
    const error = document.getElementById('position-error');
    button.disabled = true; error.textContent = 'Checking position…';
    try {
        const response = await fetch('/api/validate_position',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(draft)});
        const body = await response.json();
        if (sequence !== positionRequestSequence) return;
        if (JSON.stringify(draft) !== JSON.stringify(readPositionDraft())) throw new Error('The position changed while checking. Load the updated position again.');
        if (!response.ok) throw new Error(body.error || 'The position could not be loaded.');
        applyValidatedPosition(body.position);
        closePositionEditor();
        updateSessionControls('Position loaded and saved. Undo will stop at this starting point.');
        if (body.position.dice.every(d=>d!==null) && !body.position.completed) getRecommendation();
    } catch (failure) {
        if (sequence===positionRequestSequence) error.textContent=failure.message
            .replace(/player([12])_scores\.([0-9]+)/g,(_,p,cat)=>`Player ${p} ${categories[Number(cat)]?.name || 'score'}`)
            .replace(/player([12])_yahtzee_bonuses/g,(_,p)=>`Player ${p} extra Yahtzees`)
            .replace(/active_player/g,'Selected player').replace(/rolls_remaining/g,'Rerolls left');
    }
    finally {if (sequence===positionRequestSequence) button.disabled=false;}
}

// One transaction includes scoring, its bonus, the log and the next player.
const originalSelectScoringOption = selectScoringOption;
selectScoringOption = (cat,points) => withGameAction('scored turn', () => originalSelectScoringOption(cat,points));
const originalUpdateScore = updateScore;
updateScore = (player,cat,value) => {
    if (value !== '' && value !== null && !validCategoryScore(cat,Number(value))) {
        document.getElementById(`score-${player}-${cat}`).value = playerScores[player][cat] ?? '';
        updateSessionControls('That score is not valid for this category.'); return;
    }
    return withGameAction('score edit',()=>originalUpdateScore(player,cat,value));
};
const originalSetFixedScore = setFixedScore;
setFixedScore = (player,cat,value) => withGameAction('scored category',()=>originalSetFixedScore(player,cat,value));
const originalClearDice = clearDice;
clearDice = () => withGameAction('cleared dice',()=>{invalidateRecommendation();return originalClearDice();});
const originalAdvanceToNextRoll = advanceToNextRoll;
advanceToNextRoll = () => withGameAction('next roll',()=>{invalidateRecommendation();return originalAdvanceToNextRoll();});
const originalSilentAdvance = silentAdvanceToNextRoll;
silentAdvanceToNextRoll = () => withGameAction('next roll',()=>{invalidateRecommendation();return originalSilentAdvance();});
const originalDiceInput = handleDiceInput;
handleDiceInput = (index,value) => {const result=originalDiceInput(index,value);invalidateRecommendation();persistGameSession();return result;};
const originalKeepToggle = toggleDieKeep;
toggleDieKeep = index => {const result=originalKeepToggle(index);persistGameSession();return result;};
const originalSetActivePlayer = setActivePlayer;
setActivePlayer = player => {
    const changed = activePlayer !== player;
    const result=originalSetActivePlayer(player);
    updateTurnDisplay();
    if (changed && !restoringGameSession) {invalidateRecommendation();initTurn();persistGameSession();}
    return result;
};
const originalSetRolls = setRolls;
setRolls = rolls => {
    const changed = rollsRemaining !== rolls;
    const result=originalSetRolls(rolls);
    if (changed && !restoringGameSession) {invalidateRecommendation();persistGameSession();}
    return result;
};

window.addEventListener('pagehide',persistGameSession);
document.addEventListener('keydown',event=>{
    const overlay = document.getElementById('position-overlay');
    if (overlay.classList.contains('hidden')) return;
    if (event.key==='Escape') {event.preventDefault();closePositionEditor();}
    if (event.key==='Tab') {
        const focusable = [...overlay.querySelectorAll('button:not(:disabled), select, input')];
        const first = focusable[0], last = focusable[focusable.length-1];
        if (event.shiftKey && document.activeElement===first) {event.preventDefault();last.focus();}
        else if (!event.shiftKey && document.activeElement===last) {event.preventDefault();first.focus();}
    }
});
window.addEventListener('hashchange',()=>{
    if (window.location.hash.startsWith('#position=')) {
        try {openPositionEditor(JSON.parse(decodeURIComponent(window.location.hash.slice(10))));} catch (_) {}
    }
});
