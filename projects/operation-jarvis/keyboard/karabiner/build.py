#!/usr/bin/env python3
"""Build complete custom package, without installation or launch-services cleanup."""
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent


def main():
    for key in ('PQRS_ORG_CODE_SIGN_IDENTITY', 'PQRS_ORG_INSTALLER_CODE_SIGN_IDENTITY'):
        if not os.environ.get(key):
            raise SystemExit(f'Set {key} to an authorized local signing identity SHA-1 (not its display name)')
    for helper in ('get-codesign-identity.sh', 'get-installer-codesign-identity.sh'):
        identity = subprocess.check_output(['/bin/bash', str(ROOT / 'upstream/scripts' / helper)], text=True).strip()
        if not identity:
            raise SystemExit(f'{helper} could not resolve identity; use the SHA-1 from security find-identity, not its display name')
    subprocess.run([sys.executable, str(ROOT / 'prepare.py')], check=True)
    subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-q'],
                   cwd=ROOT.parent, check=True)
    # make package additionally mutates the launch-services database. The package
    # builder itself is sufficient and does not install or restart live services.
    subprocess.run(['/bin/bash', 'make-package.sh'], cwd=ROOT / 'upstream', check=True)
    subprocess.run([sys.executable, str(ROOT / 'verify_build.py')], check=True)
    print('Package built and signatures verified. Not installed; obtain OS approvals before deployment.')


if __name__ == '__main__':
    main()
