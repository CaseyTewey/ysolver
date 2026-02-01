# Yahtzee Category Selection Mistakes: A Mathematical Analysis

This research uses an optimal Expected Value (EV) solver for Yahtzee Joker Mode to identify common category selection mistakes. All EV numbers represent the total expected final game score when making that choice, computed via exact dynamic programming over all possible future game states.

**Key Finding**: The "obvious" choice based on immediate points is frequently wrong. The solver reveals that optimal play often requires sacrificing 10-20 immediate points to preserve future scoring flexibility.

---

## Table of Contents

1. [Taking 0 in a Category vs Scratching Yahtzee](#1-taking-0-in-a-category-vs-scratching-yahtzee)
2. [Full House vs Three of a Kind Decision](#2-full-house-vs-three-of-a-kind-decision)
3. [Small Straight vs Large Straight Timing](#3-small-straight-vs-large-straight-timing)
4. [When Chance is Actually Optimal](#4-when-chance-is-actually-optimal)
5. [Early Game Category Priorities](#5-early-game-category-priorities)
6. [Most Counterintuitive Optimal Plays](#6-most-counterintuitive-optimal-plays)

---

## 1. Taking 0 in a Category vs Scratching Yahtzee

### The Common Mistake

Many players scratch Yahtzee early when they have a garbage roll, thinking "I'll never roll a Yahtzee anyway." This is often wrong.

### The Mathematics

**Key Insight**: Yahtzee has enormous expected value. Even with only a ~4.6% chance of rolling one, the 50 points (plus potential 100-point joker bonuses) makes the Yahtzee category extremely valuable to preserve.

#### Test Case: Roll [1, 2, 3, 4, 6] - Fresh Game

| Decision | Immediate Points | Total EV |
|----------|-----------------|----------|
| Scratch Yahtzee | 0 | 228.21 |
| Scratch Four of a Kind | 0 | 235.47 |

**Result**: Scratching Yahtzee costs 7.26 EV. Even though you score 0 either way, preserving the Yahtzee slot is worth ~7 points over the course of the game.

#### When Yahtzee CAN Be Scratched

When 3-of-kind and 4-of-kind are already used:

| Roll | Scratch Yahtzee EV | Best Alternative | Difference |
|------|-------------------|------------------|------------|
| [1, 2, 3, 4, 6] | 187.10 | Full House (183.07) | **+4.03 for Yahtzee scratch** |
| [1, 2, 3, 5, 6] | 187.10 | Full House (183.07) | **+4.03 for Yahtzee scratch** |
| [1, 1, 3, 5, 6] | 187.10 | Twos (184.61) | **+2.49 for Yahtzee scratch** |

**Exception Rule**: When the "of-a-kind" categories are gone, scratching Yahtzee becomes optimal because Full House and straights are harder to hit and more valuable to preserve.

### Recommendations

1. **Never scratch Yahtzee early in a fresh game** - it costs 7-10 EV
2. **Consider scratching Yahtzee mid-game** when 3-of-kind/4-of-kind are used
3. **Scratch upper section categories first** if you must take a 0 (Ones, Twos when you have no matching dice)

---

## 2. Full House vs Three of a Kind Decision

### The Common Mistake

Players see a full house like [6, 6, 6, 5, 5] (sum = 28) and think "Three of a Kind gives me 28, Full House only gives 25. Obviously take the 28!"

### The Mathematics

**Full House is a scarce resource.** Only 4.0% of rolls are natural full houses, while 29% contain three-of-a-kind. The solver knows Full House is harder to roll later.

#### Critical Threshold Analysis

| Roll | Sum | FH Points | 3K Points | Better Choice | EV Difference |
|------|-----|-----------|-----------|---------------|---------------|
| [1,1,1,2,2] | 7 | 25 | 7 | Full House | +20.96 |
| [2,2,2,3,3] | 12 | 25 | 12 | Full House | +15.96 |
| [3,3,3,6,6] | 21 | 25 | 21 | Full House | +6.96 |
| [4,4,4,6,6] | 24 | 25 | 24 | Full House | +3.96 |
| **[5,5,5,6,6]** | **27** | 25 | **27** | **Full House** | **+0.96** |
| [6,6,6,5,5] | 28 | 25 | 28 | Three of a Kind | +0.04 |

### The Surprising Result

**[5,5,5,6,6] should take Full House even though Three of a Kind gives 2 more points!**

The crossover point is almost exactly at sum = 28. Below that, take Full House. At or above 28, the decision is nearly neutral with a slight edge to Three of a Kind.

#### State-Dependent Exceptions

When upper section is behind (low upper used, need bonus):

| Roll | State | Better Choice |
|------|-------|---------------|
| [5,5,5,6,6] | Low upper filled | **Full House** (+1.19 EV) |
| [6,6,6,5,5] | Low upper filled | **Full House** (+0.19 EV) |

Even with sum = 28, taking Full House can be correct when you need to preserve Three of a Kind to help with upper bonus via versatility!

### Recommendations

1. **Always take Full House when dice sum < 27**
2. **At sum 27-28, prefer Full House unless upper section is on track**
3. **Only take 3K for 28+ points when other lower categories are limited**

---

## 3. Small Straight vs Large Straight Timing

### The Common Mistake

Rolling [1, 2, 3, 4, 6] and thinking "I should take Small Straight now, I might not get this again."

### The Mathematics

Small Straight appears in 17.3% of rolls. Large Straight appears in only 3.1%. The 10-point difference (40 vs 30) is significant but must be weighed against future probability.

#### When to Take What You Have

| Roll | Optimal Choice | EV |
|------|----------------|-----|
| [1, 2, 3, 4, 4] | Small Straight | 246.42 |
| [1, 2, 3, 4, 6] | Small Straight | 246.42 |
| [3, 4, 5, 6, 6] | Small Straight | 246.42 |
| **[1, 2, 3, 4, 5]** | **Large Straight** | **261.52** |

**Key Finding**: When you have a small straight, take it! The solver never recommends passing on a small straight to try for large.

#### The Large Straight Is Always Optimal When You Have It

| Roll | Large EV | Small EV | Difference |
|------|----------|----------|------------|
| [1, 2, 3, 4, 5] | 261.52 | 246.42 | +15.10 |
| [2, 3, 4, 5, 6] | 261.52 | 246.42 | +15.10 |

The 10-point immediate difference plus the scarcity of large straights makes this a clear choice.

### The Counterintuitive Case

What if [1, 2, 3, 4, 5] comes up when Large Straight is already filled?

| Situation | Best Choice | EV |
|-----------|-------------|-----|
| LS filled | Small Straight | 216.63 |
| SS filled | Ones (1 pt!) | Higher than wasting 5s |

When Small Straight is filled, taking Ones for 1 point can beat taking Fives for 5 points because of upper bonus considerations!

### Recommendations

1. **Always take Large Straight when you have it** - the 10-point premium is real
2. **Take Small Straight immediately** - don't gamble on upgrading to Large
3. **Never "save" a straight for later** - straights don't stack

---

## 4. When Chance is Actually Optimal

### The Common Mistake

Treating Chance as the "garbage" category - only using it when nothing else works. In reality, Chance is often the optimal choice!

### The Mathematics

Chance is optimal in **11.1% of all fresh-game rolls** - making it the 5th most commonly optimal category!

#### Surprising Chance-Optimal Situations

**Roll: [4, 5, 5, 6, 6] (sum = 26)**

| Category | Points | EV |
|----------|--------|-----|
| **Chance** | **26** | **245.84** |
| Ones (scratch) | 0 | 236.77 |
| Fives | 10 | 228.76 |
| Sixes | 12 | 225.83 |

Chance beats scratching Ones by **9.06 EV**! This is not a marginal decision.

**Roll: [6, 6, 5, 5, 4] (sum = 26)**

Same result - Chance is optimal across all tested game states:

| Game State | Chance EV | Best Alternative | Difference |
|------------|-----------|------------------|------------|
| Fresh game | 245.84 | Ones (0): 236.77 | +9.06 |
| Upper almost full | 156.55 | Sixes (12): 153.45 | +3.10 |
| Lower categories filled | 181.39 | Fives (10): 176.17 | +5.23 |

#### When Chance Becomes Dominant

**State: Many lower section categories filled (3K, 4K, FH, Yahtzee)**

| Roll | Best Choice | EV | Alternative |
|------|-------------|-----|-------------|
| [6,6,6,5,5] | **Chance (28)** | 183.39 | Sixes (18): 181.62 |
| [5,5,5,6,6] | **Chance (27)** | 182.39 | Fives (15): 181.17 |

When lower section is limited, Chance becomes your best scoring opportunity.

### Chance Optimal Patterns

Chance tends to be optimal for:
- High-sum rolls with no combos: [4, 5, 5, 6, 6], [5, 5, 6, 6, 4]
- Two-pair rolls that aren't full houses: [3, 3, 5, 5, 6]
- Broken straights with high dice: [3, 4, 5, 6, 6]

### Recommendations

1. **Don't fear using Chance early** with a high roll (24+)
2. **Chance is NOT a garbage category** - it's optimal 11% of the time fresh
3. **When lower section is depleted**, Chance is often your best option

---

## 5. Early Game Category Priorities

### The Common Mistake

"I should fill the hard categories first and save easy ones for later."

### The Mathematics

The solver's priority order based on how often each category is optimal in a fresh game:

| Rank | Category | Optimal Frequency | Avg EV |
|------|----------|------------------|--------|
| 1 | **Ones** | 22.6% | 239.07 |
| 2 | **Twos** | 15.5% | 235.32 |
| 3 | **Threes** | 12.3% | 231.16 |
| 4 | **Full House** | 11.5% | 231.79 |
| 5 | **Chance** | 11.1% | 237.34 |
| 6 | Fours | 6.0% | 227.82 |
| 7 | Fives | 5.6% | 225.36 |
| 8 | Small Straight | 5.6% | 218.32 |
| 9 | Sixes | 4.4% | 223.66 |
| 10 | Three of a Kind | 2.4% | 234.61 |
| 11 | Yahtzee | 2.4% | 230.41 |
| 12 | Large Straight | 0.8% | 221.83 |
| 13 | Four of a Kind | **0.0%** | 237.97 |

### Key Insights

1. **Four of a Kind is NEVER optimal in a fresh game!** The solver always prefers something else.

2. **Upper section categories dominate early**. Ones is optimal 23% of the time!

3. **Full House is high priority** (11.5%) but Three of a Kind is low (2.4%)

4. **Large Straight is rarely optimal** - only 0.8% of rolls. But when you have it, take it!

### First-Roll Examples

| Roll | Optimal Play | Points | EV | Common Mistake |
|------|--------------|--------|-----|----------------|
| [1,1,1,2,3] | Ones | 3 | 245.20 | Taking 3K for 8 |
| [6,6,6,4,2] | Sixes | 18 | 250.41 | Taking 3K for 24 |
| [5,5,5,5,2] | Fives | 20 | 264.38 | Taking 4K for 22 |
| [2,2,3,3,4] | Twos | 4 | 241.63 | Taking Threes for 6 |

### The Upper Bonus Strategy

The solver implicitly prioritizes upper section because:
- Upper bonus (35 points at 63+) is achievable ~60% of games with optimal play
- Each upper category "on pace" (3 average) contributes to bonus probability
- Low upper scores (1, 2 in Ones/Twos) hurt less than missing bonus entirely

### Recommendations

1. **Fill upper section early** when you have good rolls (3+ of a face)
2. **Never take Four of a Kind fresh** - always something better
3. **Full House is high priority** - take it when you get it
4. **Three of a Kind is low priority** - it's flexible, save it

---

## 6. Most Counterintuitive Optimal Plays

These are plays where the solver recommends sacrificing significant immediate points for higher EV:

### Top 5 Most Surprising Plays

#### 1. Roll: [1, 4, 4, 5, 5]
| Choice | Points | EV |
|--------|--------|-----|
| Chance | 19 | 238.84 |
| **Ones** | **1** | **239.50** |

**Sacrifice 18 points now to gain 0.67 EV.** Taking 1 point in Ones beats 19 in Chance!

#### 2. Roll: [1, 2, 5, 5, 6]
| Choice | Points | EV |
|--------|--------|-----|
| Chance | 19 | 238.84 |
| **Ones** | **1** | **239.50** |

Same pattern. The single 1 is more valuable than the full Chance score.

#### 3. Roll: [2, 2, 5, 6, 6]
| Choice | Points | EV |
|--------|--------|-----|
| Chance | 21 | 240.84 |
| **Twos** | **4** | **241.63** |

**Sacrifice 17 points.** Even with a 21 Chance available, taking 4 in Twos is optimal.

#### 4. Roll: [4, 4, 4, 5, 6]
| Choice | Points | EV |
|--------|--------|-----|
| Three of a Kind | 23 | 248.86 |
| **Fours** | **12** | **249.30** |

**Sacrifice 11 points.** Upper section value > lower section flexibility.

#### 5. Roll: [3, 3, 4, 4, 5]
| Choice | Points | EV |
|--------|--------|-----|
| Chance | 19 | 238.84 |
| **Threes** | **6** | **239.84** |

**Sacrifice 13 points.** Lock in upper section progress.

### Why These Are Optimal

The pattern is clear: **Upper section progress is undervalued by most players.**

- The 35-point upper bonus is earned 60% of the time with optimal play
- Each "on-pace" upper category (averaging 3x face value) increases bonus probability
- Lower section categories can often be filled later; upper opportunities are more constrained

### The Mathematical Principle

When you see a garbage roll with one matching die in the upper section, the solver asks:
> "Is the future value of keeping Chance/3K open worth more than the upper section progress?"

Usually, the answer is **no**. Progress toward the 35-point bonus dominates.

---

## Summary: The 10 Commandments of Category Selection

1. **Never scratch Yahtzee in a fresh game** - costs 7+ EV
2. **Take Full House over 3K when sum < 28** - Full House is scarce
3. **Always take Large Straight immediately** - 15 EV over Small
4. **Take Small Straight when you have it** - don't gamble
5. **Chance is optimal 11% of the time** - not a garbage category
6. **Fill upper section early** - bonus probability matters
7. **Four of a Kind is never optimal fresh** - always a better choice
8. **Sacrifice immediate points for upper progress** - 1 in Ones > 19 in Chance
9. **Three of a Kind is low priority** - flexible, save for later
10. **When in doubt, consult the EV** - intuition fails often

---

## Methodology

All analysis performed using:
- **Solver**: Yahtzee Joker Mode EV Solver with dynamic programming
- **State Space**: 2^13 category masks x 64 upper subtotals x 3 Yahtzee statuses
- **Roll Space**: 252 unique 5-dice multisets
- **Accuracy**: Exact computation, no Monte Carlo approximation

Expected Values represent total game score including all future turns under optimal play.

---

*Generated by Yahtzee Category Research Tool using get_all_category_evs_joker()*
