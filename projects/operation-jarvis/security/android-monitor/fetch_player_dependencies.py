#!/usr/bin/env python3
"""Fetch checksum-locked viewer dependencies and compile platform, outside source."""
import argparse
import hashlib
import json
from pathlib import Path
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sdk', type=Path, required=True)
    args = parser.parse_args()
    sdk = args.sdk.resolve()
    if sdk == ROOT or ROOT in sdk.parents:
        raise SystemExit('SDK/cache must be outside the source tree.')
    cache = sdk / 'player-deps'
    cache.mkdir(parents=True, exist_ok=True)
    for item in json.loads((ROOT / 'player-dependencies.json').read_text()):
        if Path(item['name']).name != item['name']:
            raise SystemExit('Invalid dependency path.')
        path = cache / item['name']
        if not path.exists():
            with urllib.request.urlopen(item['url'], timeout=90) as response:
                data = response.read()
            if hashlib.sha256(data).hexdigest() != item['sha256']:
                raise SystemExit('Dependency checksum mismatch; nothing installed.')
            path.write_bytes(data)
        if hashlib.sha256(path.read_bytes()).hexdigest() != item['sha256']:
            raise SystemExit('Cached dependency checksum mismatch; refusing reuse.')
        if item['type'] == 'platform':
            target = sdk / 'android-33'
            target.mkdir(exist_ok=True)
            with zipfile.ZipFile(path) as archive:
                (target / 'android.jar').write_bytes(archive.read(item['member']))
    print('Viewer dependencies verified; no runtime configuration accessed.')


if __name__ == '__main__':
    main()
