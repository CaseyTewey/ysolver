# You Are Probably Playing Yahtzee Wrong

*A data-driven analysis of the most common mistakes, backed by a mathematically optimal EV solver*

---

## Introduction

You've been playing Yahtzee for years. You know the rules. You've developed "instincts" for which dice to keep and when to take your points.

**Those instincts are costing you points. A lot of points.**

Using a mathematically optimal Expected Value (EV) solver that computes exact probabilities across all 1.5 million possible game states, we've identified the most common mistakes players make. Some of these will surprise you. A few might make you angry. All of them are costing you games.

**Baseline:** A perfect player scores **254.49 points** on average in Joker mode. How close are you?

---

## Part 1: The Dice You're Keeping Wrong

### Mistake #1: Keeping Low Pairs

You roll `[1, 1, 3, 4, 5]` on your first roll. What do you keep?

**What most players do:** Keep the pair of 1s. "It's a start toward Yahtzee or Full House!"

**What the solver says:** Keep `[3, 4, 5]` and go for the straight.

| Keep | EV |
|------|-----|
| [3, 4, 5] | **250.52** |
| [1, 1] | 249.05 |

**Cost of the mistake: 1.47 points**

Here's the brutal truth: **a pair of 1s is worth less than rerolling all five dice** (249.05 vs 249.36). Ones contribute almost nothing to the upper bonus, and a pair is a weak foundation for anything.

### The 2-3-4-5 Straight Draw Is Gold

The biggest keeping mistake we found:

**Roll:** `[2, 2, 3, 4, 5]`

| Keep | EV |
|------|-----|
| [2, 3, 4, 5] | **254.81** |
| [2, 2] | 250.45 |

**Cost of keeping the pair: 4.36 points**

The `[2, 3, 4, 5]` straight draw is so powerful it beats almost every pair:

| Pair | EV | vs [2,3,4,5] |
|------|-----|--------------|
| Pair of 2s | 250.45 | Loses by 4.36 |
| Pair of 3s | 251.30 | Loses by 3.51 |
| Pair of 4s | 252.13 | Loses by 2.68 |
| Pair of 5s | 252.91 | Loses by 1.90 |
| **Pair of 6s** | **253.83** | **Only pair that wins** |

**Rule of thumb:** Unless you have a pair of 6s, abandon your pair for `[2, 3, 4, 5]`.

*Source: `get_recommendation_joker()` analysis, fresh game state*

---

### Mistake #2: Keeping Two Pairs

**Roll:** `[5, 5, 6, 6, 1]`

**What most players do:** Keep both pairs. "I'm one away from Full House!"

**What the solver says:** Keep only `[6, 6]`.

| Keep | EV |
|------|-----|
| [6, 6] | **253.83** |
| [5, 5, 6, 6] | 250.86 |

**Cost of keeping both pairs: 2.97 points**

Full House is only worth 25 points. By keeping both pairs, you're limiting yourself to one reroll die, killing your chances at Yahtzee or Four-of-a-Kind. Keep the higher pair and give yourself three dice to improve.

**This is never correct.** In every two-pair scenario we tested, keeping just the higher pair was optimal.

*Source: `ev_solver.py:best_keep_roll1_joker()`, tested across 10+ two-pair combinations*

---

### Mistake #3: What To Do With Three-of-a-Kind

**Good news:** Your instincts are right here. Always keep all three.

**Roll:** `[3, 3, 3, 4, 5]` - keep `[3, 3, 3]`, not `[3, 4, 5]`

| Keep | EV |
|------|-----|
| [3, 3, 3] | **259.55** |
| [3, 4, 5] | 250.52 |

Even with what looks like a good straight draw, trips are too valuable to break up. The Yahtzee/Full House potential dominates.

**Every three-of-a-kind scenario we tested confirmed: never break up trips.**

*Source: Exhaustive testing via `get_recommendation_joker()` across all trip combinations*

---

### Mistake #4: Four-of-a-Kind... Stop Scoring It!

**Roll:** `[6, 6, 6, 6, 2]` on Roll 1

**What most players do:** "I'll take Four-of-a-Kind for 26 points!"

**What the solver says:** Keep `[6, 6, 6, 6]` and go for Yahtzee.

| Action | EV |
|--------|-----|
| Keep [6,6,6,6] and reroll | **284.24** |
| Take Four-of-a-Kind (26 pts) | 261.47 |

**Cost of taking the points: 22.77 points**

This is one of the costliest mistakes in Yahtzee. With two rolls remaining, your probability of hitting Yahtzee from four-of-a-kind is **30.56%**. That's almost one in three! And your fallback is still Four-of-a-Kind if you miss.

**Always chase Yahtzee from quads.** There is no exception.

*Source: `get_recommendation_joker()` and probability calculation: P(Yahtzee) = 1 - (5/6)^2 = 30.56%*

---

## Part 2: Category Selection Disasters

### Mistake #5: Scratching Yahtzee Early

**Roll:** `[1, 2, 3, 4, 6]` - You have to score something. Where do you put it?

**What many players do:** "I'll never roll a Yahtzee anyway. I'll scratch it."

**What the solver says:** Take Small Straight for 30.

| Category | Points | Total EV |
|----------|--------|----------|
| Small Straight | 30 | **246.42** |
| Scratch Four-of-a-Kind | 0 | 235.47 |
| **Scratch Yahtzee** | **0** | **228.21** |

**Cost of scratching Yahtzee: 18.21 points**

Even though you're scoring zero either way, scratching Yahtzee costs you **18 more points** than scratching Four-of-a-Kind. Why? Because Yahtzee is worth far more than 50 points.

### The True Value of Yahtzee: 92.6 Points

Under Joker rules, scoring your first Yahtzee unlocks +100 bonuses for each additional Yahtzee. The solver calculates:

| Yahtzee Status | EV Impact |
|----------------|-----------|
| Unfilled | 254.49 (baseline) |
| Scored (50 pts) | 297.12 (+42.63 future bonus value) |
| Scratched (0 pts) | 228.21 (-26.28) |

**Expected additional Yahtzees per game: 0.426**

After scoring your first Yahtzee, you have about a 40% chance of rolling at least one more in the remaining turns. That's worth ~43 points in expectation.

**Never scratch Yahtzee unless literally forced to on the final turn.**

*Source: `ev_remaining_joker()` comparison across yahtzee_status values 0, 1, 2*

---

### Mistake #6: Full House vs Three-of-a-Kind

**Roll:** `[5, 5, 5, 6, 6]` (sum = 27)

**What most players do:** "Three-of-a-Kind gives me 27, Full House only gives 25. Easy choice!"

**What the solver says:** Take Full House.

| Category | Points | EV |
|----------|--------|-----|
| **Full House** | **25** | **231.79** |
| Three-of-a-Kind | 27 | 230.83 |

**Cost of taking Three-of-a-Kind: 0.96 points**

Full House only appears in **4.0%** of rolls. Three-of-a-Kind appears in **29%**. The solver knows Full House is scarce and values preserving Three-of-a-Kind for later.

**The crossover point is sum = 28.** Below that, take Full House. Above that, Three-of-a-Kind edges ahead slightly.

*Source: `get_all_category_evs_joker()` analysis across full house rolls*

---

### Mistake #7: Taking Large Straight on Roll 1

**Roll:** `[1, 2, 3, 4, 5]` on Roll 1

**Common debate:** "Should I take it or go for Yahtzee?"

**What the solver says:** Take it. Or don't. It doesn't matter.

| Action | EV |
|--------|-----|
| Take Large Straight (40 pts) | **261.52** |
| Keep all and continue | **261.52** |

**These are exactly equal.** The common belief that you should "go for Yahtzee" is wrong - but so is the guilt from taking the sure 40 points. Both plays are optimal.

The math: From a Large Straight, your probability of Yahtzee is ~2.8% (must reroll one die twice and hit the same face both times). The tiny upside doesn't justify the variance.

**Take the 40 and feel good about it.**

*Source: `get_recommendation_joker([1,2,3,4,5], mask=0, upper=0, rolls=2, yahtzee_status=0)`*

---

### Mistake #8: Four-of-a-Kind Is Never Optimal (Fresh Game)

Across all 252 unique dice combinations, how often is each category the optimal choice in a fresh game?

| Rank | Category | % Optimal |
|------|----------|-----------|
| 1 | Ones | 22.6% |
| 2 | Twos | 15.5% |
| 3 | Threes | 12.3% |
| 4 | Full House | 11.5% |
| 5 | Chance | 11.1% |
| 6 | Fours | 6.0% |
| 7 | Fives | 5.6% |
| 8 | Small Straight | 5.6% |
| 9 | Sixes | 4.4% |
| 10 | Three-of-a-Kind | 2.4% |
| 11 | Yahtzee | 2.4% |
| 12 | Large Straight | 0.8% |
| **13** | **Four-of-a-Kind** | **0.0%** |

**Four-of-a-Kind is never the optimal category choice in a fresh game.** There's always something better - usually an upper section category or Yahtzee itself.

*Source: Exhaustive `get_all_category_evs_joker()` analysis over all 252 roll multisets*

---

## Part 3: The Upper Bonus Delusion

### Mistake #9: Ignoring the Upper Bonus

**The bonus:** Score 63+ in the upper section (Ones through Sixes), get +35 points.

**What most players think:** "It's nice if I get it, but I won't sacrifice points for it."

**What the solver knows:** The bonus is worth **16.70 EV points** on average and drives many counterintuitive optimal plays.

### Probability of Getting the Bonus

| Upper Total | P(Bonus) |
|-------------|----------|
| 0 | 47.7% |
| 10 | 79.0% |
| 20 | 97.3% |
| 30 | 99.9% |

Under optimal play, you get the bonus about half the time. But those early upper section scores are crucial.

### The Most Counterintuitive Play We Found

**Roll:** `[1, 4, 4, 5, 5]`

| Category | Points | EV |
|----------|--------|-----|
| Chance | 19 | 238.84 |
| **Ones** | **1** | **239.50** |

**Taking 1 point in Ones beats taking 19 in Chance.**

This seems insane, but the solver knows: progress toward the upper bonus, even a single point, is often worth more than a mediocre Chance score. The 35-point bonus looms large.

### More Examples of Upper Section Priority

| Roll | Obvious Play | Optimal Play | Sacrifice |
|------|-------------|--------------|-----------|
| [2, 2, 5, 6, 6] | Chance (21) | Twos (4) | 17 pts |
| [4, 4, 4, 5, 6] | 3-of-Kind (23) | Fours (12) | 11 pts |
| [3, 3, 4, 4, 5] | Chance (19) | Threes (6) | 13 pts |

**Pattern:** The solver prioritizes upper section progress, especially early in the game.

*Source: `get_all_category_evs_joker()` comparison, fresh game states*

---

### Mistake #10: Not Knowing When to Give Up on the Bonus

**Scenario:** You've filled 4 upper categories with only 18 points. Fives and Sixes remain. You need 45 more points (virtually impossible).

**Roll:** `[5, 5, 5, 3, 3]`

| Choice | Points | EV |
|--------|--------|-----|
| Fives (reach for bonus) | 15 | 177.71 |
| **Full House (give up)** | **25** | **184.14** |

**Cost of reaching: 6.43 points**

When the bonus is mathematically unlikely, stop chasing it. The solver knows when to pivot.

**Give-up thresholds:**
- Only Sixes remain, need 33+ in other categories
- Only Fives remain, need 38+ in other categories
- If max possible upper < 63, take the sure points

*Source: `ev_remaining_joker()` with restricted category masks*

---

## Part 4: Timing Mistakes That Cost You Games

### Mistake #11: Giving Up Mid-Turn

**Roll 1:** `[6, 6, 6, 6, 1]` - You go for Yahtzee.

**Roll 2:** `[6, 6, 4, 3, 2]` - Disaster! You lost two 6s.

**What most players do:** "Ugh, I'll just take what I can get."

**What the solver says:** Keep `[6, 6]` and keep rolling!

| Action | EV |
|--------|-----|
| Keep [6, 6] and reroll | **247.66** |
| Take Chance (21) | 240.84 |
| Take Sixes (12) | 232.12 |

**Cost of giving up: 6.82 points**

Even after a bad roll, the EV of continuing usually beats taking immediate points. Yahtzee's massive value (92.6 total EV at game start) makes low-probability attempts worthwhile.

*Source: `get_recommendation_joker()` roll 2 analysis*

---

### Mistake #12: Late-Game Timidity

**Turn 12:** You have Sixes, Yahtzee, and Chance remaining.

**Roll:** `[6, 6, 6, 2, 3]`

**What most players do:** "I'll just lock in Sixes for 18. Safe points!"

**What the solver says:** Go for Yahtzee.

| Action | EV |
|--------|-----|
| Continue for Yahtzee | **52.26** |
| Take Sixes (18) | 45.34 |

**Cost of playing safe: 6.93 points**

Even in the final turns, Yahtzee pursuit is profitable. The +100 joker bonus potential (if Yahtzee is already scored) or the 50-point base (if not) makes the gamble worthwhile.

*Source: `ev_remaining_joker()` late-game state analysis*

---

## Summary: The 12 Commandments of Optimal Yahtzee

1. **Abandon low pairs (1s, 2s) for `[2,3,4,5]` straight draws** - costs up to 4.36 EV
2. **Never keep two pairs** - always keep only the higher pair
3. **Always keep trips together** - never break up three-of-a-kind
4. **Always chase Yahtzee from four-of-a-kind** - costs 22.77 EV to take early
5. **Never scratch Yahtzee early** - it's worth 92.6 total EV, not 50
6. **Take Full House over 3K when sum < 28** - Full House is scarce
7. **Large Straight on Roll 1 is fine to take** - no EV loss either way
8. **Four-of-a-Kind is never optimal in a fresh game** - always something better
9. **Upper section progress beats Chance** - even 1 point can be optimal
10. **Know when to give up on the bonus** - don't chase the impossible
11. **Don't give up mid-turn** - keep rolling after setbacks
12. **Yahtzee pursuit is profitable even late-game** - don't play safe

---

## Quick Reference: EV by Keep Type (Roll 1, Fresh Game)

| Keep | EV | Notes |
|------|-----|-------|
| Four 6s | 284.24 | Best possible |
| Four 5s | 281.63 | |
| Four 4s | 279.24 | |
| Four 3s | 276.70 | |
| Four 2s | 273.83 | |
| Four 1s | 270.21 | Still great |
| Trip 6s | 265.02 | |
| Trip 5s | 263.07 | |
| Large Straight | 261.52 | Keep all 5! |
| Trip 4s | 261.35 | |
| Trip 3s | 259.55 | |
| Trip 2s | 257.60 | |
| Trip 1s | 254.89 | |
| [2,3,4,5] draw | 254.81 | Beats most pairs |
| Pair 6s | 253.83 | |
| Pair 5s | 252.91 | |
| Pair 4s | 252.13 | |
| Pair 3s | 251.30 | |
| [1,2,3,4] draw | 251.03 | |
| Pair 2s | 250.45 | |
| **Reroll all 5** | **249.36** | **Baseline** |
| Pair 1s | 249.05 | Below baseline! |

**A pair of 1s is worse than rerolling all five dice.**

---

## Methodology

All analysis performed using the Yahtzee EV Solver with:

- **Mode:** Joker rules (official Hasbro rules)
- **State Space:** 2^13 category masks x 64 upper subtotals x 3 Yahtzee statuses = **1,572,864 states**
- **Roll Space:** 252 unique 5-dice multisets
- **Computation:** Exact dynamic programming, no Monte Carlo approximation
- **Functions Used:**
  - `get_recommendation_joker()` - optimal keep/score decisions
  - `get_all_category_evs_joker()` - category comparison
  - `ev_remaining_joker()` - future game value
  - `best_keep_roll1_joker()`, `best_keep_roll2_joker()` - keep optimization

The solver computes mathematically optimal play by working backwards from all possible end states, weighting by exact multinomial probabilities for all dice outcomes.

**Fresh game EV under optimal play: 254.49 points**

---

*Generated using the [Yahtzee EV Solver](https://ysolver.onrender.com) - try it yourself!*
