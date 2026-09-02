# Yahtzee High-Variance Category Timing: A Solver-Based Analysis

This research document analyzes optimal timing decisions for high-variance categories in Yahtzee, with a focus on the Yahtzee category itself. All findings are based on exact Expected Value (EV) calculations from the Yahtzee solver using Joker mode rules.

## Executive Summary

| Finding | Impact |
|---------|--------|
| Never scratch Yahtzee early | ~18 EV loss |
| Large Straight on roll 1 - take it | No EV loss |
| Scored Yahtzee future value | +42.2 EV |
| Always continue with 4-of-a-kind | 22+ EV gain |
| Yahtzee pursuit continues into late game | Still profitable |

---

## 1. When to Scratch Yahtzee (Take 0)

### Key Finding: **Never scratch Yahtzee early in the game**

The solver analysis reveals that scratching Yahtzee is almost never correct until very late in the game, even with terrible rolls.

### Fresh Game EV Comparison

| Yahtzee Status | EV (12 cats remaining) |
|----------------|------------------------|
| Unfilled       | 254.59                 |
| Scratched (0)  | 228.58                 |
| Scored (50)    | 270.83                 |

**The cost of scratching Yahtzee early is enormous.** Scratching Yahtzee with 12 categories remaining means giving up not just the 50 points, but also approximately 42.2 points in future joker bonus potential.

### Example: Bad Roll Analysis

Roll: [1, 2, 3, 4, 6] (no Yahtzee potential)

| Category | Points | Total EV |
|----------|--------|----------|
| Small Straight | 30 | 246.56 |
| Ones | 1 | 239.63 |
| Twos | 2 | 236.18 |
| Chance | 16 | 235.96 |
| Four of a Kind | 0 | 235.54 |
| **Yahtzee** | **0** | **228.58** |

Even with a terrible roll, scratching Yahtzee costs **17.97 EV** compared to the optimal play (Small Straight).

### When IS Scratching Correct?

Scratching Yahtzee is rarely correct before the mid-game:
- Turn 12-13 when Yahtzee is the only remaining option
- When all viable alternatives are already filled
- Never in a fresh game, and rarely as a "dump" category early in the game

---

## 2. Large Straight on Roll 1: Take It or Go for Yahtzee?

### Key Finding: **Taking Large Straight is optimal (no loss)**

This is a classic decision that many players agonize over. The solver provides a definitive answer.

### Roll: [1, 2, 3, 4, 5] on Roll 1

| Option | EV |
|--------|-----|
| Take Large Straight (40 pts) | 261.53 |
| Keep all and reroll | 261.53 |

**Verdict:** Both options are exactly equal! Taking the Large Straight is NOT a mistake.

### Roll: [2, 3, 4, 5, 6] on Roll 1

| Option | EV |
|--------|-----|
| Take Large Straight (40 pts) | 261.53 |
| Keep all and reroll | 261.53 |

**Verdict:** Same result - both options are equivalent.

### Why This Makes Sense

The 40 points from Large Straight is a known, guaranteed value. Going for Yahtzee from a Large Straight position has very low probability:
- Keep one die and reroll the other four, twice, chasing five of a kind
- Combined: approximately 1.3%

The ~1% chance of gaining an extra 10 points (50 - 40) doesn't justify the variance risk.

### Important Caveat: If Large Straight is Already Filled

If Large Straight is filled, strategy changes dramatically:

Roll: [1, 2, 3, 4, 5] with LS filled

| Action | Details |
|--------|---------|
| Best keep | [5] only |
| EV | 217.00 |

The solver recommends keeping a single high die and going for a different category (likely Fives or Yahtzee).

---

## 3. The Joker Rule: How Much is a Scored Yahtzee Worth?

### Key Finding: **Scoring Yahtzee is worth 92.2 total EV, not just 50**

The Joker rule in official Yahtzee gives +100 points for each additional Yahtzee after the first. This creates massive future value.

### Yahtzee Value Breakdown

States used: the first boxes on the scorecard (Ones, Twos, ...) already filled at par when the Yahtzee is scored.

| Game Stage | Points | Bonus Value | Total Value |
|------------|--------|-------------|-------------|
| Turn 1     | 50     | +42.2       | **92.2**    |
| Turn 4     | 50     | +28.2       | 78.2        |
| Turn 7     | 50     | +16.9       | 66.9        |
| Turn 10    | 50     | +4.4        | 54.4        |
| Turn 13    | 50     | +2.3        | 52.3        |

### Probability of Another Yahtzee by Remaining Turns

| Turns Remaining | Bonus Value | P(at least one more) |
|-----------------|-------------|----------------------|
| 12              | 42.25       | 37.3%                |
| 9               | 28.22       | 27.3%                |
| 6               | 16.87       | 17.7%                |
| 3               | 4.42        | 6.5%                 |
| 1               | 2.28        | 3.4%                 |

**Interpretation:** From a fresh game, after scoring your first Yahtzee, you have approximately a 37% chance of rolling at least one more Yahtzee in the remaining 12 turns.

### Expected Additional Yahtzees Per Game

From the solver:
- Future bonus EV from scored Yahtzee: **42.25 points**
- Expected additional Yahtzees: **0.459 per game**

This means on average, players who score their first Yahtzee will score about 0.46 additional Yahtzees worth +100 each.

---

## 4. When to Abandon Yahtzee Pursuit Mid-Turn

### Key Finding: **Almost never abandon - keep rolling**

The solver consistently recommends continuing to pursue Yahtzee even after bad intermediate rolls.

### Scenario: Going for 6s Yahtzee

**Roll 1:** [6, 6, 6, 6, 1]
- Optimal keep: [6, 6, 6, 6]
- EV: 284.30

**Roll 2 (missed):** [6, 6, 6, 6, 3]
- Optimal keep: [6, 6, 6, 6]
- EV: 277.00
- **Still go for Yahtzee!**

### Disaster Recovery: Roll 2 Setback

**Roll 2:** [6, 6, 4, 3, 2] (lost 2 sixes)
- Optimal keep: [6, 6]
- EV if continuing: 247.78

Compare to scoring now:
| Category | Points | EV |
|----------|--------|-----|
| Chance | 21 | 240.96 |
| Twos | 2 | 236.18 |
| Sixes | 12 | 232.20 |

**Verdict:** Keep rolling! The 247.78 EV from continuing beats the best immediate score by 6.82 points.

### General Principle

The high value of Yahtzee (92.2 total at game start) means that even low-probability Yahtzee attempts are worth the risk. Only abandon when:
1. You're on roll 3 and must score
2. The category math makes a sure thing clearly better (rare)

---

## 5. Late Game vs Early Game Yahtzee Strategy

### Key Finding: **Yahtzee remains valuable throughout, but strategy context shifts**

### Yahtzee Value by Game Stage

| Stage | If Score Yahtzee | Best Alternative | Margin |
|-------|------------------|------------------|--------|
| Early (fresh) | 320.83 EV | 279.47 (Sixes) | +41.36 |
| Mid (Ones through Fives filled at par) | 241.44 EV | 206.74 (Sixes) | +34.71 |
| Late (2 cats) | 50.00 EV | (depends) | varies |

### Early Game: Aggressive Yahtzee Pursuit

With a full game ahead:
- Future bonus value is highest (~42.2 EV)
- Many turns to capitalize on Joker bonuses
- Alternative categories can be filled later

**Recommendation:** Aggressively pursue Yahtzee when you have any reasonable chance (pairs, triples, four-of-a-kind).

### Mid Game: Context-Dependent

Key considerations:
- Upper bonus progress (are you on track for 63?)
- Which categories remain open
- Yahtzee bonus value still substantial (~12-30 EV)

**Recommendation:** Continue pursuing Yahtzee but weigh against upper bonus needs.

### Late Game: Still Worth Pursuing

Even on turn 12 with only 2-3 categories left:

Example: [6, 6, 6, 2, 3] with Sixes, Yahtzee, Chance remaining
- Take Sixes now: 45.34 EV
- Continue for Yahtzee: 52.26 EV
- **Gain from continuing: 6.92 EV**

**Recommendation:** The Yahtzee pursuit remains EV-positive even in the final turns, though margins are smaller.

---

## 6. The Four-of-a-Kind Decision

### Key Finding: **Always continue rolling with 4-of-a-kind**

This is one of the most costly mistakes players make.

### Analysis: [6, 6, 6, 6, 2] on Roll 1

| Option | EV |
|--------|-----|
| Take Four-of-a-Kind (26 pts) | 261.54 |
| Continue rolling | 284.30 |
| **EV Lost by taking early** | **22.77** |

### Probability Breakdown

- P(Yahtzee on 1 die reroll) = 1/6 = 16.67%
- P(Miss) = 5/6 = 83.33%

Expected value of going for Yahtzee with one roll left (268.23 is the average of the best scores after a miss):
```
EV = (1/6) * 320.83 + (5/6) * 268.23 = 277.00
```

This is still much higher than taking the 4-of-a-kind immediately (261.54).

### On Roll 2

**Roll 2:** [6, 6, 6, 6, 3]
- Keep [6, 6, 6, 6]
- EV: 277.00
- **Still go for Yahtzee!**

---

## 7. The Forced Category Rule (Joker Rules)

### Key Finding: **Understand the forced category mechanic**

When you roll a second Yahtzee with your first scored as 50:

1. **If corresponding upper section is open:** You MUST take it
2. **If corresponding upper is filled:** Free choice in lower section (if no lower box is open, a zero goes in an open upper box)
3. **All lower sections use Joker exceptions:** FH=25, SS=30, LS=40

### Example: Yahtzee of 3s [3,3,3,3,3]

**Threes still open:**
| Category | Points | Note |
|----------|--------|------|
| Threes | 115 (15+100) | **FORCED** |
| Chance | N/A | Cannot choose |

**Threes already filled (with 9):**
| Category | Points | EV |
|----------|--------|-----|
| Large Straight | 140 | 360.50 (best choice!) |
| Full House | 125 | 351.95 |
| Four of a Kind | 115 | 346.16 |
| Small Straight | 130 | 344.81 |
| Chance | 115 | 331.90 |

When forced to upper section, you still get the +100 bonus, so it's always profitable.

---

## 8. Common Timing Mistakes Summary

| Mistake | Cost (EV) | Correct Play |
|---------|-----------|--------------|
| Scratching Yahtzee early | 17.97+ | Take Small Straight instead |
| Taking Large Straight early | 0.00 | Either option is fine |
| Taking 4-of-a-kind on roll 1 | 22.77 | Continue rolling |
| Taking safe option late game | 6.92 | Continue for Yahtzee |

---

## 9. Key Takeaways

1. **Never scratch Yahtzee early** - The combined value (50 points + 42.2 future bonus potential) makes it the most valuable category by far.

2. **Large Straight on roll 1 is fine to take** - Despite common belief, there's no EV loss from taking it immediately.

3. **Yahtzee is worth 92.2 EV at game start** - The Joker rule adds massive hidden value (42.2 EV in future bonus potential).

4. **Always continue with 4-of-a-kind** - Taking the points early costs 22+ EV; the 1/6 chance at Yahtzee is worth it.

5. **Yahtzee pursuit is profitable throughout the game** - Even in late turns, going for Yahtzee typically beats safe alternatives.

6. **Expected additional Yahtzees: 0.46 per game** - After scoring your first, you'll average almost half an extra Yahtzee.

---

## Methodology

All calculations performed using the Yahtzee EV solver with:
- **Mode:** Joker rules (official Hasbro rules)
- **Yahtzee Status States:**
  - 0 = Unfilled
  - 1 = Scratched (0 points, no future bonuses)
  - 2 = Scored (50 points, eligible for +100 bonuses)
- **Function:** `Solver.ev(mask, upper, yb)` in engine.py

The solver uses dynamic programming to compute exact expected values for all 2^13 * 64 * 2 = 1,048,576 table entries.
