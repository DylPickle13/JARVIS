"""Select an optional viewer-only tmux build; never changes agent commands or PATH."""
import os

ROOT = os.path.dirname(os.path.abspath(__file__))


def executable():
    bundled = os.path.join(ROOT, 'bin', 'tmux')
    if not os.path.lexists(bundled):
        return 'tmux'  # Platforms without a scoped build retain their own tmux.
    if os.path.islink(bundled) or not os.path.isfile(bundled) or not os.access(bundled, os.X_OK):
        raise RuntimeError('Pi Desk bundled tmux is not a regular executable; reinstall the verified build.')
    return bundled


def command(socket):
    return [executable(), '-L', socket]
