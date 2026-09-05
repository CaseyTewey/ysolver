"""Validated scorecards and score accounting at the HTTP boundary.

The DP includes the upper bonus at its terminal state. A displayed current
score already includes that bonus, so subtract it from the DP's remaining EV.
"""

from dataclasses import dataclass


class InvalidState(ValueError):
    pass


def integer(value, field, minimum, maximum):
    if type(value) is not int or not minimum <= value <= maximum:
        raise InvalidState(f'{field} must be an integer from {minimum} to {maximum}')
    return value


def validate_dice(value):
    if not isinstance(value, list) or len(value) != 5:
        raise InvalidState('dice must contain exactly five integers from 1 to 6')
    for face in value:
        integer(face, 'dice values', 1, 6)
    return value


@dataclass(frozen=True)
class Scorecard:
    scores: dict
    mask: int
    upper: int
    yahtzee_status: int
    yahtzee_bonuses: int

    @property
    def remaining(self):
        return 13 - self.mask.bit_count()

    @property
    def unfilled(self):
        return {cat for cat in range(13) if not self.mask & (1 << cat)}

    @property
    def upper_bonus(self):
        return 35 if self.upper >= 63 else 0

    @property
    def locked(self):
        """Score offset for DP/PMF: category scores and earned Yahtzee bonuses."""
        return sum(v for v in self.scores.values() if v is not None) + self.yahtzee_bonuses * 100

    @property
    def current_total(self):
        return self.locked + self.upper_bonus


def parse_scorecard(data, prefix=''):
    field = prefix + 'scores'
    scores = data.get(field, {})
    if not isinstance(scores, dict):
        raise InvalidState(f'{field} must be an object keyed by category numbers 0 through 12')
    mask = upper = 0
    for key, value in scores.items():
        if key not in {str(i) for i in range(13)}:
            raise InvalidState(f'{field} has an invalid category: {key}')
        if value is None:
            continue
        cat = int(key)
        maximum = (cat + 1) * 5 if cat < 6 else {8:25, 9:30, 10:40, 11:50}.get(cat, 30)
        integer(value, f'{field}.{key}', 0, maximum)
        if cat < 6 and value % (cat + 1):
            raise InvalidState(f'{field}.{key} must be a multiple of {cat + 1}')
        if cat in (8, 9, 10, 11) and value not in (0, maximum):
            raise InvalidState(f'{field}.{key} must be 0 or {maximum}')
        if cat in (6, 7, 12) and 0 < value < 5:
            raise InvalidState(f'{field}.{key} must be 0 or between 5 and 30')
        mask |= 1 << cat
        if cat < 6:
            upper += value
    derived_status = 0 if scores.get('11') is None else (2 if scores['11'] == 50 else 1)
    status_field = prefix + 'yahtzee_status'
    status = integer(data.get(status_field, derived_status), status_field, 0, 2)
    if status != derived_status:
        raise InvalidState(f'{status_field} conflicts with the Yahtzee score (category 11)')
    bonus_field = prefix + 'yahtzee_bonuses'
    bonuses = integer(data.get(bonus_field, 0), bonus_field, 0, 12)
    if bonuses and (status != 2 or bonuses > mask.bit_count() - 1):
        raise InvalidState(f'{bonus_field} requires a scored Yahtzee and enough completed turns')
    return Scorecard(dict(scores), mask, upper, status, bonuses)
