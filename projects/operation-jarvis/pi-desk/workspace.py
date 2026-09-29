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
    commands = []

    def add(*args):
        if commands:
            commands.append(';')
        commands.extend(args)

    created = False
    for n in wanted:
        if n not in slots:
            pane = core.tmux('new-window', '-d', '-t', name + ':', '-P', '-F', '#{pane_id}',
                             core.connection_command(n)).stdout.strip()
            core.tmux('set-option', '-p', '-t', pane, '@pi-desk-session', str(n))
            slots[n] = [pane, '-1', '0', str(n), '0']
            created = True
        elif slots[n][4] == '1':
            add('respawn-pane', '-t', slots[n][0], core.connection_command(n))
        add('select-pane', '-t', slots[n][0], '-T', f'Session {n}')

    # New windows may have reused index 0 when recovering a deleted display.
    if created:
        rows = panes(name)
        slots = {int(row[3]): row for row in rows if row[3].isdigit()}
    selected = slots[number][0]
    visible = [row[0] for row in sorted(rows, key=lambda row: int(row[2]))
               if row[1] == '0']
    # Plan against the snapshot, retaining an anchor even for disjoint groups.
    # Stable pane IDs and explicit join targets let us track order without
    # querying tmux between mutations (which would expose partial layouts).
    if not visible:
        window = slots[number][1]
        add('move-window', '-s', f'{name}:{window}', '-t', target)
        visible = [row[0] for row in sorted(rows, key=lambda row: int(row[2]))
                   if row[1] == window]
    elif selected not in visible:
        anchor = visible[0]
        add('swap-pane', '-d', '-s', selected, '-t', anchor)
        visible[0] = selected
    wanted_panes = [slots[n][0] for n in wanted]
    for pane in visible[:]:
        if pane not in wanted_panes:
            add('break-pane', '-d', '-s', pane, '-t', name + ':')
            visible.remove(pane)
    for pane in wanted_panes:
        if pane not in visible:
            # Append after a known pane, not the window's changing active pane.
            add('join-pane', '-d', '-h', '-s', pane, '-t', visible[-1])
            visible.append(pane)
    for i, pane in enumerate(wanted_panes):
        index = visible.index(pane)
        if index != i:
            add('swap-pane', '-d', '-s', pane, '-t', visible[i])
            visible[i], visible[index] = visible[index], visible[i]
    # One mutation queue and one final equalization. This reduces redraws but
    # is not a transaction: tmux can still deliver queued resize notifications.
    add('select-layout', '-t', target, 'even-horizontal')
    add('select-window', '-t', target)
    add('select-pane', '-t', selected)
    add('set-option', '-t', name, '@pi-desk-capacity', str(count))
    add('set-option', '-t', name, '@pi-desk-first', str(wanted[0]))
    add('set-option', '-t', name, '@pi-desk-end', str(wanted[-1]))
    add('set-option', '-t', name, '@pi-desk-shape', shape(wanted))
    add('set-option', '-t', name, '@pi-desk-width', str(width))
    add('set-option', '-t', name, '@pi-desk-changing', '0')
    core.tmux(*commands)
    return number
