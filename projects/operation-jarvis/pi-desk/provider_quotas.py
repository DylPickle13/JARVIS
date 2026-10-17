"""Compact, credential-free Codex + Claude labels. No network calls."""
import datetime as dt

import codex_quota as base

PROVIDERS = (('codexQuota', 'Codex', 'Cx'), ('claudeQuota', 'Claude', 'Cl'))


def is_bundle(value):
    return isinstance(value, dict) and any(key in value for key, _, _ in PROVIDERS)


def normalize(value, now=None):
    value = value if isinstance(value, dict) else {}
    return {key: base.normalize(value.get(key), now) for key, _, _ in PROVIDERS}


def countdown(value, now):
    date = base.timestamp(value.get('resetAt'))
    if date is None:
        return '?'
    seconds = max(0, int((date - now).total_seconds()))
    if seconds == 0:
        return 'due'
    if seconds < 60:
        return '<1m'
    if seconds < 3600:
        return f'{seconds // 60}m'
    if seconds < 86400:
        return f'{seconds // 3600}h'
    return f'{seconds // 86400}d'


def provider_segments(key, name, value, now):
    quota = base.normalize(value.get(key), now)
    if quota['status'] != 'live':
        return ((name + ' ' + quota['status'], base.GREY),)
    segments = [(name + ' W:', base.GREY)]
    for index, window in enumerate(('weekly', 'fiveHour')):
        if index:
            segments.append((' 5h:', base.GREY))
        sample = quota[window]
        remaining = sample['remainingPercent']
        segments.extend(((base.percent(remaining), base.color(remaining)),
                         ('↻' + countdown(sample, now), base.GREY)))
        if index and quota['fiveHourEnforced'] is False:
            segments.append(('p', base.GREY))  # Tracking only: enforcement paused.
    return tuple(segments)


def label_segments(value, now=None):
    if not is_bundle(value):
        return base.label_segments(value, now)  # Compatibility with older viewers/tests.
    now = now or dt.datetime.now(dt.timezone.utc)
    choices = []
    for abbreviated in (False, True):
        segments = []
        for key, name, short in PROVIDERS:
            if segments:
                segments.append((' · ', base.GREY))
            segments.extend(provider_segments(key, short if abbreviated else name, value, now))
        choices.append(tuple(segments))
    return tuple(choices)


def markup(segments):
    # Only allowlisted labels, finite numbers, and validated dates enter tmux.
    return ('#[align=left,norange,fg=' + base.GREY + ',bg=#1e1e1e,nobold,nounderscore]'
            + ''.join('#[fg=' + color + ']' + text.replace('%', '%%') for text, color in segments))


def status_rows(value, width, now=None):
    """Extra row(s) when the tab row cannot fit both complete quota labels."""
    now = now or dt.datetime.now(dt.timezone.utc)
    for segments in label_segments(value, now):
        if sum(len(text) for text, _ in segments) <= width:
            return (markup(segments),)
    rows = []
    for key, name, short in PROVIDERS:
        segments = provider_segments(key, name, value, now)
        if sum(len(text) for text, _ in segments) > width:
            segments = provider_segments(key, short, value, now)
        # Terminals smaller than a single provider label are physically unable
        # to show every field. Clip safely; never overflow into session controls.
        bounded = []
        remaining = max(0, width)
        for text, color in segments:
            bounded.append((text[:remaining], color))
            remaining = max(0, remaining - len(text))
        rows.append(markup(bounded))
    return tuple(rows)


def details(value, now=None):
    if not is_bundle(value):
        return base.details(value, now)
    return ' · '.join(base.details(value.get(key), now).replace('Codex', name)
                      for key, name, _ in PROVIDERS)
