"""Viewer-private display panes. Never operates on the hosted agent socket.

Window 0 is visible. Other windows park existing attachment processes so layout
changes do not reconnect agents. Only the selected group is created eagerly.
Callers serialize reconciliation using desktop's selection lock.
"""
import re
import uuid

import core
from layout import capacity, group, shape, minimum_columns


VIEWER_NAME = re.compile(r'viewer-[0-9a-f]{32}\Z')


def is_viewer(name):
    return bool(VIEWER_NAME.fullmatch(name))


def panes(name):
    rows = core.tmux('list-panes', '-s', '-t', name, '-F',
                     '#{pane_id}\t#{window_index}\t#{pane_index}\t#{@pi-desk-session}\t#{pane_dead}').stdout
    return [row.split('\t') for row in rows.splitlines()]


def create(number, width, height):
    name = 'viewer-' + uuid.uuid4().hex
    try:
        pane = core.tmux('new-session', '-d', '-s', name, '-x', str(max(1, width)),
                         '-y', str(max(4, height)), '-P', '-F', '#{pane_id}',
                         core.connection_command(number)).stdout.strip()
        core.tmux('set-option', '-p', '-t', pane, '@pi-desk-session', str(number), ';',
                  'set-option', '-t', name, '@pi-desk-min-columns', str(minimum_columns()))
        reconcile(name, number, width, initial=True)
        return name
    except BaseException:
        destroy(name)
        raise


def destroy(name):
    if is_viewer(name):
        core.tmux('kill-session', '-t', '=' + name, check=False)


def reconcile(name, number, width, initial=False):
    """Keep focus, pane identities and attachment processes through regrouping.

    number=None preserves the live focus, read AFTER disabling native navigation.
    Publish the fast-path shape only after the entire reconciliation succeeds.
    """
    if not is_viewer(name):
        raise ValueError('Not a private Pi Desk viewer')
    target = name + ':0'
    core.tmux('set-option', '-t', name, '@pi-desk-changing', '1')
    previous = core.tmux('show-options', '-v', '-t', name,
                         '@pi-desk-capacity', check=False).stdout.strip()
    minimum = int(core.tmux('show-options', '-v', '-t', name,
                            '@pi-desk-min-columns').stdout.strip())
    count = capacity(width, int(previous) if previous and not initial else None, minimum)
    rows = panes(name)
    has_visible_window = any(row[1] == '0' for row in rows)
    if number is None:
        number = int(core.tmux('display-message', '-p', '-t', target if has_visible_window else name,
                              '#{@pi-desk-session}').stdout.strip())
    wanted = group(number, count)
    slots = {int(row[3]): row for row in rows if row[3].isdigit()}
    for n in wanted:
        if n not in slots:
            pane = core.tmux('new-window', '-d', '-t', name + ':', '-P', '-F', '#{pane_id}',
                             core.connection_command(n)).stdout.strip()
            core.tmux('set-option', '-p', '-t', pane, '@pi-desk-session', str(n))
            slots[n] = [pane, '-1', '0', str(n), '0']
        elif slots[n][4] == '1':
            core.tmux('respawn-pane', '-t', slots[n][0], core.connection_command(n))
        core.tmux('select-pane', '-t', slots[n][0], '-T', f'Session {n}')

    # New windows may have reused index 0 when recovering a deleted display.
    rows = panes(name)
    slots = {int(row[3]): row for row in rows if row[3].isdigit()}
    has_visible_window = any(row[1] == '0' for row in rows)
    # Always retain an anchor in window 0, even for disjoint navigation groups.
    selected = slots[number][0]
    if not has_visible_window:
        window = core.tmux('display-message', '-p', '-t', selected, '#{window_id}').stdout.strip()
        core.tmux('move-window', '-s', window, '-t', target)
    elif slots[number][1] != '0':
        anchor = next(row[0] for row in rows if row[1] == '0')
        core.tmux('swap-pane', '-d', '-s', selected, '-t', anchor)
    for pane, window, _, n, _ in panes(name):
        if window == '0' and int(n) not in wanted:
            core.tmux('break-pane', '-d', '-s', pane, '-t', name + ':')
    visible = {int(row[3]) for row in panes(name) if row[1] == '0'}
    for n in wanted:
        if n not in visible:
            core.tmux('join-pane', '-d', '-h', '-s', slots[n][0], '-t', target)
            core.tmux('select-layout', '-t', target, 'even-horizontal')
    for i, n in enumerate(wanted):
        pane = slots[n][0]
        index = core.tmux('display-message', '-p', '-t', pane, '#{pane_index}').stdout.strip()
        if index != str(i):
            core.tmux('swap-pane', '-d', '-s', pane, '-t', f'{target}.{i}')
    core.tmux('select-layout', '-t', target, 'even-horizontal', ';',
              'select-window', '-t', target, ';',
              'select-pane', '-t', selected, ';',
              'set-option', '-t', name, '@pi-desk-capacity', str(count), ';',
              'set-option', '-t', name, '@pi-desk-first', str(wanted[0]), ';',
              'set-option', '-t', name, '@pi-desk-end', str(wanted[-1]), ';',
              'set-option', '-t', name, '@pi-desk-shape', shape(wanted), ';',
              'set-option', '-t', name, '@pi-desk-width', str(width), ';',
              'set-option', '-t', name, '@pi-desk-changing', '0')
    return number
