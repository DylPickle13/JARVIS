#!/usr/bin/env python3
"""Read sanitized presence through the authenticated backend, never raw BLE data."""
import http.client
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "jarvisd"))
from jarvisd_core.local_control import read_token


def main():
    connection = http.client.HTTPConnection("127.0.0.1", 8790, timeout=5)
    try:
        connection.request("GET", "/api/v1/presence", headers={"Authorization": "Bearer " + read_token()})
        response = connection.getresponse()
        raw = response.read(16385)
        if response.status != 200 or len(raw) > 16384:
            raise ValueError()
        print(json.dumps(json.loads(raw)))
        return 0
    except Exception:
        print(json.dumps({"ok": False, "error": "Presence backend unavailable; location unknown."}))
        return 1
    finally:
        connection.close()


if __name__ == "__main__":
    sys.exit(main())
