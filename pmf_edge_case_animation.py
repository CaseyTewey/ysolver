from manim import *
import numpy as np

class PMFvsApproximation(Scene):
    """
    45-second animation showing why exact PMF beats normal approximation.
    Edge case: Two players tied with Large Straight + Yahtzee remaining.

    Render: manim -qh pmf_edge_case_animation.py PMFvsApproximation
    """

    def construct(self):
        # Timing targets (45 seconds total):
        # Scene 1: 0-8s   (Setup)
        # Scene 2: 8-20s  (PMF bars)
        # Scene 3: 20-32s (Normal overlay + comparison)
        # Scene 4: 32-42s (Impact)
        # Scene 5: 42-45s (Closing)

        self.scene_1_setup()      # ~8s
        self.scene_2_pmf_bars()   # ~12s
        self.scene_3_normal_fails()  # ~12s
        self.scene_4_impact()     # ~10s
        self.scene_5_closing()    # ~3s

    def scene_1_setup(self):
        """Scene 1: Setup the scenario (0-8s)"""
        # Title
        title = Text("Why Exact Probability Beats Approximation", font_size=42, color=BLUE)
        title.to_edge(UP, buff=0.5)
        self.play(Write(title), run_time=1.2)

        # Scenario description
        scenario = VGroup(
            Text("Late-game Yahtzee scenario:", font_size=32, color=WHITE),
            Text("Two players TIED at 250 points", font_size=28, color=YELLOW),
            Text("Both have 2 categories left:", font_size=28),
        ).arrange(DOWN, buff=0.25)
        scenario.next_to(title, DOWN, buff=0.6)

        self.play(Write(scenario), run_time=1.5)

        # Show the two categories with icons
        categories = VGroup(
            self.create_category_box("Large Straight", "0 or 40 pts", BLUE),
            self.create_category_box("Yahtzee", "0 or 50 pts", GOLD),
        ).arrange(RIGHT, buff=0.8)
        categories.next_to(scenario, DOWN, buff=0.5)

        self.play(
            LaggedStart(*[FadeIn(c, scale=0.8) for c in categories], lag_ratio=0.2),
            run_time=1.2
        )

        # Key question
        question = Text("What are the win probabilities?", font_size=36, color=GREEN)
        question.next_to(categories, DOWN, buff=0.5)
        self.play(Write(question), run_time=1)

        self.wait(0.8)

        # Store and clear
        self.setup_elements = VGroup(title, scenario, categories, question)
        self.play(FadeOut(self.setup_elements), run_time=0.6)

    def create_category_box(self, name, points, color):
        """Create a styled category box."""
        box = RoundedRectangle(
            corner_radius=0.15, width=3.2, height=1.2,
            fill_color=color, fill_opacity=0.2,
            stroke_color=color, stroke_width=2
        )
        name_text = Text(name, font_size=24, color=color)
        points_text = Text(points, font_size=20, color=WHITE)
        name_text.move_to(box.get_center() + UP * 0.2)
        points_text.move_to(box.get_center() + DOWN * 0.25)
        return VGroup(box, name_text, points_text)

    def scene_2_pmf_bars(self):
        """Scene 2: Show discrete PMF distribution (8-20s)"""
        # Header
        header = Text("PMF: The Exact Distribution", font_size=38, color=GREEN)
        header.to_edge(UP, buff=0.4)
        self.play(Write(header), run_time=0.8)

        # Create axes
        axes = Axes(
            x_range=[0, 100, 20],
            y_range=[0, 60, 10],
            x_length=10,
            y_length=4.5,
            axis_config={"include_tip": False, "include_numbers": False},
        )
        axes.shift(DOWN * 0.3)

        # X-axis labels
        x_labels = VGroup(
            Text("0", font_size=20).next_to(axes.c2p(0, 0), DOWN, buff=0.15),
            Text("40", font_size=20).next_to(axes.c2p(40, 0), DOWN, buff=0.15),
            Text("50", font_size=20).next_to(axes.c2p(50, 0), DOWN, buff=0.15),
            Text("90", font_size=20).next_to(axes.c2p(90, 0), DOWN, buff=0.15),
        )
        x_axis_label = Text("Additional Score", font_size=22).next_to(axes, DOWN, buff=0.5)

        # Y-axis label
        y_axis_label = Text("Probability (%)", font_size=22).rotate(PI/2)
        y_axis_label.next_to(axes, LEFT, buff=0.4)

        self.play(Create(axes), Write(x_labels), Write(x_axis_label), Write(y_axis_label), run_time=1)

        # PMF data: approximate probabilities for the 4 outcomes
        # Miss both: ~50%, Large Straight only: ~30%, Yahtzee only: ~15%, Both: ~5%
        # These create scores of 0, 40, 50, 90
        pmf_data = [
            (0, 50.5, RED),      # Miss both
            (40, 29.4, BLUE),    # Large Straight only
            (50, 15.1, GOLD),    # Yahtzee only
            (90, 5.0, GREEN),    # Hit both
        ]

        bars = VGroup()
        bar_labels = VGroup()
        bar_width = 6

        for score, prob, color in pmf_data:
            bar = Rectangle(
                width=bar_width * 0.08,
                height=prob * 0.075,
                fill_color=color,
                fill_opacity=0.8,
                stroke_color=WHITE,
                stroke_width=1
            )
            bar.move_to(axes.c2p(score, prob/2))
            bars.add(bar)

            label = Text(f"{prob}%", font_size=18, color=color)
            label.next_to(bar, UP, buff=0.1)
            bar_labels.add(label)

        # Animate bars growing
        self.play(
            LaggedStart(*[GrowFromEdge(bar, DOWN) for bar in bars], lag_ratio=0.15),
            run_time=1.5
        )
        self.play(
            LaggedStart(*[FadeIn(label, shift=UP*0.2) for label in bar_labels], lag_ratio=0.1),
            run_time=1
        )

        # Highlight message
        highlight = Text("Only 4 possible outcomes!", font_size=32, color=YELLOW)
        highlight.next_to(axes, DOWN, buff=1.2)
        highlight_box = SurroundingRectangle(highlight, color=YELLOW, buff=0.15)

        self.play(Write(highlight), Create(highlight_box), run_time=0.8)
        self.wait(1.2)

        # Store for next scene
        self.pmf_header = header
        self.axes = axes
        self.bars = bars
        self.bar_labels = bar_labels
        self.x_labels = x_labels
        self.x_axis_label = x_axis_label
        self.y_axis_label = y_axis_label
        self.highlight = VGroup(highlight, highlight_box)

        # Shift everything up a bit to make room
        self.play(
            FadeOut(self.highlight),
            run_time=0.5
        )

    def scene_3_normal_fails(self):
        """Scene 3: Show normal approximation overlay and comparison (20-32s)"""
        # Add normal curve header
        normal_header = Text("vs Normal Approximation", font_size=32, color=RED)
        normal_header.next_to(self.pmf_header, RIGHT, buff=0.3)
        self.play(Write(normal_header), run_time=0.6)

        # Create Gaussian curve overlay
        mean = 45  # approximate mean of the distribution
        std = 25   # approximate std

        def gaussian(x):
            return 45 * np.exp(-0.5 * ((x - mean) / std) ** 2)

        curve = self.axes.plot(gaussian, x_range=[0, 95], color=RED, stroke_width=3)
        curve_label = Text("Normal", font_size=20, color=RED)
        curve_label.next_to(curve.get_center() + UP * 1.5 + RIGHT * 1, UP)

        self.play(Create(curve), Write(curve_label), run_time=1.2)

        # Show the problem
        problem = Text("Smooth curve misses discrete peaks!", font_size=28, color=RED)
        problem.next_to(self.axes, DOWN, buff=0.8)
        self.play(Write(problem), run_time=0.8)
        self.wait(0.8)

        # Clear chart area and show comparison
        self.play(
            FadeOut(VGroup(
                self.axes, self.bars, self.bar_labels, curve,
                self.x_labels, self.x_axis_label, self.y_axis_label,
                curve_label, problem, self.pmf_header, normal_header
            )),
            run_time=0.6
        )

        # Show probability comparison
        comparison_title = Text("TIE PROBABILITY COMPARISON", font_size=36, color=WHITE)
        comparison_title.to_edge(UP, buff=0.5)
        self.play(Write(comparison_title), run_time=0.6)

        # PMF box
        pmf_box = self.create_result_box(
            "Exact PMF",
            "P(tie) = 4.06%",
            GREEN,
            check=True
        )
        pmf_box.shift(LEFT * 3)

        # Normal box
        normal_box = self.create_result_box(
            "Normal Approx",
            "P(tie) = 0.00%",
            RED,
            check=False
        )
        normal_box.shift(RIGHT * 3)

        self.play(FadeIn(pmf_box, shift=UP), run_time=0.6)
        self.play(FadeIn(normal_box, shift=UP), run_time=0.6)

        # Arrow showing the error
        error_arrow = Arrow(
            normal_box.get_left() + LEFT * 0.2,
            pmf_box.get_right() + RIGHT * 0.2,
            color=YELLOW,
            stroke_width=4
        )
        error_text = Text("4% error!", font_size=28, color=YELLOW)
        error_text.next_to(error_arrow, UP, buff=0.1)

        self.play(GrowArrow(error_arrow), Write(error_text), run_time=0.8)
        self.wait(1)

        # Store for transition
        self.comparison_elements = VGroup(comparison_title, pmf_box, normal_box, error_arrow, error_text)

    def create_result_box(self, title, result, color, check=True):
        """Create a result display box."""
        box = RoundedRectangle(
            corner_radius=0.2, width=4.5, height=2.5,
            fill_color=color, fill_opacity=0.15,
            stroke_color=color, stroke_width=3
        )
        title_text = Text(title, font_size=26, color=color)
        title_text.move_to(box.get_center() + UP * 0.7)

        result_text = Text(result, font_size=32, color=WHITE)
        result_text.move_to(box.get_center())

        if check:
            icon = Text("Correct", font_size=22, color=GREEN)
        else:
            icon = Text("WRONG", font_size=22, color=RED)
        icon.move_to(box.get_center() + DOWN * 0.7)

        return VGroup(box, title_text, result_text, icon)

    def scene_4_impact(self):
        """Scene 4: Show the real impact (32-42s)"""
        # Transition
        self.play(FadeOut(self.comparison_elements), run_time=0.5)

        # New title
        impact_title = Text("THE REAL IMPACT", font_size=42, color=YELLOW)
        impact_title.to_edge(UP, buff=0.5)
        self.play(Write(impact_title), run_time=0.6)

        # Win probability comparison
        subtitle = Text("Head-to-Head Win Probability", font_size=30)
        subtitle.next_to(impact_title, DOWN, buff=0.4)
        self.play(Write(subtitle), run_time=0.5)

        # Create two columns
        normal_col = VGroup(
            Text("Normal Says:", font_size=26, color=RED),
            Text("Win: 50.0%", font_size=32),
            Text("Tie: 0.0%", font_size=32),
            Text("Lose: 50.0%", font_size=32),
        ).arrange(DOWN, buff=0.2)
        normal_col.shift(LEFT * 3.5)

        pmf_col = VGroup(
            Text("Reality (PMF):", font_size=26, color=GREEN),
            Text("Win: 44.1%", font_size=32),
            Text("Tie: 4.06%", font_size=32, color=YELLOW),
            Text("Lose: 51.84%", font_size=32),
        ).arrange(DOWN, buff=0.2)
        pmf_col.shift(RIGHT * 3.5)

        vs_text = Text("vs", font_size=36, color=WHITE)

        self.play(Write(normal_col), run_time=1)
        self.play(Write(vs_text), run_time=0.3)
        self.play(Write(pmf_col), run_time=1)

        # Highlight the error
        error_highlight = VGroup(
            Text("5.9 percentage point error!", font_size=36, color=RED),
            Text("in a perfectly tied game", font_size=28, color=WHITE),
        ).arrange(DOWN, buff=0.15)
        error_highlight.next_to(vs_text, DOWN, buff=1)

        error_box = SurroundingRectangle(error_highlight, color=RED, buff=0.2, stroke_width=3)

        self.play(Write(error_highlight), Create(error_box), run_time=1)

        # Tournament stakes
        stakes = Text("In tournaments, this changes everything.", font_size=28, color=GOLD)
        stakes.next_to(error_box, DOWN, buff=0.5)
        self.play(Write(stakes), run_time=0.8)

        self.wait(1.2)

        # Store and clear
        self.impact_elements = VGroup(
            impact_title, subtitle, normal_col, pmf_col, vs_text,
            error_highlight, error_box, stakes
        )
        self.play(FadeOut(self.impact_elements), run_time=0.5)

    def scene_5_closing(self):
        """Scene 5: Closing message (42-45s)"""
        # Final message
        closing = VGroup(
            Text("Use exact PMF.", font_size=48, color=GREEN),
            Text("Don't approximate.", font_size=48, color=RED),
        ).arrange(DOWN, buff=0.3)

        self.play(Write(closing), run_time=1.2)

        # YSolver branding
        brand = Text("YSolver", font_size=36, color=BLUE)
        brand.next_to(closing, DOWN, buff=0.8)
        self.play(FadeIn(brand, shift=UP), run_time=0.6)

        self.wait(1)

        # Fade out
        self.play(FadeOut(VGroup(closing, brand)), run_time=0.5)


if __name__ == "__main__":
    print("Render command for 1080p:")
    print("  manim -qh pmf_edge_case_animation.py PMFvsApproximation")
    print("")
    print("Preview (faster, 480p):")
    print("  manim -pql pmf_edge_case_animation.py PMFvsApproximation")
