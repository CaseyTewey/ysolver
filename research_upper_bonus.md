# Upper Section Bonus Strategy Analysis

## Research Summary

This document presents a rigorous analysis of upper section bonus strategy in Yahtzee using the EV solver with joker rules (official Hasbro rules). All calculations are based on optimal play computed via dynamic programming.

---

## 1. How Much Is the 35-Point Bonus Really Worth?

### The Nominal vs. Expected Value

The upper section bonus awards **35 points** when you score 63 or more in the upper section (Ones through Sixes). However, the *expected value* of the bonus depends on your probability of achieving it.

| Metric | Value |
|--------|-------|
| Nominal bonus | 35 points |
| Fresh game EV | 254.59 points |
| P(bonus) from fresh game | **68.1%** |
| Expected bonus contribution | **23.84 points** |
| Percentage of total EV | **9.4%** |

**Key Finding:** The 35-point bonus contributes an expected 23.84 points to your game, representing about 9.4% of your total expected score. This makes it a significant but not dominant factor in strategy.

### How This Was Calculated

The bonus probability is computed by following the optimal policy forward from the fresh game and recording how often the upper section reaches 63 (an exact policy evaluation, not a simulation).

A shortcut that only compares expected values understates it:
- Fresh game EV (upper=0): **254.59**
- Fresh game EV (upper=63, bonus guaranteed): **272.82**
- Difference: **18.24**

The formula `P(bonus) = 1 - (difference / 35) = 1 - 0.521 = 47.9%` would be right only if both players scored the same in the boxes; the player who still needs the bonus gives up about 7 points of box scoring to chase it, so the true probability is higher.

This means that under optimal play, you achieve the bonus about two thirds of the time.

---

## 2. When to "Reach" for the Bonus vs. Give Up

### The Decision Framework

The key insight is that the **marginal value of upper section points decreases sharply** as you approach the threshold. With 6 upper categories remaining (lower section already filled):

| Upper Total | P(bonus) | Marginal Value (per point) |
|-------------|------------------|---------------------------|
| 0 | 36.9% | ~1.56 |
| 10 | 79.5% | ~1.10 |
| 20 | 97.6% | ~0.21 |
| 30 | 99.9% | ~0.01 |
| 40+ | 100.0% | ~0.00 |

**Interpretation:**
- At low upper totals, each point is extremely valuable (1.56 EV per point when upper=0)
- By upper=30, you're virtually guaranteed the bonus if playing optimally
- Points beyond 30-40 add essentially zero bonus value

### Practical "Give Up" Thresholds

When should you stop reaching for the bonus? The answer depends on which categories remain:

| Remaining Categories | Max Possible | Minimum Upper Needed | Give Up If Below |
|---------------------|--------------|---------------------|------------------|
| Only Sixes | 30 | 33 | 33 |
| Only Fives | 25 | 38 | 38 |
| Only Fours | 20 | 43 | 43 |
| Fives + Sixes | 55 | 8 | 8 |
| Fours + Fives + Sixes | 75 | 0 | Never |
| Ones + Twos + Threes | 30 | 33 | 33 |

**Example Decision:** With only Sixes remaining and upper=25, the bonus is **impossible** (max is 25+30=55 < 63). At this point, stop "reaching" and maximize other scoring.

---

## 3. Common Mistake: Always Maximizing Upper Section Scores

### Mistake #1: Taking Lower Section Points When Upper Is Better

**Scenario:** Early game, you roll three 4s (dice: 4-4-4-2-5, sum=19)

| Option | Points | Upper Contribution | Future EV | Total EV |
|--------|--------|-------------------|-----------|----------|
| Score in Fours | 12 | +12 | 237.41 | **249.41** |
| Score in Three-of-a-Kind | 19 | 0 | 225.96 | 244.96 |

**Result: Fours is better by 4.46 points** despite scoring 7 fewer immediate points.

### Mistake #2: Reaching When It's Too Late

**Scenario:** Four upper categories filled with only 18 points. You have Fives and Sixes left, needing 45 more (very hard!). You roll 5-5-5-3-3.

| Option | Points | Strategy | Future EV | Total EV |
|--------|--------|----------|-----------|----------|
| Score 15 in Fives (reach) | 15 | Keep trying for bonus | 162.93 | 177.93 |
| Score 25 in Full House | 25 | Give up on bonus | 159.27 | **184.27** |

**Result: Full House is better by 6.34 points.** When the bonus is nearly impossible, take the sure points.

### Mistake #3: Scratching Upper Categories Too Easily

**Scenario:** Early game, you roll only two 3s (dice: 3-3-2-5-6). Should you take 6 in Threes or scratch?

| Option | Points | Total EV |
|--------|--------|----------|
| Take 6 in Threes (below par) | 6 | **239.95** |
| Scratch Threes | 0 | 225.21 |

**Result: Taking the 6 is better by 14.74 points!** Even below-par upper section scores have significant value toward the bonus.

### Mistake #4: Using Low Rolls in Lower Section

**Scenario:** You have three 2s (dice: 2-2-2-3-5, sum=14).

| Option | Points | Upper Progress | Total EV |
|--------|--------|---------------|----------|
| Score 6 in Twos | 6 | +6 | **247.60** |
| Score 14 in Three-of-a-Kind | 14 | 0 | 239.96 |

**Result: Twos is better by 7.64 points.** Upper section progress (especially early) outweighs immediate point differences.

---

## 4. The 63-Point Threshold: Optimal Progress Tracking

### Par Scores

To be "on track" for the bonus, aim for these scores per category:

| Category | Par Score | Dice Needed |
|----------|-----------|-------------|
| Ones | 3 | Three 1s |
| Twos | 6 | Three 2s |
| Threes | 9 | Three 3s |
| Fours | 12 | Three 4s |
| Fives | 15 | Three 5s |
| Sixes | 18 | Three 6s |
| **Total** | **63** | **Bonus threshold** |

### Tracking by Categories Filled

Use this table to track if you're on pace:

| Upper Categories Filled | Par Total | Can Still Get (Max) | Action if Behind |
|------------------------|-----------|---------------------|------------------|
| 1 | 10.5 | 100 | Keep playing normally |
| 2 | 21 | 90 | Keep playing normally |
| 3 | 31.5 | 75 | Slight adjustment |
| 4 | 42 | 55 | Prioritize upper section |
| 5 | 52.5 | 30 | Critical - evaluate give-up |
| 6 | 63 | 0 | Threshold reached or missed |

### Order Matters!

The *which* categories you've filled matters as much as your total:

**Same upper total (18), different impact:**

| Categories Filled | Upper Total | Future EV |
|-------------------|-------------|-----------|
| Sixes only (18 points) | 18 | **232.53** |
| Fours + Twos (12+6) | 18 | 224.93 |
| Ones + Twos + Threes (3+6+9) | 18 | 215.94 |

**Insight:** Having filled fewer, high-value categories is better because:
1. More categories remain = more flexibility
2. Remaining high-value categories (Fours, Fives, Sixes) have larger scoring potential

---

## 5. Which Upper Categories Are Most Valuable to Fill vs. Sacrifice?

### Value of Each Category (Fresh Game)

| Category | Score 0 (EV) | Score Par (EV) | Score Max (EV) | Value of Par |
|----------|--------------|----------------|----------------|--------------|
| Ones | 236.90 | 245.32 | 250.89 | +8.43 |
| Twos | 230.92 | 247.60 | 258.44 | +16.68 |
| Threes | 225.21 | 248.72 | 264.44 | +23.51 |
| Fours | 221.26 | 249.41 | 269.82 | +28.16 |
| Fives | 218.54 | 249.98 | 274.73 | +31.44 |
| Sixes | 216.52 | 250.53 | 279.47 | +34.01 |

**Key Finding:** Higher-value categories contribute more total EV because:
1. They score more points directly
2. They contribute more toward the 63 threshold
3. Each point in Sixes (value 6) is worth more than each point in Ones (value 1)

### Cost of Zeroing Each Category

If you must scratch one upper category, which costs the least?

| Category Sacrificed | Upper Shortfall | Total Cost |
|--------------------|-----------------|------------|
| Ones (3 points) | 60 instead of 63 | **38 points** |
| Twos (6 points) | 57 instead of 63 | 41 points |
| Threes (9 points) | 54 instead of 63 | 44 points |
| Fours (12 points) | 51 instead of 63 | 47 points |
| Fives (15 points) | 48 instead of 63 | 50 points |
| Sixes (18 points) | 45 instead of 63 | 53 points |

**Optimal Sacrifice Order:** If you must zero a category, Ones costs the least (38 points), while Sixes costs the most (53 points).

**Note:** These costs assume all other categories are at par. The cost includes both lost points AND the lost bonus.

---

## Summary: Key Strategic Principles

1. **The bonus is worth ~23.8 EV points** in a fresh game, not the full 35.

2. **Don't scratch upper categories lightly.** Even 2-3 points in an upper category is often worth more than alternative plays.

3. **Give up on the bonus when math dictates.** Use the threshold table - if your remaining categories can't reach 63, pivot to maximizing other points.

4. **Early upper section points are most valuable.** The marginal value of upper progress is highest at the start (1.56 per point) and diminishes rapidly.

5. **Order matters.** Fill low-value categories (Ones, Twos) early when possible, saving high-value categories for better rolls.

6. **Track your progress.** Being 30+ points in with all six upper boxes still open means you're virtually guaranteed the bonus under optimal play (99.9%); after three upper boxes the odds depend heavily on which boxes remain.

7. **If sacrificing, sacrifice Ones.** The cost hierarchy is Ones < Twos < Threes < Fours < Fives < Sixes.

---

## Appendix: EV Lookup Reference

### Fresh Game Baselines

```
Fresh game EV (official Hasbro rules): 254.59
P(bonus) under optimal play: 68.1%
Expected bonus contribution: 23.84 points
```

### Upper Section Progress (All Lower Filled)

| Starting Upper | EV | P(bonus) |
|----------------|-----|------------------|
| 0 | 71.95 | 36.9% |
| 10 | 86.82 | 79.5% |
| 20 | 93.23 | 97.6% |
| 30 | 94.12 | 99.9% |
| 40+ | 94.16 | 100.0% |

### Category Fill Order Impact

With same upper total but different categories filled, more remaining categories = higher EV due to flexibility.

---

*Analysis generated using Yahtzee EV Solver with joker rules. All values computed via dynamic programming with exact probabilities.*
