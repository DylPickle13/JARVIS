#!/usr/bin/env python3
"""Verify staged custom principals and record exact local build inputs/artifact."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent
UPSTREAM = ROOT / 'upstream'


def digest(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    staging = UPSTREAM / 'pkgroot'
    principals = sorted(staging.rglob('*.app'))
    cli = staging / 'Library/Application Support/org.pqrs/Karabiner-Elements/bin/karabiner_cli'
    principals.append(cli)
    if len(principals) < 10 or not cli.exists():
        raise SystemExit('Complete package staging is missing')
    teams = set()
    signatures = {}
    for path in principals:
        subprocess.run(['codesign', '--verify', '--deep', '--strict', str(path)], check=True)
        info = subprocess.run(['codesign', '-dv', str(path)], check=True, capture_output=True, text=True).stderr
        match = re.search(r'^TeamIdentifier=(.+)$', info, re.M)
        if not match or match[1] == 'not set':
            raise SystemExit(f'Missing real signer: {path}')
        teams.add(match[1])
        signatures[str(path.relative_to(staging))] = match[1]
    if len(teams) != 1:
        raise SystemExit('Mixed signing teams in custom applications/CLI')
    dmg = UPSTREAM / 'Karabiner-Elements-16.3.0.dmg'
    inputs = sorted((ROOT / 'patches').glob('*.patch')) + sorted((ROOT / 'prototype').glob('*.hpp'))
    for header in (ROOT / 'prototype').glob('*.hpp'):
        copied = UPSTREAM / 'src/share/jarvis_ak820' / header.name
        if not copied.exists() or digest(header) != digest(copied):
            raise SystemExit(f'Source overlay changed; rebuild before verification: {header.name}')
    manifest = dict(upstream=json.loads((ROOT / 'upstream.lock.json').read_text()),
                    input_sha256={str(p.relative_to(ROOT)): digest(p) for p in inputs},
                    staged_signatures=signatures, artifact=str(dmg), sha256=digest(dmg),
                    installed=False, hardware_validated=False)
    with tempfile.TemporaryDirectory(prefix='jarvis-karabiner-verify-') as directory:
        mount = Path(directory) / 'mount'
        subprocess.run(['hdiutil', 'attach', '-readonly', '-nobrowse', '-mountpoint', str(mount), str(dmg)],
                       check=True, capture_output=True)
        try:
            check = subprocess.run(['pkgutil', '--check-signature', str(mount / 'Karabiner-Elements.pkg')],
                                   capture_output=True, text=True)
            manifest['installer_signature_verified'] = check.returncode == 0
            manifest['installer_signature_report'] = check.stdout.strip()
        finally:
            subprocess.run(['hdiutil', 'detach', str(mount)], check=True, capture_output=True)
    output = ROOT / 'build/manifest.json'
    output.write_text(json.dumps(manifest, indent=2) + '\n')
    print(f'Verified {len(principals)} staged principals with one signing team.')
    print(f'Artifact SHA256: {manifest["sha256"]}')
    print(f'Manifest: {output}')
    if not manifest['installer_signature_verified']:
        raise SystemExit('BLOCKED: installer signature is missing/unverified. No automatic installation permitted.')


if __name__ == '__main__':
    main()
