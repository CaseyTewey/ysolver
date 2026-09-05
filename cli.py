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
from typing import Dict, List


FULL_MASK = (1 << 13) - 1
MAX_DISTRIBUTION_CATEGORIES = 3
SCORE_HELP = 'Locked category points plus earned Yahtzee bonuses, excluding the 35-point upper bonus'


def load_state(filepath: str) -> Dict:
    """Load game state from JSON file."""
    with open(filepath, 'r') as f:
        state = json.load(f)
    if not isinstance(state, dict):
        raise ValueError('State file must contain a JSON object')
    return state


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


def normalize_player(data, mode, name='Player'):
    """Validate the compact CLI scorecard; upper bonus stays in solver EV/PMF."""
    from ev_solver import validate_solver_state

    if not isinstance(data, dict):
        raise ValueError('Player state must be a JSON object')
    mask = data.get('mask', 0)
    if isinstance(mask, str):
        mask = parse_mask(mask)
    upper = data.get('upper', 0)
    score = data.get('score', 0)
    if type(score) is not int or score < 0:
        raise ValueError('score must be a nonnegative integer; exclude the upper bonus')
    status = data.get('yahtzee_status')
    validate_solver_state(mask, upper)
    if mode == 'joker':
        if status is None:
            if mask & (1 << 11):
                raise ValueError('yahtzee_status is required when the Yahtzee box is filled (1=scratched, 2=scored)')
            status = 0
        validate_solver_state(mask, upper, status)
    else:
        if status not in (None, 0):
            raise ValueError('yahtzee_status requires --mode joker')
    return {'score': score, 'mask': mask, 'upper': upper,
            'yahtzee_status': status, 'name': data.get('name', name)}


def player_from_args(args, suffix=''):
    return normalize_player({
        'mask': parse_mask(getattr(args, 'mask' + suffix)),
        'upper': int(getattr(args, 'upper' + suffix)),
        'score': int(getattr(args, 'score' + suffix, 0)),
        'yahtzee_status': getattr(args, 'yahtzee_status' + suffix, None),
    }, args.mode, {'_a': 'Player A', '_b': 'Player B'}.get(suffix, 'Player'))


def recommend_player(player, dice, rolls, mode):
    from ev_solver import get_recommendation, get_recommendation_joker
    if mode == 'joker':
        return get_recommendation_joker(dice, player['mask'], player['upper'], rolls, player['yahtzee_status'])
    rec = get_recommendation(dice, player['mask'], player['upper'], rolls)
    rec['mode'] = 'traditional'
    return rec


def check_distribution_size(player):
    remaining = 13 - player['mask'].bit_count()
    if remaining > MAX_DISTRIBUTION_CATEGORIES:
        raise ValueError(f'Distribution analysis supports at most {MAX_DISTRIBUTION_CATEGORIES} open categories per player; use recommend or expected-score for earlier states')


def remaining_distribution(player, mode):
    check_distribution_size(player)
    if mode == 'joker':
        from pmf_solver_joker import pmf_remaining_joker
        return pmf_remaining_joker(player['mask'], player['upper'], player['yahtzee_status'])
    from pmf_solver import pmf_remaining
    return pmf_remaining(player['mask'], player['upper'])


def assumptions(mode):
    return {'policy': 'score_optimal', 'joker_rules': mode == 'joker',
            'score_convention': 'locked score excludes upper bonus',
            'distribution_basis': 'start_of_turn'}


def analyze_match(player_a, player_b, mode):
    from bisect import bisect_left
    from pmf_solver import pmf_stats, percentile

    # Validate both before starting either potentially expensive computation.
    check_distribution_size(player_a)
    check_distribution_size(player_b)
    pmfs = [remaining_distribution(p, mode) for p in (player_a, player_b)]
    finals = [{s + p['score']: prob for s, prob in pmf.items()}
              for p, pmf in zip((player_a, player_b), pmfs)]
    b_scores = sorted(finals[1])
    prefix = [0.0]
    for score in b_scores:
        prefix.append(prefix[-1] + finals[1][score])
    win = sum(prob * prefix[bisect_left(b_scores, score)] for score, prob in finals[0].items())
    tie = sum(prob * finals[1].get(score, 0.0) for score, prob in finals[0].items())
    result = {'win_prob': win, 'tie_prob': tie, 'lose_prob': max(0.0, 1.0 - win - tie),
              'assumptions': assumptions(mode)}
    for key, player, pmf in zip(('player_a', 'player_b'), (player_a, player_b), pmfs):
        stats = pmf_stats(pmf)
        result[key] = {'name': player['name'], 'current_score': player['score'],
                       'categories_remaining': 13 - player['mask'].bit_count(),
                       'projected_final': player['score'] + stats['mean'],
                       'remaining_mean': stats['mean'], 'remaining_std': stats['std'],
                       'percentiles': {label: player['score'] + percentile(pmf, pct)
                                       for label, pct in [('10th', .1), ('25th', .25), ('50th', .5), ('75th', .75), ('90th', .9)]}}
    result['score_differential'] = player_a['score'] - player_b['score']
    result['projected_margin'] = result['player_a']['projected_final'] - result['player_b']['projected_final']
    return result


def analyze_outs(player, target, mode):
    from pmf_solver import pmf_stats, prob_at_least
    from scoring import CATEGORY_NAMES

    pmf = remaining_distribution(player, mode)
    outcomes = {}
    if player['mask'] != FULL_MASK:
        if mode == 'joker':
            from pmf_solver_joker import compute_turn_pmf_joker
            outcomes = compute_turn_pmf_joker(player['mask'], player['upper'], player['yahtzee_status'])
        else:
            from pmf_solver import compute_turn_pmf
            outcomes = compute_turn_pmf(player['mask'], player['upper'])
    turn_pmf, categories = {}, {}
    for outcome, prob in outcomes.items():
        pts, next_mask = outcome[:2]
        category = (next_mask ^ player['mask']).bit_length() - 1
        turn_pmf[pts] = turn_pmf.get(pts, 0.0) + prob
        categories[category] = categories.get(category, 0.0) + prob
    return {'needed_to_reach_target': target - player['score'],
            'prob_reach_target': prob_at_least(pmf, target - player['score']),
            'remaining_score_stats': pmf_stats(pmf), 'turn_score_stats': pmf_stats(turn_pmf),
            'turn_thresholds': [{'threshold': t, 'probability': prob_at_least(turn_pmf, t)}
                                for t in (10, 20, 30, 40, 50, 100, 125, 150)
                                if prob_at_least(turn_pmf, t) > .001],
            'category_probs': [{'category': cat, 'name': CATEGORY_NAMES[cat], 'probability': prob}
                               for cat, prob in sorted(categories.items(), key=lambda x: -x[1])],
            'assumptions': assumptions(mode)}


def format_recommendation(rec: Dict) -> str:
    """Format recommendation as readable output."""
    lines = []
    lines.append("=" * 60)
    lines.append("RECOMMENDATION")
    lines.append("=" * 60)

    lines.append(f"\nCurrent dice: {rec['dice']}")
    lines.append(f"Rolls remaining: {rec['rolls_remaining']}")

    if rec['action'] == 'keep':
        lines.append(f"\nOptimal action: KEEP {rec['keep_dice']}")
        remaining = list(rec['dice'])
        for die in rec['keep_dice']:
            remaining.remove(die)
        lines.append(f"  (Reroll: {remaining})")
        lines.append(f"\nExpected value from here: {rec['expected_value']:.2f}")
    else:
        lines.append(f"\nOptimal action: SCORE in {rec['category_name']}")
        lines.append(f"  Points: {rec['points']}")
        if rec.get('joker_bonus'):
            lines.append(f"  Yahtzee bonus: +{rec['joker_bonus']}")
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
    dice = parse_dice(args.dice)
    player = player_from_args(args)
    rec = recommend_player(player, dice, int(args.rolls), args.mode)

    if args.json:
        print(json.dumps(rec, indent=2))
    else:
        print(format_recommendation(rec))


def cmd_match(args):
    """Handle match command."""
    from match import format_match_report
    state_a = normalize_player(load_state(args.state_a), args.mode, 'Player A') if args.state_a else player_from_args(args, '_a')
    state_b = normalize_player(load_state(args.state_b), args.mode, 'Player B') if args.state_b else player_from_args(args, '_b')
    analysis = analyze_match(state_a, state_b, args.mode)

    if args.json:
        print(json.dumps(analysis, indent=2))
    else:
        print(format_match_report(analysis))


def cmd_outs(args):
    """Handle outs command."""
    outs = analyze_outs(player_from_args(args), int(args.target), args.mode)

    if args.json:
        print(json.dumps(outs, indent=2))
    else:
        print(format_outs(outs))


def cmd_expected_score(args):
    """Handle expected-score command."""
    from ev_solver import get_expected_score_fresh_game, get_expected_score_fresh_game_joker
    ev = get_expected_score_fresh_game_joker() if args.mode == 'joker' else get_expected_score_fresh_game()

    if args.json:
        print(json.dumps({"expected_score": ev, "mode": args.mode, "policy": "score_optimal"}))
    else:
        print(f"\nExpected score from fresh game ({args.mode}): {ev:.2f}")
        print("(Under optimal score-maximizing play)")


def cmd_solve(args):
    """Analyze a state, with bounded distributions and explicit conditioning."""
    from ev_solver import ev_remaining, ev_remaining_joker
    from pmf_solver import pmf_stats

    state = load_state(args.state)
    mode = args.mode or state.get('mode', 'joker')
    if mode not in ('joker', 'traditional'):
        raise ValueError('mode must be joker or traditional')
    player = normalize_player(state.get('current_player', state), mode, 'You')
    opponent = normalize_player(state['opponent'], mode, 'Opponent') if 'opponent' in state else None
    result = {'assumptions': assumptions(mode), 'mode': mode}

    if 'dice' in state:
        rolls = state.get('rolls_remaining', 2)
        rec = recommend_player(player, state['dice'], rolls, mode)
        result['recommended_action'] = {
            'action': rec['action'], 'stage': f'roll{3 - rolls}',
            'keep': rec.get('keep_dice'), 'keep_counts': rec.get('keep_counts'),
            'category': rec.get('category_name'), 'points': rec.get('points'),
            'joker_bonus': rec.get('joker_bonus', 0),
            'expected_value': rec['expected_value']
        }
        result['category_options'] = rec['category_options']
        result['assumptions']['distribution_basis'] = 'start_of_turn; supplied dice affect recommendation only'

    ev = (ev_remaining_joker(player['mask'], player['upper'], player['yahtzee_status'])
          if mode == 'joker' else ev_remaining(player['mask'], player['upper']))
    result['score_projection'] = {'current': player['score'], 'expected_remaining': ev,
                                  'expected_final': player['score'] + ev,
                                  'basis': 'start_of_turn'}
    if any(13 - p['mask'].bit_count() > MAX_DISTRIBUTION_CATEGORIES
           for p in (player, opponent) if p is not None):
        result['distribution_unavailable'] = f'Distributions require at most {MAX_DISTRIBUTION_CATEGORIES} open categories per player'
    elif opponent:
        analysis = analyze_match(player, opponent, mode)
        result.update({key: analysis[key] for key in ('win_prob', 'tie_prob', 'lose_prob')})
        target = int(analysis['player_b']['projected_final']) + 1
        outs = analyze_outs(player, target, mode)
        result['outs'] = {
            'target_basis': 'one point above opponent expected final score',
            'target_final_score': target, 'prob_reach_target': outs['prob_reach_target'],
            'this_turn': outs['turn_thresholds'], 'category_probs': outs['category_probs']
        }
    else:
        stats = pmf_stats(remaining_distribution(player, mode))
        result['score_projection']['std_dev'] = stats['std']
    print(json.dumps(result, indent=2))


def cmd_interactive(args):
    """Run an interactive recommendation session in the selected rules mode."""
    from ev_solver import ev_remaining, ev_remaining_joker

    print(f'YAHTZEE SOLVER — {args.mode} (maximizes expected score)')
    print('roll <dice> | state <mask> <upper> [rolls] [yahtzee_status] | ev | quit')
    print('For match analysis, use the match subcommand with explicit player states.')
    player = normalize_player({}, args.mode)
    rolls = 2
    while True:
        try:
            line = input('\n> ').strip()
        except EOFError:
            break
        parts = line.split()
        if not parts:
            continue
        command = parts[0].lower()
        if command in ('quit', 'exit', 'q'):
            break
        try:
            if command == 'roll' and len(parts) >= 2:
                print(format_recommendation(recommend_player(player, parse_dice(''.join(parts[1:])), rolls, args.mode)))
            elif command == 'state' and 3 <= len(parts) <= 5:
                next_rolls = int(parts[3]) if len(parts) > 3 else 2
                if next_rolls not in (0, 1, 2):
                    raise ValueError('rolls must be 0, 1, or 2')
                next_player = normalize_player({'mask': parse_mask(parts[1]), 'upper': int(parts[2]),
                                                'yahtzee_status': int(parts[4]) if len(parts) > 4 else None}, args.mode)
                player, rolls = next_player, next_rolls
                print(f"State set: mask={player['mask']}, upper={player['upper']}, rolls={rolls}, yahtzee_status={player['yahtzee_status']}")
            elif command == 'ev':
                ev = (ev_remaining_joker(player['mask'], player['upper'], player['yahtzee_status'])
                      if args.mode == 'joker' else ev_remaining(player['mask'], player['upper']))
                print(f'Expected remaining score (including deferred upper bonus): {ev:.2f}')
            else:
                print('Unknown command. Use roll, state, ev, or quit.')
        except (ValueError, TypeError, KeyError, RuntimeError) as error:
            print(f'Error: {error}')


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Yahtzee expected-score solver; match probabilities assume score-optimal play',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Get recommendation for a roll
  python cli.py recommend --dice 1,1,3,5,6 --mask 0 --upper 0 --rolls 2

  # Analyze a match state from JSON
  python cli.py solve --state game.json

  # Compare two players
  python cli.py match --mode traditional --score-a 100 --mask-a 8191 \\
                      --score-b 90 --mask-b 8191

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
    p_match.add_argument('--score-a', default='0', help=SCORE_HELP)
    p_match.add_argument('--mask-a', default='0', help='Player A filled categories')
    p_match.add_argument('--upper-a', default='0', help='Player A upper subtotal')
    p_match.add_argument('--score-b', default='0', help=SCORE_HELP)
    p_match.add_argument('--mask-b', default='0', help='Player B filled categories')
    p_match.add_argument('--upper-b', default='0', help='Player B upper subtotal')
    p_match.add_argument('--json', action='store_true', help='Output as JSON')

    # Outs subcommand
    p_outs = subparsers.add_parser('outs', help='Analyze outs to reach target score')
    p_outs.add_argument('--mask', default='0', help='Filled categories bitmask')
    p_outs.add_argument('--upper', default='0', help='Upper section subtotal')
    p_outs.add_argument('--score', default='0', help=SCORE_HELP)
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

    for command_parser in (p_rec, p_match, p_outs, p_ev, p_solve, p_int):
        command_parser.add_argument('--mode', choices=('joker', 'traditional'),
                                    default=None if command_parser is p_solve else 'joker',
                                    help='Rules (default: joker; solve also accepts mode in its state file)')
    for command_parser in (p_rec, p_outs):
        command_parser.add_argument('--yahtzee-status', type=int, choices=(0, 1, 2),
                                    help='0=unfilled, 1=scratched, 2=scored 50; required if filled in joker mode')
    for suffix in ('a', 'b'):
        p_match.add_argument(f'--yahtzee-status-{suffix}', type=int, choices=(0, 1, 2),
                             help='Yahtzee status: 0=unfilled, 1=scratched, 2=scored 50')

    args = parser.parse_args(argv)
    handlers = {'recommend': cmd_recommend, 'match': cmd_match, 'outs': cmd_outs,
                'expected-score': cmd_expected_score, 'solve': cmd_solve,
                'interactive': cmd_interactive}
    if args.command in handlers:
        try:
            handlers[args.command](args)
        except (ValueError, TypeError, KeyError, OSError, RuntimeError) as error:
            parser.error(str(error))
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
