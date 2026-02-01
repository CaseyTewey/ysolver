# Upper Section Bonus Strategy Analysis

## Research Summary

This document presents a rigorous analysis of upper section bonus strategy in Yahtzee using the EV solver with joker rules. All calculations are based on optimal play computed via dynamic programming.

---

## 1. How Much Is the 35-Point Bonus Really Worth?

### The Nominal vs. Expected Value

The upper section bonus awards **35 points** when you score 63 or more in the upper section (Ones through Sixes). However, the *expected value* of the bonus depends on your probability of achieving it.

| Metric | Value |
|--------|-------|
| Nominal bonus | 35 points |
| Fresh game EV | 254.49 points |
| P(bonus) from fresh game | **47.7%** |
| Expected bonus contribution | **16.70 points** |
| Percentage of total EV | **6.6%** |

**Key Finding:** The 35-point bonus contributes an expected 16.70 points to your game, representing about 6.6% of your total expected score. This makes it a significant but not dominant factor in strategy.

### How This Was Calculated

The bonus probability is derived by comparing:
- Fresh game EV (upper=0): **254.49**
- Fresh game EV (upper=63, bonus guaranteed): **272.79**
- Difference: **18.30**

Using the formula: `P(bonus) = 1 - (difference / 35) = 1 - 0.523 = 47.7%`

This means that under optimal play, you achieve the bonus slightly less than half the time.

---

## 2. When to "Reach" for the Bonus vs. Give Up

### The Decision Framework

The key insight is that the **marginal value of upper section points decreases sharply** as you approach the threshold. With 6 upper categories remaining:

| Upper Total | Implied P(bonus) | Marginal Value (per point) |
|-------------|------------------|---------------------------|
| 0 | 36.5% | ~1.56 |
| 10 | 79.0% | ~1.20 |
| 20 | 97.3% | ~0.26 |
| 30 | 99.9% | ~0.02 |
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
| Score in Fours | 12 | +12 | 237.30 | **249.30** |
| Score in Three-of-a-Kind | 19 | 0 | 225.86 | 244.86 |

**Result: Fours is better by 4.44 points** despite scoring 7 fewer immediate points.

### Mistake #2: Reaching When It's Too Late

**Scenario:** Four upper categories filled with only 18 points. You have Fives and Sixes left, needing 45 more (very hard!). You roll 5-5-5-3-3.

| Option | Points | Strategy | Future EV | Total EV |
|--------|--------|----------|-----------|----------|
| Score 15 in Fives (reach) | 15 | Keep trying for bonus | 162.71 | 177.71 |
| Score 25 in Full House | 25 | Give up on bonus | 159.14 | **184.14** |

**Result: Full House is better by 6.43 points.** When the bonus is nearly impossible, take the sure points.

### Mistake #3: Scratching Upper Categories Too Easily

**Scenario:** Early game, you roll only two 3s (dice: 3-3-2-5-6). Should you take 6 in Threes or scratch?

| Option | Points | Total EV |
|--------|--------|----------|
| Take 6 in Threes (below par) | 6 | **239.84** |
| Scratch Threes | 0 | 225.14 |

**Result: Taking the 6 is better by 14.70 points!** Even below-par upper section scores have significant value toward the bonus.

### Mistake #4: Using Low Rolls in Lower Section

**Scenario:** You have three 2s (dice: 2-2-2-4-4, sum=14).

| Option | Points | Upper Progress | Total EV |
|--------|--------|---------------|----------|
| Score 6 in Twos | 6 | +6 | **247.48** |
| Score 14 in Three-of-a-Kind | 14 | 0 | 239.86 |

**Result: Twos is better by 7.62 points.** Upper section progress (especially early) outweighs immediate point differences.

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
| Sixes only (18 points) | 18 | **232.41** |
| Fours + Twos (12+6) | 18 | 224.78 |
| Ones + Twos + Threes (3+6+9) | 18 | 215.74 |

**Insight:** Having filled fewer, high-value categories is better because:
1. More categories remain = more flexibility
2. Remaining high-value categories (Fours, Fives, Sixes) have larger scoring potential

---

## 5. Which Upper Categories Are Most Valuable to Fill vs. Sacrifice?

### Value of Each Category (Fresh Game)

| Category | Score 0 (EV) | Score Par (EV) | Score Max (EV) | Value of Par |
|----------|--------------|----------------|----------------|--------------|
| Ones | 236.77 | 245.20 | 250.76 | +8.42 |
| Twos | 230.82 | 247.48 | 258.32 | +16.65 |
| Threes | 225.14 | 248.60 | 264.34 | +23.47 |
| Fours | 221.20 | 249.30 | 269.73 | +28.10 |
| Fives | 218.49 | 249.87 | 274.65 | +31.38 |
| Sixes | 216.47 | 250.41 | 279.40 | +33.94 |

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

1. **The bonus is worth ~16.7 EV points** in a fresh game, not the full 35.

2. **Don't scratch upper categories lightly.** Even 2-3 points in an upper category is often worth more than alternative plays.

3. **Give up on the bonus when math dictates.** Use the threshold table - if your remaining categories can't reach 63, pivot to maximizing other points.

4. **Early upper section points are most valuable.** The marginal value of upper progress is highest at the start (1.56 per point) and diminishes rapidly.

5. **Order matters.** Fill low-value categories (Ones, Twos) early when possible, saving high-value categories for better rolls.

6. **Track your progress.** Being at 31+ points after 3 categories means you're virtually guaranteed the bonus under optimal play.

7. **If sacrificing, sacrifice Ones.** The cost hierarchy is Ones < Twos < Threes < Fours < Fives < Sixes.

---

## Appendix: EV Lookup Reference

### Fresh Game Baselines

```
Fresh game EV (joker mode): 254.49
P(bonus) under optimal play: 47.7%
Expected bonus contribution: 16.70 points
```

### Upper Section Progress (All Lower Filled)

| Starting Upper | EV | Implied P(bonus) |
|----------------|-----|------------------|
| 0 | 71.95 | 36.5% |
| 10 | 86.82 | 79.0% |
| 20 | 93.23 | 97.3% |
| 30 | 94.12 | 99.9% |
| 40+ | 94.16 | 100.0% |

### Category Fill Order Impact

With same upper total but different categories filled, more remaining categories = higher EV due to flexibility.

---

*Analysis generated using Yahtzee EV Solver with joker rules. All values computed via dynamic programming with exact probabilities.*
