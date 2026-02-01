# Yahtzee Win-Probability Solver Implementation Plan

## Overview

A **Yahtzee win-probability solver** that takes a **current game state** and returns:
- **Win % / tie % / lose %**
- **Optimal play recommendations** (what to keep on roll 1/2, and which category to score)
- "**Outs**"-style breakdowns (what specific dice outcomes / category hits keep you alive, probability of reaching a target, etc.)

Assumes **2-player Yahtzee** (each has their own scorecard; winner = higher total after all 13 turns).

---

## 0) Rules & Scope

**Rules (default):**
- Standard Yahtzee categories (13), 5 dice, up to 3 rolls/turn, choose one category/turn
- Upper bonus: +35 if upper subtotal ≥ 63
- No Joker rules (simple mode - Yahtzee only scores in Yahtzee box)

**Two solver modes:**
1. **Score-optimal**: each player maximizes **expected final score** (implemented first)
2. **Win-optimal**: each player maximizes **probability of winning** (game-theoretic, harder)

---

## 1) Representations and Core Data Structures

### 1.1 Categories Indexing
```
0-5:   Upper (Ones through Sixes)
6-12:  Lower (3K, 4K, Full House, Small Straight, Large Straight, Yahtzee, Chance)
```

### 1.2 Dice State Representation
- Multisets as counts: `(c1..c6)` where sum=5
- 252 unique multisets: C(10,5) = 252
- Mappings: `roll_id(counts) -> int` and `id_to_roll(int) -> counts`

### 1.3 Scorecard State
- `mask: int` (13-bit) — bit=1 means category filled
- `upper: int` — clamped to min(63, actual) for bonus tracking

### 1.4 Two-Player State
- Player A: `(maskA, upperA, scoreA_so_far)`
- Player B: `(maskB, upperB, scoreB_so_far)`

---

## 2) Precomputation Strategy

### 2.1 Transition Probabilities
- For each r ∈ {0..5}: enumerate reroll outcomes with multinomial probabilities
- For each roll state: enumerate keep options and transition distributions

### 2.2 Scoring Table
- `score_table[252][13]` — precomputed for all roll/category combinations

### 2.3 Legal Actions
- `legal_cats[mask]` — unfilled categories for any mask

---

## 3) Single-Player EV Engine

### 3.1 State Space
- `mask`: 2^13 = 8192
- `upper`: 0..63 (64 values)
- Total: ~524k states (feasible with memoization)

### 3.2 Turn Evaluation (Roll-Stage DP)
```
V3(s, mask, upper) = max over legal cats of [pts + EV_remaining(next_state)]
V2(s, mask, upper) = max over keeps of E[V3(next_roll)]
V1(s, mask, upper) = max over keeps of E[V2(next_roll)]
TurnEV(mask, upper) = E[V1(initial_roll)]
```

### 3.3 Upper Bonus Handling
- Clamp upper to 63
- Add +35 at terminal state if upper >= 63

---

## 4) Distributions (PMF) for Win%

### 4.1 PMF Under Optimal Policy
- `PMF(mask, upper) -> dict{score_delta: probability}`
- Prune with epsilon threshold and top-k entries

### 4.2 Turn PMF Construction
- Enumerate all roll sequences under policy
- Aggregate `(pts, next_mask, next_upper) -> probability`

### 4.3 "Outs" Extraction
- P(≥X points this turn)
- P(reaching target final score)
- Which dice/categories are pivotal

---

## 5) Win Probability Engine

### 5.1 Baseline (Score-Optimal → Win%)
1. Compute remaining PMF for each player
2. Shift by current scores
3. Compute P(A > B), P(A = B), P(A < B)

### 5.2 Win-Aware Decisions (Future Enhancement)
- Maximize win probability instead of EV
- Context-aware "comeback" plays

---

## 6) API Design

### Input
```json
{
  "dice": [1,1,3,5,6],
  "rolls_remaining": 2,
  "current_player": {"score": 87, "mask": 259, "upper": 15},
  "opponent": {"score": 92, "mask": 456, "upper": 22}
}
```

### Output
```json
{
  "win_prob": 0.63,
  "tie_prob": 0.02,
  "lose_prob": 0.35,
  "recommended_action": {
    "stage": "roll1",
    "keep": [1,1],
    "expected_value": 245.3
  },
  "outs": {
    "prob_reach_target": 0.41,
    "turn_thresholds": [...]
  }
}
```

---

## 7) Module Structure

| Module | Purpose |
|--------|---------|
| `dice.py` | Multiset enumeration, multinomial probabilities |
| `scoring.py` | Score functions, precomputed table |
| `transitions.py` | Keep enumeration, reroll distributions |
| `ev_solver.py` | EV DP, policy extraction |
| `pmf_solver.py` | PMF DP with pruning |
| `match.py` | Win% computation, match reports |
| `cli.py` | Command-line interface |
| `tests.py` | Unit tests |

---

## 8) Implementation Phases

### Phase 1 — Core Engine (Single-Player EV)
- [x] Dice multiset enumeration (252 states)
- [x] Scoring functions for 13 categories
- [x] Precompute score_table[252][13]
- [x] Reroll outcome lists for r=0..5
- [x] Keep options and next_roll_dist
- [x] EV_remaining(mask, upper) with memoization
- [ ] Validate EV sanity (~254 expected for fresh game)

### Phase 2 — Policy Extraction + Advisor
- [x] Store argmax decisions for keeps/categories
- [x] "Given dice, what do I do?" endpoint

### Phase 3 — Distributions + Outs
- [x] PMF(mask, upper) under fixed policy with pruning
- [x] Outs: probability thresholds, category hit probs

### Phase 4 — Win% (Baseline)
- [x] Compute each player's remaining PMF
- [x] Win/tie/lose calculation with efficient CDF

### Phase 5 — Win-Aware Decisions
- [ ] Evaluate alternate keeps/categories by win%
- [ ] Report EV-optimal vs win%-optimal when they differ

### Phase 6 — Performance and UX
- [x] Cache everything (in-memory with lru_cache)
- [x] CLI with multiple commands
- [ ] Performance profiling

---

## 9) Testing Strategy

### Unit Tests
- Scoring correctness for known dice
- Reroll probability sums to 1.0
- Roll distribution sums to 1.0

### Property Tests
- Symmetry (permuting faces)
- EV monotonicity sanity

### Golden Tests
- Hardcode mid-game situations
- Snapshot keep/category/EV outputs

---

## 10) Function Signatures

```python
# dice.py
Counts = tuple[int, int, int, int, int, int]
def enumerate_rolls() -> list[Counts]
def roll_id(counts: Counts) -> int
def id_to_roll(i: int) -> Counts
def multinomial_prob(x: Counts) -> float

# scoring.py
def score(cat: int, counts: Counts) -> int
def precompute_score_table() -> list[list[int]]

# transitions.py
def enumerate_keeps(counts: Counts) -> list[Counts]
def get_reroll_outcomes(num_dice: int) -> list[tuple[Counts, float]]
def get_transition_dist(roll_idx: int, keep: Counts) -> list[tuple[int, float]]

# ev_solver.py
def ev_remaining(mask: int, upper: int) -> float
def best_keep_roll1(roll_idx: int, mask: int, upper: int) -> Counts
def best_keep_roll2(roll_idx: int, mask: int, upper: int) -> Counts
def best_category(roll_idx: int, mask: int, upper: int) -> tuple[int, float]

# pmf_solver.py
PMF = dict[int, float]
def pmf_remaining(mask: int, upper: int) -> PMF

# match.py
def win_probs(scoreA: int, maskA: int, upperA: int,
              scoreB: int, maskB: int, upperB: int) -> dict[str, float]
```

---

## Current Status

**Completed:**
- All core modules implemented (dice, scoring, transitions, ev_solver, pmf_solver, match, cli)
- Unit test suite created
- Sample state JSON for testing

**In Progress:**
- Cache warm-up validation
- Full test suite execution

**Remaining:**
- Win-aware decision mode (Phase 5)
- Performance optimization
- Extensive validation against known Yahtzee EV values
