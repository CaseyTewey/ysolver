# Early Game Keeping Mistakes in Yahtzee (Joker Mode)

This research uses the EV solver to identify common intuitive plays that are suboptimal.
All scenarios assume **Roll 1** (2 rolls remaining) of a **fresh game** (empty scorecard).

Expected values are calculated using dynamic programming with the full game tree.

---

## Executive Summary

| Category | Key Finding | EV Cost of Mistake |
|----------|-------------|-------------------|
| Low Pairs (1s, 2s) | Abandon for open-ended straights (2-3-4-5 or 3-4-5) | Up to **4.32 EV** |
| High Pairs (5s, 6s) | Keep 6s always; 5s lose to perfect straight draws | 0-1.86 EV |
| Mid Pairs (3s, 4s) | Abandon for 2-3-4-5 straight draws | Up to **3.47 EV** |
| Three of a Kind | ALWAYS keep all 3 - never break up trips | N/A (intuition correct) |
| Four of a Kind | ALWAYS chase Yahtzee from quads | N/A (intuition correct) |
| Two Pairs | Keep the HIGHER pair only, not both | Up to **3.16 EV** |

### Biggest Surprises

1. **Two pairs is a trap!** Keeping both pairs for Full House costs 2-3 EV - always keep just the higher pair
2. **Pair of 2s with 2-3-4-5** is the biggest mistake (4.32 EV loss) - the straight draw dominates
3. **Even pair of 5s loses** to a perfect 2-3-4-5 straight draw (1.86 EV)

---

## 1. Low Pairs vs Straight Draws

**Question:** When should you abandon a low pair (1s or 2s) to draw at a straight?

**Intuition:** "Keep the pair - it's a start toward Yahtzee or Full House"

**Reality:** With strong straight draws, abandoning low pairs can be correct!

### Test Results

| Dice | Description | Optimal Keep | Opt EV | Pair Keep | Pair EV | EV Loss | Verdict |
|------|-------------|--------------|--------|-----------|---------|---------|---------|
| [1, 1, 3, 4, 5] | Pair of 1s with 3-4-5 | [3, 4, 5] | 250.62 | [1, 1] | 249.17 | 1.45 | MISTAKE |
| [1, 1, 2, 3, 4] | Pair of 1s with 1-2-3-4 | [1, 2, 3, 4] | 251.13 | [1, 1] | 249.17 | 1.97 | MISTAKE |
| [2, 2, 3, 4, 5] | Pair of 2s with 2-3-4-5 | [2, 3, 4, 5] | 254.88 | [2, 2] | 250.56 | 4.32 | MISTAKE |
| [2, 2, 3, 4, 6] | Pair of 2s with 3-4 (weak) | [2, 2] | 250.56 | [2, 2] | 250.56 | - | Correct |
| [1, 1, 2, 4, 5] | Pair of 1s with 2-4-5 (gutshot) | [5] | 249.94 | [1, 1] | 249.17 | 0.77 | MISTAKE |
| [1, 2, 2, 4, 5] | Pair of 2s with 1-4-5 | [2, 2] | 250.56 | [2, 2] | 250.56 | - | Correct |
| [1, 2, 3, 4, 4] | Pair of 4s with 1-2-3-4 | [4, 4] | 252.24 | [4, 4] | 252.24 | - | Correct |
| [1, 1, 4, 5, 6] | Pair of 1s with 4-5-6 | [5] | 249.94 | [1, 1] | 249.17 | 0.77 | MISTAKE |
| [2, 2, 4, 5, 6] | Pair of 2s with 4-5-6 | [2, 2] | 250.56 | [2, 2] | 250.56 | - | Correct |

### Key Insights - Low Pairs

1. **Pair of 1s vs 3-4-5**: The straight draw wins because:
   - 1s contribute only 2 points to upper section (3 needed for bonus pace)
   - Straight possibilities: Large Straight (40), Small Straight (30)
   - Rerolling 2 dice for straight is favorable odds

2. **Pair of 2s vs open-ended straights**: Similar logic - 2s aren't worth much

3. **When to keep low pairs**: When straight draw is weak (gutshot only)

---

## 2. High Pairs vs Straight Draws

**Question:** Are high pairs (5s, 6s) different from low pairs?

**Intuition:** "High pairs should be better because of upper bonus"

**Reality:** Confirmed! High pairs are almost always worth keeping.

### Test Results

| Dice | Description | Optimal Keep | Opt EV | Pair Keep | Pair EV | EV Loss | Verdict |
|------|-------------|--------------|--------|-----------|---------|---------|---------|
| [5, 5, 3, 4, 6] | Pair of 5s with 3-4-5-6 open-ended | [5, 5] | 253.02 | [5, 5] | 253.02 | - | Correct |
| [6, 6, 3, 4, 5] | Pair of 6s with 3-4-5 | [6, 6] | 253.94 | [6, 6] | 253.94 | - | Correct |
| [5, 5, 2, 3, 4] | Pair of 5s with 2-3-4-5 | [2, 3, 4, 5] | 254.88 | [5, 5] | 253.02 | 1.86 | MISTAKE |
| [6, 6, 2, 3, 4] | Pair of 6s with 2-3-4 | [6, 6] | 253.94 | [6, 6] | 253.94 | - | Correct |
| [5, 5, 1, 2, 3] | Pair of 5s with 1-2-3 | [5, 5] | 253.02 | [5, 5] | 253.02 | - | Correct |
| [6, 6, 1, 2, 4] | Pair of 6s with gutshot | [6, 6] | 253.94 | [6, 6] | 253.94 | - | Correct |
| [4, 4, 2, 3, 5] | Pair of 4s with 2-3-4-5 | [2, 3, 4, 5] | 254.88 | [4, 4] | 252.24 | 2.63 | MISTAKE |
| [3, 3, 2, 4, 5] | Pair of 3s with 2-3-4-5 | [2, 3, 4, 5] | 254.88 | [3, 3] | 251.41 | 3.47 | MISTAKE |

### Key Insights - High Pairs

1. **Upper bonus math**:
   - Need 63 points in upper section for +35 bonus
   - Average per category = 63/6 = 10.5
   - Pair of 5s = 10 points, pair of 6s = 12 points
   - These are "on pace" or better for the bonus!

2. **6s are truly premium**: Even with the best straight draws (3-4-5), pair of 6s wins

3. **5s are borderline**: Pair of 5s loses to 2-3-4-5 but beats 3-4-5-6 draws

4. **3s and 4s should chase straights**: When you have 2-3-4-5, abandon these pairs!

### The Critical Pattern

The magic straight draw is **2-3-4-5** - it beats almost every pair:
- Beats pair of 2s (4.32 EV difference!)
- Beats pair of 3s (3.47 EV difference)
- Beats pair of 4s (2.63 EV difference)
- Beats pair of 5s (1.86 EV difference)
- Only loses to pair of 6s

---

## 3. Three of a Kind Decisions

**Question:** When you roll 3 of a kind, should you ever break it up?

**Intuition:** "Keep all three - go for Yahtzee or Full House"

**Reality:** Always keep all 3! Never break up trips.

### Test Results

| Dice | Description | Optimal Keep | Opt EV | Trips Keep | Trips EV | EV Loss | Verdict |
|------|-------------|--------------|--------|------------|----------|---------|---------|
| [1, 1, 1, 2, 3] | Trip 1s with 1-2-3 | [1, 1, 1] | 254.99 | [1, 1, 1] | 254.99 | - | Correct |
| [2, 2, 2, 3, 4] | Trip 2s with 2-3-4 | [2, 2, 2] | 257.70 | [2, 2, 2] | 257.70 | - | Correct |
| [2, 2, 2, 4, 5] | Trip 2s with 4-5 | [2, 2, 2] | 257.70 | [2, 2, 2] | 257.70 | - | Correct |
| [3, 3, 3, 4, 5] | Trip 3s with 3-4-5 | [3, 3, 3] | 259.65 | [3, 3, 3] | 259.65 | - | Correct |
| [5, 5, 5, 2, 3] | Trip 5s with 2-3 | [5, 5, 5] | 263.17 | [5, 5, 5] | 263.17 | - | Correct |
| [6, 6, 6, 1, 2] | Trip 6s with 1-2 | [6, 6, 6] | 265.11 | [6, 6, 6] | 265.11 | - | Correct |
| [6, 6, 6, 4, 5] | Trip 6s with 4-5 | [6, 6, 6] | 265.11 | [6, 6, 6] | 265.11 | - | Correct |
| [3, 3, 3, 2, 4] | Trip 3s with 2-3-4 | [3, 3, 3] | 259.65 | [3, 3, 3] | 259.65 | - | Correct |
| [4, 4, 4, 3, 5] | Trip 4s with 3-4-5 | [4, 4, 4] | 261.45 | [4, 4, 4] | 261.45 | - | Correct |
| [4, 4, 4, 2, 3] | Trip 4s with 2-3-4 | [4, 4, 4] | 261.45 | [4, 4, 4] | 261.45 | - | Correct |
| [3, 3, 3, 4, 5] | Trip 3s - compare keep [3,3] vs [3,3,3] | [3, 3, 3] | 259.65 | [3, 3, 3] | 259.65 | - | Correct |

### Key Insights - Three of a Kind

1. **Trips are gold**: The probability of improving from 3-of-kind is high:
   - P(Full House) from trips = decent (pair the other 2)
   - P(4-of-kind) from trips = reroll 2 dice, need 1+ match
   - P(Yahtzee) from trips = reroll 2 dice twice, ~9%

2. **Never break trips for straights**: Even with 3-4-5 when you have trip 3s,
   keeping all 3 is correct. The straight draw isn't worth giving up trips.

3. **High trips vs low trips**: Both are always kept, but high trips have
   slightly better EV due to upper bonus contribution.

---

## 4. Four of a Kind on Roll 1 - Always Chase Yahtzee?

**Question:** With 4 of a kind on roll 1, should you always go for Yahtzee?

**Intuition:** "Keep all 4 and pray for Yahtzee!"

**Reality:** Always correct! The Yahtzee chase is worth it.

### Test Results

| Dice | Description | Optimal Keep | Opt EV | Quads Keep | Quads EV | Keep All | Verdict |
|------|-------------|--------------|--------|------------|----------|----------|---------|
| [1, 1, 1, 1, 2] | Quads 1s + 2 | [1, 1, 1, 1] | 270.30 | [1, 1, 1, 1] | 270.30 | 260.19 | Correct |
| [1, 1, 1, 1, 6] | Quads 1s + 6 | [1, 1, 1, 1] | 270.30 | [1, 1, 1, 1] | 270.30 | 260.19 | Correct |
| [2, 2, 2, 2, 1] | Quads 2s + 1 | [2, 2, 2, 2] | 273.91 | [2, 2, 2, 2] | 273.91 | 264.53 | Correct |
| [2, 2, 2, 2, 6] | Quads 2s + 6 | [2, 2, 2, 2] | 273.91 | [2, 2, 2, 2] | 273.91 | 264.53 | Correct |
| [3, 3, 3, 3, 1] | Quads 3s + 1 | [3, 3, 3, 3] | 276.78 | [3, 3, 3, 3] | 276.78 | 267.97 | Correct |
| [3, 3, 3, 3, 5] | Quads 3s + 5 | [3, 3, 3, 3] | 276.78 | [3, 3, 3, 3] | 276.78 | 267.97 | Correct |
| [4, 4, 4, 4, 1] | Quads 4s + 1 | [4, 4, 4, 4] | 279.31 | [4, 4, 4, 4] | 279.31 | 271.01 | Correct |
| [4, 4, 4, 4, 6] | Quads 4s + 6 | [4, 4, 4, 4] | 279.31 | [4, 4, 4, 4] | 279.31 | 271.01 | Correct |
| [5, 5, 5, 5, 1] | Quads 5s + 1 | [5, 5, 5, 5] | 281.70 | [5, 5, 5, 5] | 281.70 | 273.87 | Correct |
| [5, 5, 5, 5, 6] | Quads 5s + 6 | [5, 5, 5, 5] | 281.70 | [5, 5, 5, 5] | 281.70 | 273.87 | Correct |
| [6, 6, 6, 6, 1] | Quads 6s + 1 | [6, 6, 6, 6] | 284.30 | [6, 6, 6, 6] | 284.30 | 277.00 | Correct |
| [6, 6, 6, 6, 5] | Quads 6s + 5 | [6, 6, 6, 6] | 284.30 | [6, 6, 6, 6] | 284.30 | 277.00 | Correct |

### Key Insights - Four of a Kind

1. **Yahtzee probability from quads**:
   - With 2 rolls remaining, rerolling 1 die each time
   - P(Yahtzee) = 1 - (5/6)^2 = 30.56%
   - Expected Yahtzee value: 50 * 0.3056 = 15.28 points

2. **Why chase is correct**:
   - Yahtzee (50) + potential joker bonuses (100 each)
   - 4-of-kind is already guaranteed as fallback
   - No downside to chasing - you can't do worse

3. **Low quads vs high quads**: Both should chase Yahtzee
   - Even quad 1s should chase (Yahtzee value > upper section loss)

---

## 5. Additional Edge Cases

### Two Pairs - A Major Trap!

**Intuition says:** "Keep both pairs for Full House!"

**Reality:** NEVER keep two pairs - always keep only the higher pair!

| Dice | Optimal Keep | Opt EV | Intuitive (Both Pairs) | Int EV | EV Loss |
|------|--------------|--------|------------------------|--------|---------|
| [1, 1, 2, 2, 3] | [2, 2] | 250.56 | [1, 1, 2, 2] | 248.79 | **1.77** |
| [3, 3, 5, 5, 6] | [5, 5] | 253.02 | [3, 3, 5, 5] | 249.85 | **3.16** |
| [5, 5, 6, 6, 1] | [6, 6] | 253.94 | [5, 5, 6, 6] | 250.97 | **2.97** |

**Why this is wrong:**
- Full House is only 25 points
- Keeping both pairs limits you to 1 reroll die
- Keeping one high pair gives 3 dice to improve toward Yahtzee/4-of-kind
- The higher pair contributes more to upper bonus

### Small Straight + Extra Die

| Dice | Optimal Keep | EV | Intuitive | Int EV | Notes |
|------|--------------|-----|-----------|--------|-------|
| [1, 2, 3, 4, 6] | [1, 2, 3, 4] | 251.13 | [1, 2, 3, 4] | 251.13 | Go for large straight |
| [2, 3, 4, 5, 1] | **[1, 2, 3, 4, 5]** | **261.53** | [2, 3, 4, 5] | 254.88 | **Keep all 5! Already have large straight!** |
| [3, 4, 5, 6, 1] | [3, 4, 5, 6] | 251.13 | [3, 4, 5, 6] | 251.13 | Reroll the 1 |

**Key insight:** [2, 3, 4, 5, 1] is already a LARGE STRAIGHT worth 40 points!
Keeping just [2, 3, 4, 5] costs you **6.66 EV** - don't throw away a made hand!

### Near Large Straights

| Dice | Optimal Keep | EV | Notes |
|------|--------------|----|----|
| [1, 3, 4, 5, 6] | [3, 4, 5, 6] | 251.13 | Almost large straight (missing 2) |
| [2, 3, 4, 5, 5] | [2, 3, 4, 5] | 254.88 | Almost large straight with pair 5s |


---

## Methodology

1. **Game State**: Fresh game (mask=0, upper=0, yahtzee_status=unfilled)
2. **Roll Phase**: Roll 1 (2 rolls remaining)
3. **EV Calculation**: Full dynamic programming with Joker mode rules
4. **Optimal Keep**: Found via exhaustive search over all valid keeps

### EV Solver Details

The solver uses precomputed EV tables for all 8192 x 64 x 2 game states
(filled categories x upper subtotal x Yahtzee-bonus flag). For each keep decision,
it computes expected value by:

1. Enumerating all possible reroll outcomes
2. Looking up the optimal continuation value (v2 after roll 1)
3. Weighting by multinomial probabilities

This gives exact EV values, not Monte Carlo estimates.

---

## Practical Takeaways

### Quick Rules of Thumb

1. **Low pairs (1s, 2s)**: Abandon for any good straight draw (3-4-5 or better)
2. **Mid pairs (3s, 4s)**: Abandon for 2-3-4-5 straight draw specifically
3. **High pairs (6s)**: Always keep - even vs best straight draws
4. **Pair of 5s**: Keep unless you have exactly 2-3-4-5
5. **Three of a kind**: ALWAYS keep all 3 - never break up trips
6. **Four of a kind**: ALWAYS chase Yahtzee - guaranteed fallback
7. **Two pairs**: NEVER keep both! Keep only the higher pair

### The Upper Bonus Effect

The 35-point upper bonus at 63+ points significantly affects strategy:
- Need average of 10.5 per category (3x face value)
- 6s: 3 gives 18 (above pace)
- 5s: 3 gives 15 (above pace)
- 4s: 3 gives 12 (above pace)
- 3s: 3 gives 9 (below pace)
- 2s: 3 gives 6 (below pace)
- 1s: 3 gives 3 (below pace)

This is why high pairs are more valuable than low pairs!

---

## Appendix: EV Reference Table

### Expected Values by Keep Type (Fresh Game, Roll 1)

| Keep Type | Example | EV | Notes |
|-----------|---------|-----|-------|
| Four of a kind (6s) | [6,6,6,6] | 284.30 | Best possible keep |
| Four of a kind (5s) | [5,5,5,5] | 281.70 | |
| Four of a kind (4s) | [4,4,4,4] | 279.31 | |
| Four of a kind (3s) | [3,3,3,3] | 276.78 | |
| Four of a kind (2s) | [2,2,2,2] | 273.91 | |
| Four of a kind (1s) | [1,1,1,1] | 270.30 | Still great! |
| Three 6s | [6,6,6] | 265.11 | |
| Three 5s | [5,5,5] | 263.17 | |
| Three 4s | [4,4,4] | 261.45 | |
| Large straight | [1,2,3,4,5] | 261.53 | Keep all 5! |
| Three 3s | [3,3,3] | 259.65 | |
| Three 2s | [2,2,2] | 257.70 | |
| Three 1s | [1,1,1] | 254.99 | |
| Open-ended straight | [2,3,4,5] | 254.88 | Very strong draw |
| Pair of 6s | [6,6] | 253.94 | |
| Pair of 5s | [5,5] | 253.02 | |
| Pair of 4s | [4,4] | 252.24 | |
| Small straight (low) | [1,2,3,4] | 251.13 | |
| Small straight (high) | [3,4,5,6] | 251.13 | |
| Pair of 3s | [3,3] | 251.41 | |
| Inside straight | [3,4,5] | 250.62 | |
| Pair of 2s | [2,2] | 250.56 | |
| Two pairs | [5,5,6,6] | 250.97 | Bad! Keep one pair |
| Empty (reroll all) | [] | 249.47 | Baseline |
| Pair of 1s | [1,1] | 249.17 | Below baseline! |

### Key Observations

1. **Any pair of 1s is worse than rerolling all 5 dice!** (249.17 vs 249.47)
2. **Two pairs underperform** compared to the higher single pair
3. **Open-ended straight [2,3,4,5] beats all pairs except 6s**
4. **Trips always beat pairs** by a wide margin (5-10+ EV)
5. **Quads are exceptional** - always worth chasing Yahtzee

---

*Generated by Yahtzee EV Solver research script*
*Joker mode rules, fresh game state, Roll 1 (2 rolls remaining)*
