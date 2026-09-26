#!/usr/bin/env python3
"""Owner-only opt-in after manually configuring macOS login security."""
import argparse
import os

import cycle
import watch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--enable', action='store_true')
    mode.add_argument('--disable', action='store_true')
    parser.add_argument('--confirm-password-and-immediate-lock', action='store_true',
                        help='Confirm password set, automatic login off, immediate password requirement, and inactivity lock configured')
    args = parser.parse_args()
    if args.enable and not args.confirm_password_and_immediate_lock:
        parser.error('Configure and manually test macOS lock security first; explicit confirmation required.')
    os.umask(0o077)
    store = cycle.Store(cycle.RUNTIME)
    with watch.locked(store, 'cycle.lock'):
        state = store.load('display-state.json', display_initial())
        if args.enable and state != display_initial():
            # Never silently clear an uncertain write or trust old transition state.
            parser.error('Existing display state requires owner review before re-enabling.')
        store.save('display-config.json', {'enabled': args.enable})
    print('Display automation enabled.' if args.enable else 'Display automation disabled; no lock, wake or security setting changed.')


def display_initial():
    import display_cycle
    return display_cycle.initial()


if __name__ == '__main__':
    main()
