"""Native tmux navigation; Python runs only when a workspace needs recovery."""


def binding(direction):
    fallback = ('run-shell -b \'python3 "$HOME/.local/share/pi-desk/navigate.py" '
                + str(direction) + ' "#{client_pid}"\'')
    command = fallback
    for current in reversed(range(1, 11)):
        number = max(1, min(10, current + direction))
        key = (number - 1) // 3 + 1
        group = f'group-{key}'
        # Inspect actual live panes, not a cached readiness flag. Loop expansion
        # validates order, tags, window and liveness before taking the fast path.
        panes = ('#{S:#{W:#{P:#{?#{==:#{session_name},' + group
                 + '},#{window_index}:#{pane_index}:#{@pi-desk-session}:#{pane_dead}|,}}}}')
        expected = ''.join(f'0:{i}:{n}:0|' for i, n in enumerate(
            range((key - 1) * 3 + 1, min(key * 3, 10) + 1)))
        ready = '#{==:' + panes + ',' + expected + '}'
        fast = (f'select-pane -t {group}:0.{(number - 1) % 3} ; '
                f'switch-client -t ={group} ; set-option -g @pi-desk-last {number}')
        branch = f'if-shell -F "{ready}" {{ {fast} }} {{ {fallback} }}'
        condition = '#{==:#{@pi-desk-session},' + str(current) + '}'
        command = f'if-shell -F "{condition}" {{ {branch} }} {{ {command} }}'
    return command


def install(tmux):
    for direction, key in ((-1, 'Left'), (1, 'Right')):
        command = binding(direction)
        tmux('bind-key', '-T', 'root', 'C-' + key, command)
        for prefix_key in (key, 'C-' + key):
            tmux('bind-key', '-T', 'prefix', prefix_key, command)
