#!/usr/bin/env python3
"""Stage a fresh macOS ARP-helper install. Never elevates, installs or stops the Pi.

Private input JSON: INTERFACE, PHONE_IP, PHONE_MAC, DOORBELL_IP, DOORBELL_MAC.
Run the generated install.sh explicitly with sudo after reviewing the manifest.
A durable root-owned attempt marker prevents automatic installation/bootstrap replay.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import shlex
import stat
import subprocess
import sys

from arp_repair import Peer

ROOT = Path(__file__).resolve().parent
LABEL = 'com.jarvis.monitor-arp'
BINARY = Path('/Library/PrivilegedHelperTools') / LABEL
PLIST = Path('/Library/LaunchDaemons') / (LABEL + '.plist')
MARKER = Path('/var/db') / (LABEL + '.install-attempted')
LOG = Path('/var/log/jarvis-monitor-arp.log')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def arguments(config):
    if set(config) != {'INTERFACE', 'PHONE_IP', 'PHONE_MAC', 'DOORBELL_IP', 'DOORBELL_MAC'}:
        raise ValueError('exact five-field configuration required')
    if any(type(x) is not str for x in config.values()):
        raise ValueError('string fields required')
    if not re.fullmatch(r'[a-zA-Z0-9_.-]{1,15}', config['INTERFACE']):
        raise ValueError('invalid interface')
    phone = Peer.parse(config['PHONE_IP'], config['PHONE_MAC'])
    bell = Peer.parse(config['DOORBELL_IP'], config['DOORBELL_MAC'])
    if phone.ip == bell.ip or phone.mac == bell.mac:
        raise ValueError('distinct identities required')
    if bytes.fromhex('020000000000') in (phone.mac, bell.mac):
        raise ValueError('privacy placeholder is not a peer identity')
    return [config['INTERFACE'], str(phone.ip), phone.mac.hex(':'), str(bell.ip), bell.mac.hex(':')]


def service(args):
    return {'Label': LABEL, 'ProgramArguments': [str(BINARY), '--run', *args],
            'RunAtLoad': True, 'KeepAlive': True, 'ThrottleInterval': 60,
            'ProcessType': 'Background', 'Umask': 0o077,
            'StandardOutPath': str(LOG), 'StandardErrorPath': str(LOG),
            'WorkingDirectory': '/'}


def installer(stage, binary_sha, plist_sha, manifest_sha):
    q = shlex.quote
    # All substituted paths are shell-quoted; service paths are fixed, not inputs.
    return f'''#!/bin/sh
set -eu
umask 077
export PATH=/usr/bin:/bin:/usr/sbin:/sbin
[ "$(/usr/bin/id -u)" = 0 ] || {{ echo 'Run this installer with sudo in Terminal.' >&2; exit 77; }}
stage={q(str(stage))}
# Source and copied bytes must match the reviewed build; no compiling as root.
verify() {{
  actual=$(/usr/bin/shasum -a 256 "$1")
  [ "${{actual%% *}}" = "$2" ] || {{ echo 'Hash mismatch; stopped.' >&2; exit 65; }}
}}
verify "$stage/arp-repair-macos" {q(binary_sha)}
verify "$stage/{LABEL}.plist" {q(plist_sha)}
verify "$stage/manifest.json" {q(manifest_sha)}
/usr/bin/plutil -lint "$stage/{LABEL}.plist"
# This installer is fresh-install-only. Never overwrite or replay an unknown result.
for p in {q(str(BINARY))} {q(str(PLIST))} {q(str(MARKER))} {q(str(LOG))}; do
  [ ! -e "$p" ] && [ ! -L "$p" ] || {{ echo 'Existing installation or attempt: inspect before proceeding.' >&2; exit 73; }}
done
if /bin/launchctl print system/{LABEL} >/dev/null 2>&1; then
  echo 'Service already loaded; inspect instead of retrying.' >&2; exit 73
fi
# Reject unsafe destination parents rather than changing existing permissions.
for p in /Library /Library/PrivilegedHelperTools /Library/LaunchDaemons /var/db /var/log; do
  [ -d "$p" ] && [ ! -L "$p" ] || {{ echo 'Missing or symlink destination parent.' >&2; exit 73; }}
  [ "$(/usr/bin/stat -f %u "$p")" = 0 ] || exit 73
  mode=$(/usr/bin/stat -f %Lp "$p")
  [ "$((0$mode & 0022))" = 0 ] || {{ echo 'Writable destination parent.' >&2; exit 73; }}
done
/bin/mkdir -m 700 {q(str(MARKER))}
/usr/bin/install -o root -g wheel -m 600 "$stage/manifest.json" {q(str(MARKER / 'manifest.json'))}
/usr/bin/install -o root -g wheel -m 555 "$stage/arp-repair-macos" {q(str(BINARY))}
/usr/bin/install -o root -g wheel -m 644 "$stage/{LABEL}.plist" {q(str(PLIST))}
verify {q(str(BINARY))} {q(binary_sha)}
verify {q(str(PLIST))} {q(plist_sha)}
# Only sanitized status/counters enter this log; no addresses, frames or credentials.
(set -C; : > {q(str(LOG))})
/usr/sbin/chown root:wheel {q(str(LOG))}
/bin/chmod 644 {q(str(LOG))}
: > {q(str(MARKER / 'bootstrap.attempted'))}
/bin/launchctl bootstrap system {q(str(PLIST))}
echo 'Mac helper bootstrap dispatched once. Pi helper untouched. Live verification required.'
/bin/launchctl print system/{LABEL}
'''


def replacement_installer(stage, binary_sha, plist_sha, manifest_sha, old_sha):
    q = shlex.quote
    marker = Path('/var/db') / (LABEL + '.replace-' + binary_sha[:16] + '.attempted')
    temporary = str(BINARY) + '.' + binary_sha[:16] + '.new'
    return f'''#!/bin/sh
set -eu
umask 077
export PATH=/usr/bin:/bin:/usr/sbin:/sbin
[ "$(/usr/bin/id -u)" = 0 ] || {{ echo 'Run this replacement with sudo in Terminal.' >&2; exit 77; }}
stage={q(str(stage))}
verify() {{
  actual=$(/usr/bin/shasum -a 256 "$1")
  [ "${{actual%% *}}" = "$2" ] || {{ echo 'Hash mismatch; stopped without replay.' >&2; exit 65; }}
}}
verify "$stage/arp-repair-macos" {q(binary_sha)}
verify "$stage/manifest.json" {q(manifest_sha)}
verify {q(str(BINARY))} {q(old_sha)}
verify {q(str(PLIST))} {q(plist_sha)}
for p in /Library /Library/PrivilegedHelperTools /Library/LaunchDaemons /var/db /var/log; do
  [ -d "$p" ] && [ ! -L "$p" ] || exit 73
  [ "$(/usr/bin/stat -f %u "$p")" = 0 ] || exit 73
  mode=$(/usr/bin/stat -f %Lp "$p")
  [ "$((0$mode & 0022))" = 0 ] || exit 73
done
for p in {q(str(BINARY))} {q(str(PLIST))} {q(str(LOG))}; do
  [ -f "$p" ] && [ ! -L "$p" ] || exit 73
  [ "$(/usr/bin/stat -f %u "$p")" = 0 ] || exit 73
  [ "$(/usr/bin/stat -f %l "$p")" = 1 ] || exit 73
  mode=$(/usr/bin/stat -f %Lp "$p")
  [ "$((0$mode & 0022))" = 0 ] || exit 73
done
for p in {q(str(marker))} {q(temporary)}; do
  [ ! -e "$p" ] && [ ! -L "$p" ] || {{ echo 'Existing replacement attempt: inspect, do not replay.' >&2; exit 73; }}
done
/bin/launchctl print system/{LABEL} >/dev/null
/bin/mkdir -m 700 {q(str(marker))}
/usr/bin/install -o root -g wheel -m 600 "$stage/manifest.json" {q(str(marker / 'manifest.json'))}
/usr/bin/install -o root -g wheel -m 500 {q(str(BINARY))} {q(str(marker / 'binary.before'))}
/usr/bin/install -o root -g wheel -m 600 {q(str(PLIST))} {q(str(marker / 'plist.before'))}
verify {q(str(marker / 'binary.before'))} {q(old_sha)}
: > {q(str(marker / 'bootout.attempted'))}
/bin/launchctl bootout system/{LABEL}
# Stop only this helper and prove it has exited before replacing its binary.
i=0
while /usr/bin/pgrep -f '^/Library/PrivilegedHelperTools/com[.]jarvis[.]monitor-arp( |$)' >/dev/null; do
  i=$((i+1)); [ "$i" -le 10 ] || {{ echo 'Helper still running; stopped for inspection.' >&2; exit 75; }}
  /bin/sleep 1
done
if /bin/launchctl print system/{LABEL} >/dev/null 2>&1; then exit 75; fi
verify {q(str(BINARY))} {q(old_sha)}
verify {q(str(PLIST))} {q(plist_sha)}
/usr/bin/install -o root -g wheel -m 555 "$stage/arp-repair-macos" {q(temporary)}
verify {q(temporary)} {q(binary_sha)}
/bin/mv -f {q(temporary)} {q(str(BINARY))}
verify {q(str(BINARY))} {q(binary_sha)}
: > {q(str(marker / 'replacement.installed'))}
: > {q(str(marker / 'bootstrap.attempted'))}
/bin/launchctl bootstrap system {q(str(PLIST))}
echo 'Replacement dispatched once. Plist and Pi helper unchanged. Live verification required.'
/bin/launchctl print system/{LABEL}
'''


def build(config, output, replace_existing_sha256=None):
    if sys.platform != 'darwin':
        raise ValueError('macOS build host required')
    args = arguments(config)
    if replace_existing_sha256 is not None:
        if not re.fullmatch('[0-9a-f]{64}', replace_existing_sha256):
            raise ValueError('exact existing binary SHA256 required')
        for installed in (BINARY, PLIST):
            info = installed.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
                raise ValueError('unsafe installed file')
        if digest(BINARY) != replace_existing_sha256:
            raise ValueError('installed binary differs from reviewed replacement target')
    output = output.expanduser().absolute()
    output.mkdir(mode=0o700, parents=False, exist_ok=False)
    os.chmod(output, 0o700)
    binary = output / 'arp-repair-macos'
    subprocess.run(['xcrun', 'clang', '-std=c11', '-Wall', '-Wextra', '-Werror', '-O2',
                    str(ROOT / 'arp_repair_macos.c'), '-lpcap', '-o', str(binary)], check=True)
    os.chmod(binary, 0o700)
    # No BPF access, packets, device controls or privilege prompts in --check.
    subprocess.run([str(binary), '--check', *args], check=True)
    plist = output / (LABEL + '.plist')
    plist.write_bytes(plistlib.dumps(service(args), sort_keys=True))
    subprocess.run(['/usr/bin/plutil', '-lint', str(plist)], check=True)
    if replace_existing_sha256 is not None and digest(PLIST) != digest(plist):
        raise ValueError('replacement must preserve the installed service configuration exactly')
    manifest = {'phase': 'staged_not_installed', 'label': LABEL, 'config': config,
                'sourceSHA256': {name: digest(ROOT / name) for name in
                                 ('arp_repair_macos.c', 'arp_protocol.h', 'build_macos_arp.py')},
                'binarySHA256': digest(binary), 'plistSHA256': digest(plist),
                'piServiceChanged': False, 'livePacketTestPerformed': False,
                'credentialsIncluded': False,
                'privilegeModel': 'root opens BPF then permanently drops to nobody'}
    if replace_existing_sha256 is not None:
        manifest.update(phase='replacement_staged_not_installed', replacesExistingSHA256=replace_existing_sha256)
    path = output / 'manifest.json'
    path.write_text(json.dumps(manifest, indent=2) + '\n')
    script = output / ('replace.sh' if replace_existing_sha256 else 'install.sh')
    if replace_existing_sha256:
        script.write_text(replacement_installer(output, digest(binary), digest(plist), digest(path), replace_existing_sha256))
    else:
        script.write_text(installer(output, digest(binary), digest(plist), digest(path)))
    script.chmod(0o700)
    subprocess.run(['/bin/sh', '-n', str(script)], check=True)
    print(json.dumps({'phase': manifest['phase'], 'directory': str(output),
                      'next': 'sudo ' + shlex.quote(str(script))}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--replace-existing-sha256', help='Reviewed installed binary hash; preserve the service plist exactly')
    opts = parser.parse_args()
    build(json.loads(opts.config.read_text()), opts.output, opts.replace_existing_sha256)
