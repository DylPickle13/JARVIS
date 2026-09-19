#!/usr/bin/env python3
"""Explicit write-closed recovery entry. No v2 activation or vendor rollback."""
from pathlib import Path


def main():
    import jarvisd
    from jarvisd_core.control_closed import load_pins, run_closed
    # Deployment supplies independently reviewed staged SDK pins. Never generate
    # or refresh these from whatever happens to be installed at startup.
    pins = load_pins(Path(__file__).resolve().parent / 'closed-vendor-pins.json')
    return run_closed(jarvisd, pins=pins)


if __name__ == '__main__':
    raise SystemExit(main())
