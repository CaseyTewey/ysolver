from manim import *
import numpy as np

class YahtzeeProbabilityExplained(Scene):
    """
    A beginner-friendly animation explaining Yahtzee probability
    and Joker mode calculations.

    No LaTeX required - uses Text for all mathematical expressions.
    """

    def construct(self):
        # Section 1: Title and Introduction
        self.show_title()

        # Section 2: Basic Dice Probability
        self.explain_basic_probability()

        # Section 3: Multiple Dice - Multinomial
        self.explain_multinomial()

        # Section 4: Yahtzee Probability Example
        self.show_yahtzee_calculation()

        # Section 5: Joker Mode Explained
        self.explain_joker_mode()

        # Section 6: Joker Bonus Probability
        self.show_joker_bonus_probability()

        # Section 7: Summary
        self.show_summary()

    def show_title(self):
        """Display the opening title."""
        title = Text("Yahtzee Probability", font_size=60, color=BLUE)
        subtitle = Text("Understanding Joker Mode", font_size=36, color=YELLOW)
        subtitle.next_to(title, DOWN, buff=0.5)

        group = VGroup(title, subtitle)

        self.play(Write(title), run_time=1.5)
        self.play(FadeIn(subtitle, shift=UP), run_time=1)
        self.wait(2)
        self.play(FadeOut(group))

    def create_die(self, value, size=0.8, color=WHITE):
        """Create a visual representation of a die showing a specific value."""
        die = VGroup()

        # Die face (rounded square)
        face = RoundedRectangle(
            corner_radius=0.1,
            width=size,
            height=size,
            fill_color=color,
            fill_opacity=1,
            stroke_color=BLACK,
            stroke_width=2
        )
        die.add(face)

        # Dot positions for each value (normalized to die size)
        dot_radius = size * 0.08
        positions = {
            1: [(0, 0)],
            2: [(-0.2, 0.2), (0.2, -0.2)],
            3: [(-0.2, 0.2), (0, 0), (0.2, -0.2)],
            4: [(-0.2, 0.2), (0.2, 0.2), (-0.2, -0.2), (0.2, -0.2)],
            5: [(-0.2, 0.2), (0.2, 0.2), (0, 0), (-0.2, -0.2), (0.2, -0.2)],
            6: [(-0.2, 0.2), (0.2, 0.2), (-0.2, 0), (0.2, 0), (-0.2, -0.2), (0.2, -0.2)]
        }

        # Add dots
        for pos in positions.get(value, []):
            dot = Dot(
                point=[pos[0] * size, pos[1] * size, 0],
                radius=dot_radius,
                color=BLACK
            )
            die.add(dot)

        return die

    def explain_basic_probability(self):
        """Explain basic single die probability."""
        # Header
        header = Text("Step 1: Single Die Probability", font_size=40, color=GREEN)
        header.to_edge(UP)
        self.play(Write(header))

        # Show a single die
        die = self.create_die(3, size=1.2)
        die.shift(UP * 0.5)

        self.play(FadeIn(die, scale=0.5))

        # Explanation text
        explanation = VGroup(
            Text("When you roll one die:", font_size=28),
            Text("Each face (1-6) has an equal chance", font_size=28),
        ).arrange(DOWN, aligned_edge=LEFT)
        explanation.next_to(die, DOWN, buff=0.8)

        self.play(Write(explanation), run_time=2)
        self.wait(1)

        # Show the probability fraction (using Text instead of MathTex)
        prob_text = Text(
            "P(any face) = 1/6 = 16.67%",
            font_size=32
        )
        prob_text.next_to(explanation, DOWN, buff=0.5)

        # Create box around probability
        prob_box = SurroundingRectangle(prob_text, color=YELLOW, buff=0.2)

        self.play(Write(prob_text))
        self.play(Create(prob_box))
        self.wait(2)

        # Show all six dice faces
        self.play(FadeOut(die), FadeOut(explanation))

        all_dice = VGroup(*[self.create_die(i, size=0.9) for i in range(1, 7)])
        all_dice.arrange(RIGHT, buff=0.3)
        all_dice.move_to(ORIGIN + UP * 0.5)

        self.play(LaggedStart(*[FadeIn(d, scale=0.5) for d in all_dice], lag_ratio=0.15))

        # Fractions under each die
        fractions = VGroup(*[
            Text("1/6", font_size=24) for _ in range(6)
        ])
        for i, frac in enumerate(fractions):
            frac.next_to(all_dice[i], DOWN, buff=0.3)

        self.play(LaggedStart(*[Write(f) for f in fractions], lag_ratio=0.1))
        self.wait(2)

        # Cleanup
        self.play(
            FadeOut(all_dice),
            FadeOut(fractions),
            FadeOut(prob_text),
            FadeOut(prob_box),
            FadeOut(header)
        )

    def explain_multinomial(self):
        """Explain probability with multiple dice."""
        header = Text("Step 2: Rolling 5 Dice", font_size=40, color=GREEN)
        header.to_edge(UP)
        self.play(Write(header))

        # Show 5 dice
        five_dice = VGroup(*[self.create_die(i, size=0.9) for i in [1, 1, 3, 5, 6]])
        five_dice.arrange(RIGHT, buff=0.2)
        five_dice.move_to(UP * 1)

        self.play(LaggedStart(*[FadeIn(d, scale=0.5) for d in five_dice], lag_ratio=0.1))

        # Explanation
        exp1 = Text("In Yahtzee, you roll 5 dice at once.", font_size=28)
        exp2 = Text("There are 252 unique combinations!", font_size=28, color=YELLOW)
        exp_group = VGroup(exp1, exp2).arrange(DOWN, buff=0.3)
        exp_group.next_to(five_dice, DOWN, buff=0.7)

        self.play(Write(exp1))
        self.wait(1)
        self.play(Write(exp2))
        self.wait(2)

        # Show probability concept
        formula_intro = Text("The probability depends on:", font_size=28)
        formula_intro.next_to(exp_group, DOWN, buff=0.5)

        # Explain the formula parts using simple text
        explanation = VGroup(
            Text("1. How many ways to arrange the dice", font_size=24),
            Text("2. Removing duplicate arrangements", font_size=24),
            Text("3. Each die has 1/6 chance per face", font_size=24),
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.2)
        explanation.next_to(formula_intro, DOWN, buff=0.3)

        self.play(Write(formula_intro))
        self.play(Write(explanation), run_time=2)
        self.wait(2)

        # Show the key formula result
        formula = Text("Total outcomes: 6^5 = 7,776", font_size=30, color=BLUE)
        formula.next_to(explanation, DOWN, buff=0.4)
        self.play(Write(formula))
        self.wait(2)

        # Cleanup
        self.play(FadeOut(VGroup(header, five_dice, exp_group, formula_intro, explanation, formula)))

    def show_yahtzee_calculation(self):
        """Show how Yahtzee probability is calculated."""
        header = Text("Step 3: Yahtzee Probability", font_size=40, color=GREEN)
        header.to_edge(UP)
        self.play(Write(header))

        # Show 5 matching dice (Yahtzee!)
        yahtzee_dice = VGroup(*[self.create_die(4, size=0.9, color=GOLD) for _ in range(5)])
        yahtzee_dice.arrange(RIGHT, buff=0.2)
        yahtzee_dice.move_to(UP * 1.2)

        yahtzee_label = Text("YAHTZEE!", font_size=36, color=GOLD)
        yahtzee_label.next_to(yahtzee_dice, UP, buff=0.3)

        self.play(
            LaggedStart(*[FadeIn(d, scale=0.5) for d in yahtzee_dice], lag_ratio=0.1),
            Write(yahtzee_label)
        )
        self.wait(1)

        # Calculate probability on first roll
        calc_header = Text("Probability on a single roll:", font_size=28)
        calc_header.next_to(yahtzee_dice, DOWN, buff=0.6)

        step1 = Text("Total outcomes = 6^5 = 7,776", font_size=26)
        step2 = Text("Yahtzee outcomes = 6", font_size=26)
        step2b = Text("(all 1s, all 2s, ... all 6s)", font_size=22, color=GRAY)
        step3 = Text("P(Yahtzee) = 6/7776 = 0.077%", font_size=26, color=YELLOW)

        calc_steps = VGroup(step1, step2, step2b, step3).arrange(DOWN, aligned_edge=LEFT, buff=0.25)
        calc_steps.next_to(calc_header, DOWN, buff=0.4)

        self.play(Write(calc_header))
        for step in calc_steps:
            self.play(Write(step))
            self.wait(0.8)

        # Highlight the result
        result_box = SurroundingRectangle(step3, color=RED, buff=0.15)
        self.play(Create(result_box))
        self.wait(1)

        # Show the good news
        good_news = Text("But you get 3 rolls per turn!", font_size=30, color=GREEN)
        good_news.next_to(calc_steps, DOWN, buff=0.4)

        self.play(Write(good_news))

        # Show improved probability
        improved = Text(
            "P(Yahtzee per turn) = ~4.6%",
            font_size=30,
            color=YELLOW
        )
        improved.next_to(good_news, DOWN, buff=0.3)

        improved_box = SurroundingRectangle(improved, color=YELLOW, buff=0.15)

        self.play(Write(improved), Create(improved_box))
        self.wait(2)

        # Cleanup
        self.play(FadeOut(VGroup(
            header, yahtzee_dice, yahtzee_label, calc_header,
            calc_steps, result_box, good_news, improved, improved_box
        )))

    def explain_joker_mode(self):
        """Explain what Joker Mode is."""
        header = Text("Step 4: What is Joker Mode?", font_size=40, color=PURPLE)
        header.to_edge(UP)
        self.play(Write(header))

        # Joker mode explanation
        intro = Text("Joker Mode = Official Yahtzee Bonus Rule!", font_size=28, color=YELLOW)
        intro.next_to(header, DOWN, buff=0.5)
        self.play(Write(intro))

        # Create a simple scorecard visualization
        yahtzee_box = Rectangle(width=4, height=0.8, color=WHITE)
        yahtzee_text = Text("Yahtzee", font_size=24)
        yahtzee_score = Text("50", font_size=24, color=GREEN)
        yahtzee_text.move_to(yahtzee_box.get_left() + RIGHT * 1)
        yahtzee_score.move_to(yahtzee_box.get_right() + LEFT * 0.5)
        scorecard = VGroup(yahtzee_box, yahtzee_text, yahtzee_score)
        scorecard.next_to(intro, DOWN, buff=0.5)

        self.play(Create(yahtzee_box), Write(yahtzee_text), Write(yahtzee_score))

        # Rules
        rules = VGroup(
            Text("The Rules:", font_size=26, color=BLUE),
            Text("1. First Yahtzee = 50 points", font_size=22),
            Text("2. Each EXTRA Yahtzee = +100 BONUS!", font_size=22, color=GOLD),
            Text("3. Must use matching upper section first", font_size=22),
            Text("4. Or use any open lower section", font_size=22),
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.2)
        rules.next_to(scorecard, DOWN, buff=0.4)

        for rule in rules:
            self.play(Write(rule), run_time=0.7)
            self.wait(0.4)

        self.wait(1)

        # Show example
        example_header = Text("Example:", font_size=26, color=GREEN)
        example_header.next_to(rules, DOWN, buff=0.4)
        self.play(Write(example_header))

        # Show dice rolling a second yahtzee
        second_yahtzee = VGroup(*[self.create_die(3, size=0.6, color=GOLD) for _ in range(5)])
        second_yahtzee.arrange(RIGHT, buff=0.1)
        second_yahtzee.next_to(example_header, DOWN, buff=0.25)

        self.play(LaggedStart(*[FadeIn(d, scale=0.5) for d in second_yahtzee], lag_ratio=0.1))

        bonus_text = Text("Five 3s again = +100 bonus!", font_size=22, color=GOLD)
        bonus_text.next_to(second_yahtzee, DOWN, buff=0.2)
        self.play(Write(bonus_text))

        score_calc = Text("Score: 3x5=15 (Threes) + 100 = 115 pts!", font_size=22)
        score_calc.next_to(bonus_text, DOWN, buff=0.15)
        self.play(Write(score_calc))

        self.wait(2)

        # Cleanup
        self.play(FadeOut(VGroup(
            header, intro, scorecard, rules, example_header,
            second_yahtzee, bonus_text, score_calc
        )))

    def show_joker_bonus_probability(self):
        """Calculate probability of getting a Joker bonus."""
        header = Text("Step 5: Joker Bonus Probability", font_size=40, color=PURPLE)
        header.to_edge(UP)
        self.play(Write(header))

        # Setup
        setup = Text("After your first Yahtzee, what are", font_size=26)
        setup2 = Text("the chances of getting a bonus?", font_size=26)
        setup_group = VGroup(setup, setup2).arrange(DOWN, buff=0.1)
        setup_group.next_to(header, DOWN, buff=0.5)
        self.play(Write(setup_group))

        # Create timeline visualization
        timeline_header = Text("Remaining turns: ~12", font_size=24, color=BLUE)
        timeline_header.next_to(setup_group, DOWN, buff=0.4)
        self.play(Write(timeline_header))

        # Show probability calculation step by step
        calc = VGroup(
            Text("P(Yahtzee per turn) = 4.6%", font_size=26),
            Text("P(NO Yahtzee per turn) = 95.4%", font_size=26),
            Text("P(NO bonus in 12 turns) = 0.954^12", font_size=26),
            Text("= 55%", font_size=26, color=RED),
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.25)
        calc.next_to(timeline_header, DOWN, buff=0.4)

        for eq in calc:
            self.play(Write(eq))
            self.wait(0.8)

        # Final result
        result = Text(
            "P(At least one bonus) = 1 - 55% = 45%",
            font_size=28,
            color=GOLD
        )
        result.next_to(calc, DOWN, buff=0.4)
        result_box = SurroundingRectangle(result, color=GOLD, buff=0.2)

        self.play(Write(result), Create(result_box))
        self.wait(1)

        # Interpretation
        interp = Text("Nearly half of games with a Yahtzee", font_size=24, color=GREEN)
        interp2 = Text("earn at least one +100 bonus!", font_size=24, color=GREEN)
        interp_group = VGroup(interp, interp2).arrange(DOWN, buff=0.1)
        interp_group.next_to(result_box, DOWN, buff=0.3)
        self.play(Write(interp_group))

        self.wait(2)

        # Cleanup
        self.play(FadeOut(VGroup(header, setup_group, timeline_header, calc, result, result_box, interp_group)))

    def show_summary(self):
        """Show a summary of key points."""
        header = Text("Summary: Key Probabilities", font_size=40, color=BLUE)
        header.to_edge(UP)
        self.play(Write(header))

        # Key facts
        facts = VGroup(
            VGroup(
                self.create_die(6, size=0.5),
                Text("Single die: 1/6 = 16.7%", font_size=24)
            ).arrange(RIGHT, buff=0.3),

            VGroup(
                VGroup(*[self.create_die(4, size=0.4) for _ in range(5)]).arrange(RIGHT, buff=0.05),
                Text("Yahtzee (1 roll): 0.077%", font_size=24)
            ).arrange(RIGHT, buff=0.3),

            VGroup(
                Text("3 rolls", font_size=20, color=YELLOW),
                Text("Yahtzee per turn: ~4.6%", font_size=24)
            ).arrange(RIGHT, buff=0.3),

            VGroup(
                Text("JOKER", font_size=20, color=GOLD),
                Text("Bonus chance: ~45%", font_size=24, color=GOLD)
            ).arrange(RIGHT, buff=0.3),
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.4)
        facts.next_to(header, DOWN, buff=0.7)

        for fact in facts:
            self.play(FadeIn(fact, shift=RIGHT), run_time=0.7)
            self.wait(0.8)

        self.wait(1)

        # Final message
        final = Text("Now you understand Yahtzee probability!", font_size=30, color=GREEN)
        final.next_to(facts, DOWN, buff=0.6)
        self.play(Write(final))

        self.wait(2)

        # Fade out everything
        self.play(FadeOut(VGroup(header, facts, final)))

        # End card
        thanks = Text("Thanks for watching!", font_size=48, color=BLUE)
        self.play(Write(thanks))
        self.wait(2)
        self.play(FadeOut(thanks))


# Shorter standalone scene for quick demo
class QuickYahtzeeProbability(Scene):
    """A quick 30-second overview of Yahtzee probability."""

    def create_die(self, value, size=0.8, color=WHITE):
        die = VGroup()
        face = RoundedRectangle(corner_radius=0.1, width=size, height=size,
                               fill_color=color, fill_opacity=1,
                               stroke_color=BLACK, stroke_width=2)
        die.add(face)

        dot_radius = size * 0.08
        positions = {
            1: [(0, 0)],
            2: [(-0.2, 0.2), (0.2, -0.2)],
            3: [(-0.2, 0.2), (0, 0), (0.2, -0.2)],
            4: [(-0.2, 0.2), (0.2, 0.2), (-0.2, -0.2), (0.2, -0.2)],
            5: [(-0.2, 0.2), (0.2, 0.2), (0, 0), (-0.2, -0.2), (0.2, -0.2)],
            6: [(-0.2, 0.2), (0.2, 0.2), (-0.2, 0), (0.2, 0), (-0.2, -0.2), (0.2, -0.2)]
        }

        for pos in positions.get(value, []):
            dot = Dot(point=[pos[0] * size, pos[1] * size, 0], radius=dot_radius, color=BLACK)
            die.add(dot)

        return die

    def construct(self):
        # Title
        title = Text("Yahtzee Joker Mode", font_size=48, color=BLUE)
        self.play(Write(title))
        self.wait(1)
        self.play(title.animate.to_edge(UP).scale(0.7))

        # Show yahtzee
        dice = VGroup(*[self.create_die(5, size=0.8, color=GOLD) for _ in range(5)])
        dice.arrange(RIGHT, buff=0.15)
        self.play(LaggedStart(*[FadeIn(d, scale=0.5) for d in dice], lag_ratio=0.1))

        # Key stats
        stats = VGroup(
            Text("P(Yahtzee per turn) = 4.6%", font_size=28),
            Text("First Yahtzee = 50 pts", font_size=28),
            Text("Each extra = +100 BONUS!", font_size=28, color=GOLD),
            Text("P(getting a bonus) = 45%", font_size=28, color=GREEN),
        ).arrange(DOWN, buff=0.3)
        stats.next_to(dice, DOWN, buff=0.5)

        for stat in stats:
            self.play(Write(stat), run_time=0.8)
            self.wait(0.5)

        self.wait(2)


if __name__ == "__main__":
    print("Render commands:")
    print("  Low quality preview:  manim -pql yahtzee_probability_animation.py YahtzeeProbabilityExplained")
    print("  High quality:         manim -pqh yahtzee_probability_animation.py YahtzeeProbabilityExplained")
    print("  Quick demo:           manim -pql yahtzee_probability_animation.py QuickYahtzeeProbability")
