"""Bounded, credential-free Codex quota projection and terminal presentation."""
import datetime as dt
import math

FRESH_SECONDS = 900  # Match jarvisd's quota cache, not the 12s session watchdog.
UNAVAILABLE = {'status': 'unavailable'}


def timestamp(value):
    if not isinstance(value, str) or len(value) > 64:
        return None
    try:
        date = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
        if date.tzinfo is None or not 1970 <= date.year <= 2100:
            return None
        return date.astimezone(dt.timezone.utc)
    except (ValueError, OverflowError):
        return None


def iso(date):
    return date.isoformat().replace('+00:00', 'Z') if date is not None else None


def number(value, maximum):
    if type(value) not in (int, float):
        return None
    try:
        return value if math.isfinite(value) and 0 <= value <= maximum else None
    except OverflowError:
        return None


def window(value, checked):
    if not isinstance(value, dict):
        return {'remainingPercent': None, 'resetAt': None}
    reset = timestamp(value.get('resetAt'))
    if reset is None and checked is not None:
        seconds = number(value.get('resetAfterSeconds'), 366 * 86400)
        if seconds is not None:
            reset = checked + dt.timedelta(seconds=seconds)
    return {'remainingPercent': number(value.get('remainingPercent'), 100),
            'resetAt': iso(reset)}


def normalize(value, now=None):
    """Validate the additive wire field; repeated reads cannot renew freshness."""
    if not isinstance(value, dict) or value.get('status') not in ('live', 'stale'):
        return dict(UNAVAILABLE)
    now = now or dt.datetime.now(dt.timezone.utc)
    checked = timestamp(value.get('checkedAt'))
    weekly = window(value.get('weekly'), checked)
    five_hour = window(value.get('fiveHour'), checked)
    enforced = value.get('fiveHourEnforced')
    enforced = enforced if type(enforced) is bool else None
    if weekly['remainingPercent'] is None and (five_hour['remainingPercent'] is None or enforced is False):
        return dict(UNAVAILABLE)
    age = (now - checked).total_seconds() if checked is not None else None
    status = value['status']
    if age is None or age < -5 or age > FRESH_SECONDS:
        status = 'stale'
    return {'status': status, 'checkedAt': iso(checked),
            'weekly': weekly, 'fiveHour': five_hour,
            'fiveHourEnforced': enforced,
            'limitReached': value.get('limitReached') is True}


def project(value, now=None):
    """Whitelist only quota data from jarvisd; never forward errors/account data."""
    if not isinstance(value, dict) or value.get('ok') is not True or value.get('available') is not True:
        return dict(UNAVAILABLE)
    return normalize({
        'status': 'live' if value.get('stale') is False and not value.get('lastError') else 'stale',
        'checkedAt': value.get('checkedAt') or value.get('updatedAt'),
        'weekly': value.get('weekly'), 'fiveHour': value.get('fiveHour'),
        'fiveHourEnforced': value.get('fiveHourEnforced'),
        'limitReached': value.get('limitReached'),
    }, now)


def percent(value):
    if value is None:
        return 'n/a'
    # Only actual exhaustion/full capacity should be displayed as 0%/100%.
    rounded = max(1, min(99, int(value + .5))) if 0 < value < 100 else int(value)
    return f'{rounded}%'


def labels(value, now=None):
    """Longest-first footer choices, with explicit remaining semantics."""
    quota = normalize(value, now)
    if quota['status'] != 'live':
        return (f" Codex {quota['status']} ",)
    weekly = quota['weekly']['remainingPercent']
    five = ('paused' if quota['fiveHourEnforced'] is False else
            percent(quota['fiveHour']['remainingPercent']))
    compact = (f' Codex W:{percent(weekly)} left ' if weekly is not None else
               f' Codex 5h:{five} left ')
    return (f' Codex W:{percent(weekly)} · 5h:{five} left ', compact)


def color(value, now=None):
    quota = normalize(value, now)
    if quota['status'] != 'live':
        return 'colour245'
    remaining = [quota['weekly']['remainingPercent']]
    if quota['fiveHourEnforced'] is not False:
        remaining.append(quota['fiveHour']['remainingPercent'])
    minimum = min((n for n in remaining if n is not None), default=100)
    if quota['limitReached'] or minimum < 30:  # Same critical threshold as JARVIS.
        return 'colour203'
    return 'colour179' if minimum < 50 else '#D183E8'


def reset_label(value, now):
    reset = timestamp(value.get('resetAt'))
    if reset is None:
        return 'reset unavailable'
    seconds = max(0, int((reset - now).total_seconds()))
    if seconds == 0:
        return 'reset due; awaiting usage update'
    if seconds < 60:
        return 'resets in <1m'
    if seconds < 3600:
        return f'resets in {seconds // 60}m'
    if seconds < 86400:
        return f'resets in {seconds // 3600}h {(seconds % 3600) // 60}m'
    return f'resets in {seconds // 86400}d {(seconds % 86400) // 3600}h'


def details(value, now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    quota = normalize(value, now)
    if quota['status'] == 'unavailable':
        return 'Codex usage unavailable'
    if quota['status'] == 'stale':
        return 'Codex usage stale; awaiting a fresh reading'
    weekly, five = quota['weekly'], quota['fiveHour']
    fields = [f"Weekly: {percent(weekly['remainingPercent'])} left, {reset_label(weekly, now)}"]
    if quota['fiveHourEnforced'] is False:
        fields.append('5-hour: paused (not enforced)')
    elif five['remainingPercent'] is None:
        fields.append('5-hour: unavailable')
    else:
        fields.append(f"5-hour: {percent(five['remainingPercent'])} left, {reset_label(five, now)}")
    if quota['limitReached']:
        fields.append('limit reached')
    return 'Codex — ' + ' · '.join(fields)
