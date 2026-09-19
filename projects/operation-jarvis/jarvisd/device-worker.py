#!/usr/bin/env python3
"""Private, local device worker. No HTTP listener or public CLI dependency."""
from jarvisd_core.device_worker import main

if __name__ == "__main__":
    raise SystemExit(main())
