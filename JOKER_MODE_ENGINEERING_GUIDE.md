# Yahtzee Joker Mode - Engineering Implementation Guide

## Overview

This document provides a comprehensive guide for implementing **Yahtzee Joker Mode** alongside the existing Traditional Mode. The implementation requires changes to the state space, scoring logic, DP solver, and UI while maintaining backward compatibility with the current solver.

---

## Table of Contents

1. [Yahtzee Joker Rules](#1-yahtzee-joker-rules)
2. [Current Architecture Overview](#2-current-architecture-overview)
3. [New State Space Design](#3-new-state-space-design)
4. [File-by-File Implementation Guide](#4-file-by-file-implementation-guide)
5. [Cache Strategy](#5-cache-strategy)
6. [Performance Optimization with Numba](#6-performance-optimization-with-numba)
7. [UI Changes](#7-ui-changes)
8. [Testing Strategy](#8-testing-strategy)
9. [Migration & Deployment](#9-migration--deployment)
10. [Appendix: Mathematical Details](#10-appendix-mathematical-details)

---

## 1. Yahtzee Joker Rules

### 1.1 Standard Yahtzee Bonus
- First Yahtzee: Score 50 points in Yahtzee category (or 0 if you choose to waste it)
- Second+ Yahtzee: **+100 bonus chips** (if you scored 50 on first Yahtzee)

### 1.2 Joker Scoring Rules (When Rolling Additional Yahtzees)

**Priority Order (MUST follow):**

1. **Upper Section First**: If the corresponding upper section is open, you MUST score there
   - Example: Roll five 4s → Must score in "Fours" (4 × 5 = 20 points) + 100 bonus

2. **Lower Section Joker**: If upper section is filled, score in ANY open lower section:
   - Three of a Kind: Sum of all dice
   - Four of a Kind: Sum of all dice
   - Full House: **25 points** (joker exception - not actually a full house)
   - Small Straight: **30 points** (joker exception)
   - Large Straight: **40 points** (joker exception)
   - Chance: Sum of all dice

3. **Zero Out**: If all lower sections filled, must score 0 in any remaining upper section

### 1.3 Joker Bonus Tracking
- Bonus is **only awarded** if original Yahtzee category has 50 points
- If you scored 0 in Yahtzee (scratched it), subsequent Yahtzees get NO bonus
- Each additional Yahtzee = +100 bonus (can get 200, 300, etc. in a game)

---

## 2. Current Architecture Overview

### 2.1 File Structure
```
ysolver/
├── dice.py              # Dice enumeration (252 unique rolls)
├── scoring.py           # Scoring rules for 13 categories
├── transitions.py       # Keep/reroll transition probabilities
├── ev_solver.py         # Dynamic programming EV solver
├── pmf_solver.py        # Probability mass function calculations
├── precompute_fast.py   # Numba-accelerated precomputation
├── match.py             # Two-player match analysis
├── web_app.py           # Flask API server
├── cli.py               # Command-line interface
├── ev_cache.pkl         # Precomputed DP tables (~136MB)
└── templates/
    └── index.html       # Web UI
```

### 2.2 Current State Space
```python
# Current state tuple:
(roll_idx, mask, upper)

# Where:
# - roll_idx: 0-251 (252 possible dice multisets)
# - mask: 0-8191 (13-bit bitmask for filled categories)
# - upper: 0-63 (clamped upper section total for bonus tracking)

# Total states: 252 × 8192 × 64 = 132,120,576 states
```

### 2.3 Current DP Recurrence
```python
# v3(roll, mask, upper) = max over unfilled categories of:
#     score(roll, cat) + ev_remaining(new_mask, new_upper)

# v2(roll, mask, upper) = max over keep options of:
#     E[v3(next_roll, mask, upper)]

# v1(roll, mask, upper) = max over keep options of:
#     E[v2(next_roll, mask, upper)]
```

---

## 3. New State Space Design

### 3.1 Additional State Variable
```python
# New state tuple for Joker Mode:
(roll_idx, mask, upper, yahtzee_status)

# Where yahtzee_status is:
# - 0: Yahtzee category not yet filled
# - 1: Yahtzee filled with 0 (scratched - no future bonuses)
# - 2: Yahtzee filled with 50 (eligible for joker bonuses)

# New total states: 252 × 8192 × 64 × 3 = 396,361,728 states
# Approximately 3x the current cache size
```

### 3.2 State Encoding
```python
# Option A: Separate arrays (recommended for clarity)
ev_remaining_traditional[mask][upper]      # Current format
ev_remaining_joker[mask][upper][yahtzee_status]  # New format

# Option B: Combined encoding (more compact)
# Encode yahtzee_status into upper bits of mask
extended_mask = mask | (yahtzee_status << 13)  # 15-bit mask
```

### 3.3 Recommended Approach
Use **Option A** with separate cache files:
- `ev_cache_traditional.pkl` - Current solver (no changes needed)
- `ev_cache_joker.pkl` - New joker mode solver

This allows:
- Backward compatibility
- Independent updates
- Mode selection at runtime

---

## 4. File-by-File Implementation Guide

### 4.1 `scoring.py` - Scoring Logic Changes

#### Current Structure:
```python
CATEGORY_NAMES = [
    "Ones", "Twos", "Threes", "Fours", "Fives", "Sixes",
    "Three of a Kind", "Four of a Kind", "Full House",
    "Small Straight", "Large Straight", "Yahtzee", "Chance"
]

def get_score_table():
    """Returns score_table[roll_id][category] = points"""
    ...
```

#### Changes Required:

```python
# Add new function for joker scoring
def get_joker_score_table():
    """
    Returns joker_score_table[roll_id][category] = points

    For Yahtzee rolls (all 5 same), applies joker rules:
    - Full House = 25 (even for 5-of-a-kind)
    - Small Straight = 30
    - Large Straight = 40
    """
    table = np.zeros((NUM_ROLLS, NUM_CATEGORIES), dtype=np.int32)

    for roll_idx in range(NUM_ROLLS):
        counts = roll_to_counts(roll_idx)
        is_yahtzee = max(counts) == 5

        for cat in range(NUM_CATEGORIES):
            if is_yahtzee and cat in [8, 9, 10]:  # FH, SS, LS
                # Joker scoring
                table[roll_idx][cat] = [0, 0, 0, 0, 0, 0, 0, 0, 25, 30, 40, 0, 0][cat]
            else:
                # Normal scoring
                table[roll_idx][cat] = compute_score(counts, cat)

    return table


def is_yahtzee_roll(roll_idx: int) -> bool:
    """Check if roll is a Yahtzee (all 5 dice same)."""
    counts = roll_to_counts(roll_idx)
    return max(counts) == 5


def get_yahtzee_face(roll_idx: int) -> int:
    """For a Yahtzee roll, return which face (0-5 for 1-6)."""
    counts = roll_to_counts(roll_idx)
    for face, count in enumerate(counts):
        if count == 5:
            return face
    return -1  # Not a yahtzee


def get_forced_category_joker(roll_idx: int, mask: int) -> Optional[int]:
    """
    For joker rules, determine if there's a forced category.

    Returns:
        Category index if forced, None if player has choice
    """
    if not is_yahtzee_roll(roll_idx):
        return None

    face = get_yahtzee_face(roll_idx)
    upper_cat = face  # Categories 0-5 correspond to faces 1-6

    # Must use upper section if available
    if not (mask & (1 << upper_cat)):
        return upper_cat

    return None  # Free to choose from lower section
```

### 4.2 `ev_solver.py` - DP Solver Changes

#### New Constants:
```python
# Yahtzee status values
YAHTZEE_UNFILLED = 0
YAHTZEE_SCRATCHED = 1  # Filled with 0
YAHTZEE_SCORED = 2     # Filled with 50

# Yahtzee bonus
YAHTZEE_BONUS = 100

# Category index for Yahtzee
YAHTZEE_CATEGORY = 11
```

#### New EV Remaining Function:
```python
@njit(cache=True)
def ev_remaining_joker(mask: int, upper: int, yahtzee_status: int) -> float:
    """
    Expected remaining score for joker mode.

    Args:
        mask: 13-bit filled category mask
        upper: Upper section total (0-63, clamped)
        yahtzee_status: 0=unfilled, 1=scratched, 2=scored

    Returns:
        Expected additional points from remaining game
    """
    return _ev_remaining_joker_cache[mask, upper, yahtzee_status]


def compute_ev_remaining_joker():
    """
    Compute all EV values for joker mode via backward induction.

    Order: Iterate from 13 categories filled down to 0.
    """
    cache = np.zeros((8192, 64, 3), dtype=np.float64)

    # Base case: all categories filled
    for upper in range(64):
        for ys in range(3):
            bonus = 35.0 if upper >= 63 else 0.0
            cache[8191, upper, ys] = bonus

    # Backward induction
    for num_filled in range(12, -1, -1):
        for mask in masks_with_n_bits(num_filled):
            for upper in range(64):
                for yahtzee_status in range(3):
                    cache[mask, upper, yahtzee_status] = compute_turn_ev_joker(
                        mask, upper, yahtzee_status
                    )

    return cache
```

#### Modified Turn EV Computation:
```python
@njit(cache=True)
def compute_turn_ev_joker(mask: int, upper: int, yahtzee_status: int) -> float:
    """
    Compute expected value of one turn in joker mode.

    This is E[v1(first_roll)] averaged over all possible first rolls.
    """
    total = 0.0
    for roll_idx in range(NUM_ROLLS):
        prob = INITIAL_ROLL_PROBS[roll_idx]
        total += prob * v1_joker(roll_idx, mask, upper, yahtzee_status)
    return total


@njit(cache=True)
def v3_joker(roll_idx: int, mask: int, upper: int, yahtzee_status: int) -> float:
    """
    Value after third roll (must score) - Joker mode.
    """
    is_yahtzee = IS_YAHTZEE[roll_idx]
    yahtzee_face = YAHTZEE_FACE[roll_idx]  # -1 if not yahtzee

    best_ev = -np.inf

    # Check for joker bonus
    joker_bonus = 0.0
    if is_yahtzee and yahtzee_status == YAHTZEE_SCORED:
        joker_bonus = YAHTZEE_BONUS

    # Determine available categories
    for cat in range(NUM_CATEGORIES):
        if mask & (1 << cat):
            continue  # Already filled

        # Check joker forcing rule
        if is_yahtzee and yahtzee_status == YAHTZEE_SCORED:
            forced_cat = get_forced_category_joker_jit(yahtzee_face, mask)
            if forced_cat is not None and cat != forced_cat:
                continue  # Must use forced category

        # Compute score for this category
        if is_yahtzee and yahtzee_status == YAHTZEE_SCORED:
            pts = JOKER_SCORE_TABLE[roll_idx, cat]
        else:
            pts = SCORE_TABLE[roll_idx, cat]

        # Update state
        new_mask = mask | (1 << cat)
        new_upper = min(63, upper + pts) if cat < 6 else upper

        # Update yahtzee status if scoring in yahtzee category
        new_ys = yahtzee_status
        if cat == YAHTZEE_CATEGORY:
            new_ys = YAHTZEE_SCORED if pts == 50 else YAHTZEE_SCRATCHED

        # Compute EV
        ev = pts + joker_bonus + ev_remaining_joker(new_mask, new_upper, new_ys)
        best_ev = max(best_ev, ev)

    return best_ev
```

### 4.3 `precompute_fast.py` - Numba-Accelerated Precomputation

#### New Precomputation Pipeline:
```python
"""
Joker Mode Precomputation Pipeline

This module generates all lookup tables and EV caches for joker mode.
Uses Numba JIT for performance-critical inner loops.

Estimated runtime: 30-60 minutes on modern hardware.
"""

import numpy as np
from numba import njit, prange
import pickle
from pathlib import Path

# Constants
NUM_ROLLS = 252
NUM_CATEGORIES = 13
NUM_MASKS = 8192  # 2^13
NUM_UPPER = 64
NUM_YAHTZEE_STATUS = 3


@njit(parallel=True, cache=True)
def precompute_v3_joker(
    score_table: np.ndarray,
    joker_score_table: np.ndarray,
    ev_remaining: np.ndarray,
    is_yahtzee: np.ndarray,
    yahtzee_face: np.ndarray
) -> np.ndarray:
    """
    Precompute v3 (must-score) values for all states.

    Returns:
        v3[roll_idx, mask, upper, yahtzee_status] array
    """
    v3 = np.zeros((NUM_ROLLS, NUM_MASKS, NUM_UPPER, NUM_YAHTZEE_STATUS),
                  dtype=np.float64)

    for roll_idx in prange(NUM_ROLLS):  # Parallel over rolls
        for mask in range(NUM_MASKS):
            for upper in range(NUM_UPPER):
                for ys in range(NUM_YAHTZEE_STATUS):
                    v3[roll_idx, mask, upper, ys] = _compute_v3_single(
                        roll_idx, mask, upper, ys,
                        score_table, joker_score_table, ev_remaining,
                        is_yahtzee, yahtzee_face
                    )

    return v3


@njit(cache=True)
def _compute_v3_single(
    roll_idx: int, mask: int, upper: int, yahtzee_status: int,
    score_table: np.ndarray, joker_score_table: np.ndarray,
    ev_remaining: np.ndarray, is_yahtzee: np.ndarray, yahtzee_face: np.ndarray
) -> float:
    """Compute v3 for a single state."""

    is_ytz = is_yahtzee[roll_idx]
    ytz_face = yahtzee_face[roll_idx]

    # Joker bonus
    joker_bonus = 100.0 if (is_ytz and yahtzee_status == 2) else 0.0

    best_ev = -1e9

    for cat in range(NUM_CATEGORIES):
        if mask & (1 << cat):
            continue

        # Joker forcing rule
        if is_ytz and yahtzee_status == 2 and ytz_face >= 0:
            upper_cat = ytz_face
            if not (mask & (1 << upper_cat)):
                if cat != upper_cat:
                    continue

        # Score
        if is_ytz and yahtzee_status == 2:
            pts = joker_score_table[roll_idx, cat]
        else:
            pts = score_table[roll_idx, cat]

        # New state
        new_mask = mask | (1 << cat)
        new_upper = upper + pts if cat < 6 else upper
        new_upper = min(63, new_upper)

        new_ys = yahtzee_status
        if cat == 11:  # Yahtzee category
            new_ys = 2 if pts == 50 else 1

        ev = pts + joker_bonus + ev_remaining[new_mask, new_upper, new_ys]
        if ev > best_ev:
            best_ev = ev

    return best_ev


@njit(parallel=True, cache=True)
def precompute_v2_joker(
    v3: np.ndarray,
    keep_options: np.ndarray,
    transition_probs: np.ndarray,
    num_keeps: np.ndarray
) -> tuple:
    """
    Precompute v2 (one reroll remaining) values and best keep decisions.

    Returns:
        (v2 values array, best_keep indices array)
    """
    v2 = np.zeros((NUM_ROLLS, NUM_MASKS, NUM_UPPER, NUM_YAHTZEE_STATUS),
                  dtype=np.float64)
    best_keep = np.zeros((NUM_ROLLS, NUM_MASKS, NUM_UPPER, NUM_YAHTZEE_STATUS),
                         dtype=np.int32)

    for roll_idx in prange(NUM_ROLLS):
        for mask in range(NUM_MASKS):
            for upper in range(NUM_UPPER):
                for ys in range(NUM_YAHTZEE_STATUS):
                    v, k = _compute_v2_single(
                        roll_idx, mask, upper, ys,
                        v3, keep_options, transition_probs, num_keeps
                    )
                    v2[roll_idx, mask, upper, ys] = v
                    best_keep[roll_idx, mask, upper, ys] = k

    return v2, best_keep


def generate_joker_cache(output_path: str = "ev_cache_joker.pkl"):
    """
    Generate complete joker mode cache.

    Steps:
    1. Generate score tables (normal + joker)
    2. Precompute yahtzee detection arrays
    3. Backward induction for ev_remaining
    4. Forward pass for v3, v2, v1 with best keep decisions
    5. Save to pickle file
    """
    print("Generating Joker Mode Cache...")
    print("=" * 50)

    # Step 1: Score tables
    print("Step 1/5: Computing score tables...")
    score_table = get_score_table()
    joker_score_table = get_joker_score_table()

    # Step 2: Yahtzee detection
    print("Step 2/5: Computing yahtzee detection arrays...")
    is_yahtzee = np.array([is_yahtzee_roll(i) for i in range(NUM_ROLLS)])
    yahtzee_face = np.array([get_yahtzee_face(i) for i in range(NUM_ROLLS)])

    # Step 3: Backward induction for ev_remaining
    print("Step 3/5: Backward induction for EV remaining...")
    ev_remaining = compute_ev_remaining_joker_full()

    # Step 4: Forward computation
    print("Step 4/5: Computing v3, v2, v1 tables...")
    v3 = precompute_v3_joker(score_table, joker_score_table, ev_remaining,
                              is_yahtzee, yahtzee_face)

    keep_options, transition_probs, num_keeps = get_transition_data()
    v2, best_keep_v2 = precompute_v2_joker(v3, keep_options, transition_probs, num_keeps)
    v1, best_keep_v1 = precompute_v1_joker(v2, keep_options, transition_probs, num_keeps)

    # Step 5: Save
    print("Step 5/5: Saving cache...")
    cache = {
        'version': '2.0-joker',
        'score_table': score_table,
        'joker_score_table': joker_score_table,
        'is_yahtzee': is_yahtzee,
        'yahtzee_face': yahtzee_face,
        'ev_remaining': ev_remaining,
        'v3': v3,
        'v2': v2,
        'v1': v1,
        'best_keep_v2': best_keep_v2,
        'best_keep_v1': best_keep_v1,
    }

    with open(output_path, 'wb') as f:
        pickle.dump(cache, f, protocol=pickle.HIGHEST_PROTOCOL)

    size_mb = Path(output_path).stat().st_size / (1024 * 1024)
    print(f"Cache saved to {output_path} ({size_mb:.1f} MB)")
    print("=" * 50)
    print("Done!")


if __name__ == "__main__":
    generate_joker_cache()
```

### 4.4 `web_app.py` - API Changes

#### Mode Selection:
```python
# Add mode parameter to all endpoints

@app.route('/api/recommend', methods=['POST'])
def recommend():
    data = request.json

    dice = data.get('dice', [1, 1, 1, 1, 1])
    rolls_remaining = data.get('rolls_remaining', 2)
    player_scores = data.get('scores', {})
    mode = data.get('mode', 'traditional')  # NEW: 'traditional' or 'joker'
    yahtzee_status = data.get('yahtzee_status', 0)  # NEW: 0, 1, or 2
    yahtzee_bonuses = data.get('yahtzee_bonuses', 0)  # NEW: count of bonuses earned

    # Compute state
    filled = [int(k) for k, v in player_scores.items() if v is not None]
    mask = compute_mask(filled)
    upper = compute_upper_total(player_scores)

    # Get recommendation based on mode
    if mode == 'joker':
        rec = get_recommendation_joker(dice, mask, upper, rolls_remaining, yahtzee_status)
    else:
        rec = get_recommendation(dice, mask, upper, rolls_remaining)

    # Add joker-specific info to response
    if mode == 'joker':
        response['yahtzee_status'] = yahtzee_status
        response['yahtzee_bonuses'] = yahtzee_bonuses
        response['is_yahtzee_roll'] = is_yahtzee_roll(roll_id(dice_list_to_counts(dice)))

        # Check if this roll would trigger joker bonus
        if response['is_yahtzee_roll'] and yahtzee_status == 2:
            response['joker_bonus_available'] = True
            response['forced_category'] = get_forced_category_joker(...)

    return jsonify(response)
```

### 4.5 `templates/index.html` - UI Changes

#### Mode Selection on Start:
```javascript
// Add joker mode option to mode selector
<div class="mode-buttons">
    <button class="mode-btn" onclick="startGame('free')">
        <h3>Free Play</h3>
        <p>Practice mode - Traditional rules</p>
    </button>
    <button class="mode-btn" onclick="startGame('free-joker')">
        <h3>Free Play (Joker)</h3>
        <p>Practice mode - With Yahtzee Joker rules</p>
    </button>
    <button class="mode-btn primary" onclick="startGame('true')">
        <h3>True Gameplay</h3>
        <p>Traditional rules with logging</p>
    </button>
    <button class="mode-btn primary" onclick="startGame('true-joker')">
        <h3>True Gameplay (Joker)</h3>
        <p>Joker rules with logging</p>
    </button>
</div>
```

#### Joker State Tracking:
```javascript
// Add to game state
let jokerMode = false;
let yahtzeeStatus = {
    1: 0,  // Player 1: 0=unfilled, 1=scratched, 2=scored
    2: 0   // Player 2
};
let yahtzeeBonuses = {
    1: 0,  // Player 1 bonus count
    2: 0   // Player 2 bonus count
};

// Update score display to show bonuses
function updateTotals(player) {
    // ... existing code ...

    if (jokerMode) {
        const bonusCount = yahtzeeBonuses[player];
        const bonusEl = document.getElementById(`yahtzee-bonus-${player}`);
        if (bonusEl) {
            bonusEl.textContent = bonusCount > 0 ? `+${bonusCount * 100}` : '0';
        }

        // Add bonuses to total
        totalScore += bonusCount * 100;
    }
}

// Handle joker bonus on scoring
function handleJokerScoring(player, categoryId, points, isYahtzeeRoll) {
    if (!jokerMode) return 0;

    let bonus = 0;

    // Update yahtzee status when scoring in yahtzee category
    if (categoryId === 11) {  // Yahtzee category
        yahtzeeStatus[player] = points === 50 ? 2 : 1;
    }

    // Award bonus if applicable
    if (isYahtzeeRoll && yahtzeeStatus[player] === 2 && categoryId !== 11) {
        yahtzeeBonuses[player]++;
        bonus = 100;
        triggerJokerBonusAnimation();  // Fun animation!
    }

    return bonus;
}
```

#### Joker Bonus Animation:
```css
/* Add to styles */
.joker-bonus-animation {
    position: fixed;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    font-size: 4em;
    font-weight: bold;
    color: #ffd700;
    text-shadow: 0 0 20px #ffd700, 0 0 40px #ff6b6b;
    animation: jokerPop 1.5s ease-out forwards;
    z-index: 3000;
}

@keyframes jokerPop {
    0% { transform: translate(-50%, -50%) scale(0); opacity: 0; }
    20% { transform: translate(-50%, -50%) scale(1.3); opacity: 1; }
    100% { transform: translate(-50%, -50%) scale(1); opacity: 0; }
}
```

---

## 5. Cache Strategy

### 5.1 Dual Cache System
```
ysolver/
├── ev_cache_traditional.pkl  # ~136 MB (existing)
├── ev_cache_joker.pkl        # ~400 MB (new, 3x states)
└── cache_metadata.json       # Version info, checksums
```

### 5.2 Lazy Loading
```python
# Only load joker cache when needed
class SolverCache:
    def __init__(self):
        self._traditional = None
        self._joker = None

    @property
    def traditional(self):
        if self._traditional is None:
            self._traditional = load_cache('ev_cache_traditional.pkl')
        return self._traditional

    @property
    def joker(self):
        if self._joker is None:
            self._joker = load_cache('ev_cache_joker.pkl')
        return self._joker
```

### 5.3 Cache Versioning
```json
{
    "traditional": {
        "version": "1.0",
        "generated": "2024-01-15T10:30:00Z",
        "checksum": "abc123..."
    },
    "joker": {
        "version": "1.0",
        "generated": "2024-01-15T12:45:00Z",
        "checksum": "def456..."
    }
}
```

---

## 6. Performance Optimization with Numba

### 6.1 JIT Compilation Strategy
```python
# Use these Numba decorators for performance:

# For pure computation, no Python objects
@njit(cache=True)
def compute_score(...): ...

# For parallel loops over independent states
@njit(parallel=True, cache=True)
def precompute_all_states(...):
    for i in prange(N):  # Parallel range
        ...

# For functions called millions of times
@njit(fastmath=True, cache=True)
def inner_loop_function(...): ...
```

### 6.2 Memory Layout
```python
# Use contiguous arrays for cache efficiency
# C-order (row-major) for iteration over last dimension
ev_cache = np.zeros((MASKS, UPPER, YS), dtype=np.float64, order='C')

# Structure of arrays > Array of structures
# Good:
roll_indices = np.array([...], dtype=np.int32)
probabilities = np.array([...], dtype=np.float64)

# Bad:
transitions = [{'roll': r, 'prob': p} for ...]
```

### 6.3 Avoiding Python Overhead
```python
# Pre-convert all lookups to numpy arrays
IS_YAHTZEE = np.array([is_yahtzee_roll(i) for i in range(252)], dtype=np.bool_)
YAHTZEE_FACE = np.array([get_yahtzee_face(i) for i in range(252)], dtype=np.int8)

# Pass arrays to JIT functions, not Python objects
@njit
def fast_function(is_yahtzee_arr, yahtzee_face_arr, ...):
    # Access arrays directly, no Python calls
    if is_yahtzee_arr[roll_idx]:
        face = yahtzee_face_arr[roll_idx]
```

---

## 7. UI Changes

### 7.1 Mode Indicator
- Show "JOKER MODE" badge when active
- Different color scheme (gold accents for joker)

### 7.2 Yahtzee Bonus Tracker
```
┌─────────────────────────┐
│ Yahtzee Bonuses: +200   │  <- Shows total bonus earned
│ [★][★][ ][ ]            │  <- Visual tracker (max 4?)
└─────────────────────────┘
```

### 7.3 Forced Category Indicator
- When joker forces upper section, highlight it
- Show message: "JOKER RULE: Must score in [Fours]"

### 7.4 Joker Scoring Indicators
- When Yahtzee used as joker for Full House, show "JOKER: 25 pts"
- Different styling to indicate joker exception

---

## 8. Testing Strategy

### 8.1 Unit Tests for Scoring
```python
def test_joker_full_house():
    """Five 3s scored as Full House = 25 (joker rule)."""
    roll = [3, 3, 3, 3, 3]
    assert get_joker_score(roll, FULL_HOUSE) == 25

def test_joker_small_straight():
    """Five 4s scored as Small Straight = 30 (joker rule)."""
    roll = [4, 4, 4, 4, 4]
    assert get_joker_score(roll, SMALL_STRAIGHT) == 30

def test_joker_forcing_rule():
    """Must use upper section if available."""
    roll = [5, 5, 5, 5, 5]  # Five 5s
    mask = 0b0000000000000  # Nothing filled
    forced = get_forced_category_joker(roll, mask)
    assert forced == 4  # Fives category
```

### 8.2 Integration Tests
```python
def test_full_game_with_multiple_yahtzees():
    """Simulate game with 3 Yahtzees, verify bonus calculation."""
    ...

def test_joker_ev_vs_traditional():
    """Joker mode should have higher EV due to bonus potential."""
    ...
```

### 8.3 Regression Tests
- Ensure traditional mode unchanged
- Compare against known optimal plays

---

## 9. Migration & Deployment

### 9.1 Deployment Steps
1. Generate joker cache (offline, 30-60 min)
2. Deploy new code with feature flag
3. Enable joker mode in UI
4. Monitor for errors

### 9.2 Feature Flags
```python
JOKER_MODE_ENABLED = os.getenv('JOKER_MODE', 'true').lower() == 'true'

@app.route('/api/modes')
def get_modes():
    modes = ['traditional', 'free']
    if JOKER_MODE_ENABLED:
        modes.extend(['joker', 'free-joker'])
    return jsonify({'modes': modes})
```

### 9.3 Rollback Plan
- Keep traditional cache as primary
- Joker mode can be disabled via env var
- No database migrations needed

---

## 10. Appendix: Mathematical Details

### 10.1 State Space Complexity
```
Traditional Mode:
- States: 252 × 8192 × 64 = 132,120,576
- Cache size: ~136 MB

Joker Mode:
- States: 252 × 8192 × 64 × 3 = 396,361,728
- Cache size: ~400 MB (estimated)

Increase factor: 3x
```

### 10.2 Yahtzee Probability
```
P(Yahtzee on first roll) = 6 / 7776 = 0.077%
P(Yahtzee in a turn) ≈ 4.6% (with optimal rerolls)
P(2+ Yahtzees in game) ≈ 0.46%
```

### 10.3 Expected Joker Bonus
```
E[Joker Bonus per game] ≈ 0.5 × 100 = 5 points
(Roughly 0.5% of games have a second Yahtzee after scoring first)

Impact on strategy: Marginal, but affects:
- Yahtzee category valuation (don't scratch it early)
- Late-game risk assessment
```

### 10.4 EV Difference: Traditional vs Joker
```
E[Score | Traditional] ≈ 254.6
E[Score | Joker]       ≈ 255.1

Difference: ~0.5 points (from joker bonus potential)
```

---

## Implementation Checklist

- [ ] Create `scoring.py` joker functions
- [ ] Add yahtzee detection utilities
- [ ] Implement `ev_solver.py` joker DP
- [ ] Create `precompute_joker.py` pipeline
- [ ] Generate `ev_cache_joker.pkl`
- [ ] Update `web_app.py` endpoints
- [ ] Add mode selection UI
- [ ] Implement yahtzee bonus tracking
- [ ] Add joker animations
- [ ] Write unit tests
- [ ] Write integration tests
- [ ] Performance testing
- [ ] Documentation update
- [ ] Deploy with feature flag

---

## Quick Start Commands

```bash
# Generate joker cache (run once, takes 30-60 min)
python precompute_joker.py

# Run tests
pytest tests/test_joker.py -v

# Start server with joker mode
JOKER_MODE=true python web_app.py

# Benchmark cache generation
python -m cProfile -s cumtime precompute_joker.py
```

---

*Document version: 1.0*
*Last updated: [Current Date]*
*Author: Claude (AI Assistant)*
