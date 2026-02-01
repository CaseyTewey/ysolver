# Joker Mode PMF Solver Implementation Plan

## Overview

This document describes the implementation of a proper PMF (Probability Mass Function) solver for Yahtzee Joker Mode. The joker PMF solver will compute **exact win probabilities** by modeling the full distribution of remaining scores under optimal joker-mode play.

## Why This Is Needed

The current "exact" win probability calculation uses the traditional PMF solver (`pmf_solver.py`), which:
- Only tracks state as `(mask, upper)`
- Does NOT model yahtzee_status transitions
- Does NOT account for joker bonus potential (+100 per additional Yahtzee)
- Does NOT use joker scoring rules (FH=25, SS=30, LS=40 for jokers)

This leads to incorrect win probabilities when `yahtzee_status == SCORED` because future joker bonuses are not modeled.

## Key Differences: Traditional vs Joker PMF

| Aspect | Traditional PMF | Joker PMF |
|--------|-----------------|-----------|
| Cache Key | `(mask, upper)` | `(mask, upper, yahtzee_status)` |
| State Space | 8192 × 64 = 524,288 | 8192 × 64 × 3 = 1,572,864 |
| Score Table | Standard only | Standard + Joker score table |
| Yahtzee Tracking | None | UNFILLED/SCRATCHED/SCORED |
| Joker Bonus | None | +100 per additional Yahtzee |
| Forced Categories | None | Upper section forcing rule |
| Optimal Policy | `best_category()` | `best_category_joker()` |

## State Space Details

### Yahtzee Status Values
- `YAHTZEE_UNFILLED (0)`: Yahtzee category not yet scored
- `YAHTZEE_SCRATCHED (1)`: Yahtzee scored as 0 (scratched)
- `YAHTZEE_SCORED (2)`: Yahtzee scored as 50 (eligible for +100 bonuses)

### State Transitions

When scoring in the Yahtzee category:
- If score = 50 → `yahtzee_status` becomes `SCORED`
- If score = 0 → `yahtzee_status` becomes `SCRATCHED`

When `yahtzee_status == SCORED` and rolling a Yahtzee:
- Add +100 joker bonus to score
- Forced to score in corresponding upper section if available

## Implementation Steps

### Step 1: Create pmf_solver_joker.py Structure ✓

Create the file with:
- Import statements (matching pmf_solver.py + joker imports)
- Joker-specific cache: `_PMF_JOKER_CACHE: Dict[Tuple[int, int, int], PMF] = {}`
- Helper functions: `prune_pmf`, `shift_pmf`, `convolve_pmf`, `mix_pmfs` (reuse from pmf_solver)

### Step 2: Implement compute_turn_pmf_joker()

This is the core function. It computes the distribution of turn outcomes.

**Key Differences from Traditional:**
1. Takes additional `yahtzee_status` parameter
2. Returns `Dict[(points, next_mask, next_upper, next_yahtzee_status), probability]`
3. Uses joker EV tables to get optimal keep decisions
4. Uses joker scoring rules when `yahtzee_status == SCORED` and rolling Yahtzee
5. Tracks joker bonus (+100) separately
6. Handles yahtzee_status transitions when scoring in Yahtzee category

**Algorithm:**
```
For each roll1 in initial_roll_dist:
    Get optimal keep1 from joker v2 values
    For each roll2 in transition_dist(roll1, keep1):
        Get optimal keep2 from joker v3 values
        For each roll3 in transition_dist(roll2, keep2):
            Use best_category_joker to get optimal category
            Compute: points, new_mask, new_upper, new_yahtzee_status
            Accumulate (outcome -> probability)
```

### Step 3: Implement pmf_remaining_joker()

Recursive function that computes full remaining score distribution.

**Key Differences:**
1. Cache key is `(mask, upper, yahtzee_status)`
2. Base case includes upper bonus (35 if upper >= 63)
3. Turn PMF tracks yahtzee_status transitions
4. Convolves turn outcomes with future PMFs from correct next states

**Algorithm:**
```
def pmf_remaining_joker(mask, upper, yahtzee_status):
    if mask == FULL_MASK:
        return {upper_bonus: 1.0}

    turn_pmf = compute_turn_pmf_joker(mask, upper, yahtzee_status)

    final_pmf = {}
    for (pts, next_mask, next_upper, next_ys), prob in turn_pmf:
        future = pmf_remaining_joker(next_mask, next_upper, next_ys)
        shifted = shift_pmf(future, pts)
        mix into final_pmf

    return prune_pmf(final_pmf)
```

### Step 4: Implement Progress Tracking

Add visual progress meter for cache warming:
```
def warm_pmf_cache_joker(max_unfilled=5, verbose=True):
    total_states = count_states_to_compute(max_unfilled)
    for i, (mask, upper, ys) in enumerate(states_to_compute):
        pmf_remaining_joker(mask, upper, ys)
        if verbose and i % 1000 == 0:
            print_progress_bar(i, total_states)
```

### Step 5: Implement Win Probability Functions

```python
def compute_win_probability_joker_exact(
    p1_locked: int, p1_mask: int, p1_upper: int, p1_yahtzee_status: int,
    p2_locked: int, p2_mask: int, p2_upper: int, p2_yahtzee_status: int
) -> float:
    # Get PMFs for both players
    pmf1 = pmf_remaining_joker(p1_mask, p1_upper, p1_yahtzee_status)
    pmf2 = pmf_remaining_joker(p2_mask, p2_upper, p2_yahtzee_status)

    # Shift by locked scores
    pmf1 = shift_pmf(pmf1, p1_locked)
    pmf2 = shift_pmf(pmf2, p2_locked)

    # P(p1 wins) = sum over s1,s2 where s1>s2 of pmf1[s1] * pmf2[s2]
    # P(tie) = sum over s where both have mass
```

### Step 6: Update match.py

Add joker mode support:
```python
def compute_win_probability_joker(p1_state, p2_state, exact=False):
    if exact:
        return compute_win_probability_joker_exact(...)
    else:
        return compute_win_probability_joker_approximate(...)
```

### Step 7: Update web_app.py

Modify `/api/win_probability_exact` endpoint to use joker PMF when in joker mode.

### Step 8: Add Comprehensive Tests

Test cases:
1. Fresh game PMF mean matches EV from joker solver (254.49)
2. PMF sums to 1.0 (probability axiom)
3. Yahtzee status transitions work correctly
4. Joker bonuses are included in PMF
5. Win probability is 0.5 for identical symmetric states
6. Win probability monotonicity (more points = higher win prob)

## Validation Criteria

The implementation is correct if:

1. **Mean Matches EV:** `pmf_stats(pmf_remaining_joker(0, 0, 0))['mean'] ≈ 254.49`
2. **PMF Sums to 1:** `sum(pmf.values()) ≈ 1.0` for all states
3. **No Negative Probabilities:** All `pmf[score] >= 0`
4. **Yahtzee Status Consistency:** States with `yahtzee_status=SCORED` have higher EVs than `SCRATCHED`
5. **Win Prob Range:** `0.0 <= win_prob <= 1.0`
6. **Symmetric States:** Two players with identical states have `win_prob ≈ 0.5`

## File Structure

```
ysolver/
├── pmf_solver.py           # Traditional PMF (unchanged)
├── pmf_solver_joker.py     # NEW: Joker mode PMF
├── match.py                # UPDATE: Add joker exact mode
├── web_app.py              # UPDATE: Use joker PMF
└── tests.py                # UPDATE: Add joker PMF tests
```

## Performance Considerations

1. **State Space:** 3x larger than traditional (1.5M vs 500K states)
2. **Cache Size:** ~50-100MB for full cache
3. **Computation Time:** Expect 2-5 minutes for full cache warm
4. **Late-Game Focus:** Only need states with ≤5 unfilled categories for practical use

## Progress Tracking Requirements

1. Show total states to compute at start
2. Update progress bar every 0.5 seconds
3. Show estimated time remaining
4. Print completion summary with stats
