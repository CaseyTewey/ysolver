#!/usr/bin/env python3
"""
Command-line interface for the Yahtzee solver.

Usage:
    python cli.py solve --state state.json
    python cli.py recommend --dice 1,1,3,5,6 --mask 0 --upper 0 --rolls 2
    python cli.py match --state-a state_a.json --state-b state_b.json
    python cli.py expected-score
"""

import argparse
import json
import sys
from typing import Dict, List, Optional


def load_state(filepath: str) -> Dict:
    """Load game state from JSON file."""
    with open(filepath, 'r') as f:
        return json.load(f)


def parse_dice(dice_str: str) -> List[int]:
    """Parse comma-separated dice values."""
    return [int(d.strip()) for d in dice_str.split(',')]


def parse_mask(mask_input: str) -> int:
    """Parse mask from int, hex, or binary string."""
    mask_input = mask_input.strip()
    if mask_input.startswith('0b'):
        return int(mask_input, 2)
    elif mask_input.startswith('0x'):
        return int(mask_input, 16)
    else:
        return int(mask_input)


def format_recommendation(rec: Dict) -> str:
    """Format recommendation as readable output."""
    from scoring import CATEGORY_NAMES
    from dice import counts_to_dice_list

    lines = []
    lines.append("=" * 60)
    lines.append("RECOMMENDATION")
    lines.append("=" * 60)

    lines.append(f"\nCurrent dice: {rec['dice']}")
    lines.append(f"Rolls remaining: {rec['rolls_remaining']}")

    if rec['action'] == 'keep':
        lines.append(f"\nOptimal action: KEEP {rec['keep_dice']}")
        lines.append(f"  (Reroll: {[d for d in rec['dice'] if d not in rec['keep_dice'] or rec['keep_dice'].count(d) < rec['dice'].count(d)]})")
        lines.append(f"\nExpected value from here: {rec['expected_value']:.2f}")
    else:
        lines.append(f"\nOptimal action: SCORE in {rec['category_name']}")
        lines.append(f"  Points: {rec['points']}")
        lines.append(f"  Expected remaining value: {rec['expected_value']:.2f}")

    lines.append(f"\nAll category options (if scoring now):")
    for opt in rec['category_options'][:8]:
        lines.append(f"  {opt['name']:20s}: {opt['points']:3d} pts, EV = {opt['expected_value']:.2f}")

    lines.append("=" * 60)
    return "\n".join(lines)


def format_outs(outs: Dict) -> str:
    """Format outs analysis as readable output."""
    lines = []
    lines.append("=" * 60)
    lines.append("OUTS ANALYSIS")
    lines.append("=" * 60)

    lines.append(f"\nNeeded to reach target: {outs['needed_to_reach_target']}")
    lines.append(f"Probability of reaching target: {outs['prob_reach_target']*100:.1f}%")

    stats = outs['remaining_score_stats']
    lines.append(f"\nRemaining score distribution:")
    lines.append(f"  Expected: {stats['mean']:.0f}")
    lines.append(f"  Std dev:  {stats['std']:.0f}")
    lines.append(f"  Range:    {stats['min']} - {stats['max']}")

    if outs['turn_thresholds']:
        lines.append(f"\nThis turn probabilities:")
        for t in outs['turn_thresholds']:
            lines.append(f"  Score >= {t['threshold']:2d}: {t['probability']*100:.1f}%")

    if outs['category_probs']:
        lines.append(f"\nCategory hit probabilities (this turn):")
        for c in outs['category_probs'][:5]:
            lines.append(f"  {c['name']:20s}: {c['probability']*100:.1f}%")

    lines.append("=" * 60)
    return "\n".join(lines)


def cmd_recommend(args):
    """Handle recommend command."""
    from ev_solver import get_recommendation, warm_cache

    print("Loading solver...", file=sys.stderr)
    warm_cache(verbose=False)

    dice = parse_dice(args.dice)
    mask = parse_mask(args.mask)
    upper = int(args.upper)
    rolls = int(args.rolls)

    rec = get_recommendation(dice, mask, upper, rolls)

    if args.json:
        print(json.dumps(rec, indent=2))
    else:
        print(format_recommendation(rec))


def cmd_match(args):
    """Handle match command."""
    from match import (
        PlayerState, MatchState, get_match_analysis, format_match_report
    )
    from ev_solver import warm_cache

    print("Loading solver...", file=sys.stderr)
    warm_cache(verbose=False)

    if args.state_a:
        state_a_data = load_state(args.state_a)
        state_a = PlayerState(
            score=state_a_data['score'],
            mask=state_a_data['mask'],
            upper=state_a_data['upper'],
            name=state_a_data.get('name', 'Player A')
        )
    else:
        state_a = PlayerState(
            score=int(args.score_a),
            mask=parse_mask(args.mask_a),
            upper=int(args.upper_a),
            name='Player A'
        )

    if args.state_b:
        state_b_data = load_state(args.state_b)
        state_b = PlayerState(
            score=state_b_data['score'],
            mask=state_b_data['mask'],
            upper=state_b_data['upper'],
            name=state_b_data.get('name', 'Player B')
        )
    else:
        state_b = PlayerState(
            score=int(args.score_b),
            mask=parse_mask(args.mask_b),
            upper=int(args.upper_b),
            name='Player B'
        )

    match = MatchState(player_a=state_a, player_b=state_b)
    analysis = get_match_analysis(match)

    if args.json:
        print(json.dumps(analysis, indent=2))
    else:
        print(format_match_report(analysis))


def cmd_outs(args):
    """Handle outs command."""
    from pmf_solver import get_outs_analysis
    from ev_solver import warm_cache

    print("Loading solver...", file=sys.stderr)
    warm_cache(verbose=False)

    mask = parse_mask(args.mask)
    upper = int(args.upper)
    current_score = int(args.score)
    target = int(args.target)

    outs = get_outs_analysis(mask, upper, current_score, target)

    if args.json:
        print(json.dumps(outs, indent=2))
    else:
        print(format_outs(outs))


def cmd_expected_score(args):
    """Handle expected-score command."""
    from ev_solver import warm_cache, get_expected_score_fresh_game

    print("Loading solver...", file=sys.stderr)
    warm_cache(verbose=False)

    ev = get_expected_score_fresh_game()

    if args.json:
        print(json.dumps({"expected_score": ev}))
    else:
        print(f"\nExpected score from fresh game: {ev:.2f}")
        print("(Under optimal score-maximizing play)")


def cmd_solve(args):
    """Handle solve command - comprehensive analysis from JSON state."""
    from ev_solver import get_recommendation, warm_cache
    from pmf_solver import get_outs_analysis, pmf_remaining, pmf_stats
    from match import PlayerState, MatchState, get_match_analysis
    from scoring import CATEGORY_NAMES

    print("Loading solver...", file=sys.stderr)
    warm_cache(verbose=False)

    state = load_state(args.state)

    result = {
        "assumptions": {
            "policy": "score_optimal",
            "joker_rules": False
        }
    }

    # Current player's state
    player = state.get('current_player', state)
    mask = player['mask']
    upper = player['upper']
    score = player.get('score', 0)

    # If mid-turn with dice
    if 'dice' in state:
        dice = state['dice']
        rolls_remaining = state.get('rolls_remaining', 2)
        rec = get_recommendation(dice, mask, upper, rolls_remaining)
        result['recommended_action'] = {
            'stage': f"roll{3 - rolls_remaining}",
            'keep': rec.get('keep_dice'),
            'keep_counts': rec.get('keep_counts'),
            'category': rec.get('category_name'),
            'points': rec.get('points'),
            'expected_value': rec['expected_value']
        }
        result['category_options'] = rec['category_options']

    # Win probability if opponent state provided
    if 'opponent' in state:
        opp = state['opponent']
        state_a = PlayerState(score=score, mask=mask, upper=upper, name="You")
        state_b = PlayerState(
            score=opp.get('score', 0),
            mask=opp['mask'],
            upper=opp['upper'],
            name="Opponent"
        )
        match = MatchState(player_a=state_a, player_b=state_b)
        analysis = get_match_analysis(match)

        result['win_prob'] = analysis['win_prob']
        result['tie_prob'] = analysis['tie_prob']
        result['lose_prob'] = analysis['lose_prob']

        # Outs vs opponent's expected score
        opp_expected = opp.get('score', 0) + analysis['player_b']['remaining_mean']
        target = int(opp_expected) + 1
        outs = get_outs_analysis(mask, upper, score, target)
        result['outs'] = {
            'need_to_win': {
                'target_final_score': target,
                'prob_reach_target': outs['prob_reach_target']
            },
            'this_turn': outs['turn_thresholds'],
            'category_probs': outs['category_probs']
        }
    else:
        # Single player - just provide distribution stats
        pmf = pmf_remaining(mask, upper)
        stats = pmf_stats(pmf)
        result['score_projection'] = {
            'current': score,
            'expected_remaining': stats['mean'],
            'expected_final': score + stats['mean'],
            'std_dev': stats['std']
        }

    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print(json.dumps(result, indent=2, default=str))


def cmd_interactive(args):
    """Run interactive mode for exploring the solver."""
    from ev_solver import warm_cache, get_recommendation
    from match import win_probs
    from scoring import CATEGORY_NAMES

    print("Loading solver...")
    warm_cache(verbose=True)

    print("\n" + "=" * 60)
    print("YAHTZEE SOLVER - Interactive Mode")
    print("=" * 60)
    print("\nCommands:")
    print("  roll <dice>          - Get recommendation (e.g., 'roll 1,1,3,5,6')")
    print("  state <mask> <upper> - Set current state")
    print("  match <scoreA> <maskA> <upperA> <scoreB> <maskB> <upperB>")
    print("  ev                   - Show expected remaining value")
    print("  quit                 - Exit")

    mask = 0
    upper = 0
    rolls_remaining = 2

    while True:
        try:
            line = input("\n> ").strip()
        except EOFError:
            break

        if not line:
            continue

        parts = line.split()
        cmd = parts[0].lower()

        if cmd in ('quit', 'exit', 'q'):
            break

        elif cmd == 'roll' and len(parts) >= 2:
            try:
                dice = parse_dice(' '.join(parts[1:]))
                rec = get_recommendation(dice, mask, upper, rolls_remaining)
                print(format_recommendation(rec))
            except Exception as e:
                print(f"Error: {e}")

        elif cmd == 'state' and len(parts) >= 3:
            try:
                mask = parse_mask(parts[1])
                upper = int(parts[2])
                rolls_remaining = int(parts[3]) if len(parts) > 3 else 2
                print(f"State set: mask={mask} ({bin(mask)}), upper={upper}, rolls={rolls_remaining}")
            except Exception as e:
                print(f"Error: {e}")

        elif cmd == 'match' and len(parts) >= 7:
            try:
                probs = win_probs(
                    int(parts[1]), parse_mask(parts[2]), int(parts[3]),
                    int(parts[4]), parse_mask(parts[5]), int(parts[6])
                )
                print(f"Win:  {probs['win_prob']*100:.1f}%")
                print(f"Tie:  {probs['tie_prob']*100:.1f}%")
                print(f"Lose: {probs['lose_prob']*100:.1f}%")
            except Exception as e:
                print(f"Error: {e}")

        elif cmd == 'ev':
            from ev_solver import ev_remaining
            ev = ev_remaining(mask, upper)
            print(f"Expected remaining score: {ev:.2f}")

        else:
            print("Unknown command. Type 'quit' to exit.")


def main():
    parser = argparse.ArgumentParser(
        description='Yahtzee win-probability solver',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Get recommendation for a roll
  python cli.py recommend --dice 1,1,3,5,6 --mask 0 --upper 0 --rolls 2

  # Analyze a match state from JSON
  python cli.py solve --state game.json

  # Compare two players
  python cli.py match --score-a 100 --mask-a 0b111 --upper-a 15 \\
                      --score-b 90 --mask-b 0b110 --upper-b 12

  # Get expected score for fresh game
  python cli.py expected-score

  # Interactive mode
  python cli.py interactive
"""
    )

    subparsers = parser.add_subparsers(dest='command', help='Available commands')

    # Recommend subcommand
    p_rec = subparsers.add_parser('recommend', help='Get recommendation for current dice')
    p_rec.add_argument('--dice', required=True, help='Dice values (comma-separated, e.g., 1,1,3,5,6)')
    p_rec.add_argument('--mask', default='0', help='Filled categories bitmask')
    p_rec.add_argument('--upper', default='0', help='Upper section subtotal')
    p_rec.add_argument('--rolls', default='2', help='Rolls remaining (2, 1, or 0)')
    p_rec.add_argument('--json', action='store_true', help='Output as JSON')

    # Match subcommand
    p_match = subparsers.add_parser('match', help='Analyze two-player match')
    p_match.add_argument('--state-a', help='Player A state JSON file')
    p_match.add_argument('--state-b', help='Player B state JSON file')
    p_match.add_argument('--score-a', default='0', help='Player A current score')
    p_match.add_argument('--mask-a', default='0', help='Player A filled categories')
    p_match.add_argument('--upper-a', default='0', help='Player A upper subtotal')
    p_match.add_argument('--score-b', default='0', help='Player B current score')
    p_match.add_argument('--mask-b', default='0', help='Player B filled categories')
    p_match.add_argument('--upper-b', default='0', help='Player B upper subtotal')
    p_match.add_argument('--json', action='store_true', help='Output as JSON')

    # Outs subcommand
    p_outs = subparsers.add_parser('outs', help='Analyze outs to reach target score')
    p_outs.add_argument('--mask', default='0', help='Filled categories bitmask')
    p_outs.add_argument('--upper', default='0', help='Upper section subtotal')
    p_outs.add_argument('--score', default='0', help='Current locked score')
    p_outs.add_argument('--target', required=True, help='Target score to reach')
    p_outs.add_argument('--json', action='store_true', help='Output as JSON')

    # Expected score subcommand
    p_ev = subparsers.add_parser('expected-score', help='Get expected score from fresh game')
    p_ev.add_argument('--json', action='store_true', help='Output as JSON')

    # Solve subcommand (comprehensive)
    p_solve = subparsers.add_parser('solve', help='Comprehensive analysis from state file')
    p_solve.add_argument('--state', required=True, help='Game state JSON file')
    p_solve.add_argument('--json', action='store_true', help='Output as JSON (default)')

    # Interactive subcommand
    p_int = subparsers.add_parser('interactive', help='Run interactive mode')

    args = parser.parse_args()

    if args.command == 'recommend':
        cmd_recommend(args)
    elif args.command == 'match':
        cmd_match(args)
    elif args.command == 'outs':
        cmd_outs(args)
    elif args.command == 'expected-score':
        cmd_expected_score(args)
    elif args.command == 'solve':
        cmd_solve(args)
    elif args.command == 'interactive':
        cmd_interactive(args)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
