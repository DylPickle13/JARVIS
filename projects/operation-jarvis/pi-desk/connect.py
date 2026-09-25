#!/usr/bin/env python3
"""Reconnect a display client, never restart a hosted agent."""
import signal
import subprocess
import sys
import time

from backend import clean_environment, load


def main(number):
    command = load().attachment(number)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    try:
        while True:
            child = subprocess.Popen(command, env=clean_environment())
            try:
                child.wait()
            finally:
                if child.poll() is None:
                    child.terminate()
                    try:
                        child.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.wait()
            print(f'\nConnection closed. Reconnecting session {number} in 3 seconds…', flush=True)
            time.sleep(3)
    except KeyboardInterrupt:
        return 0


if __name__ == '__main__':
    raise SystemExit(main(int(sys.argv[1])))
