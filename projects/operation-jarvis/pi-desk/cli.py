#!/usr/bin/env python3
"""The same terminal entry point on macOS and Linux."""
import argparse
import subprocess
import sys

from backend import clean_environment, load


def restart(dry_run=False):
    backend = load()
    if not dry_run:
        print('Start/restart all ten agents on mac-mini-64. Existing conversations are preserved.')
        print('Busy, stale or ambiguous sessions block the operation. Missing slots start fresh.')
        print('This affects every viewer. Partial failures are NOT automatically retried.')
        try:
            confirmed = sys.stdin.isatty() and input('Press Enter to start/restart all ten agents (Ctrl+C to cancel): ') == ''
        except (EOFError, KeyboardInterrupt):
            confirmed = False
        if not confirmed:
            print('Cancelled; no agents changed.')
            return 1
    result = subprocess.run(backend.restart(dry_run), env=clean_environment())
    if result.returncode:
        print('Start/restart did not complete. Review the result before trying again.')
    if sys.stdin.isatty():
        input('Press Enter to return to Pi Desk…')
    return result.returncode


def main():
    parser = argparse.ArgumentParser(description='Pi Desk — ten shared Mac-hosted Pi sessions')
    parser.add_argument('action', choices=('open', 'restart'), nargs='?', default='open')
    parser.add_argument('--dry-run', action='store_true', help='restart preflight only; no changes')
    args = parser.parse_args()
    if args.dry_run and args.action != 'restart':
        parser.error('--dry-run requires restart')
    if args.action == 'restart':
        return restart(args.dry_run)
    if not sys.stdin.isatty():
        parser.error('open Pi Desk in an interactive terminal')
    from desktop import main as display
    try:
        return display()
    except RuntimeError as exc:
        print(f'Pi Desk: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyboardInterrupt) as exc:
        print(f'Pi Desk: {exc or "cancelled"}', file=sys.stderr)
        raise SystemExit(1)
