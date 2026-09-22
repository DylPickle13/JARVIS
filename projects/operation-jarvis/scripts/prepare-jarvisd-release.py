#!/usr/bin/env python3
"""Prepare a private, uninstalled source artifact from one committed Git tree.

Never reads runtime configuration, installs dependencies, runs launchctl, or
activates a release. Existing destinations and symlinks are refused. Tests and
cutover approval are separate gates; the manifest never claims they happened.
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile


DEPENDENCIES = '''import importlib.metadata as m, json, platform, sys
rows = []
for d in m.distributions():
    row = {'name': d.metadata.get('Name', ''), 'version': d.version}
    raw = d.read_text('direct_url.json')
    if raw:
        try:
            commit = json.loads(raw).get('vcs_info', {}).get('commit_id')
            if commit: row['vcsCommit'] = commit
        except (ValueError, TypeError): pass
    rows.append(row)
print(json.dumps({'python': platform.python_version(), 'implementation': platform.python_implementation(),
                  'dependencies': sorted(rows, key=lambda r: (r['name'], r['version']))}))
'''


def git(repository, *args):
    return subprocess.check_output(['git', '-C', str(repository), *args], stderr=subprocess.DEVNULL)


def prepare(repository, revision, destination, interpreters=()):
    repository = Path(repository).resolve(strict=True)
    destination = Path(destination).absolute()
    destination = destination.parent.resolve(strict=True) / destination.name
    if destination.exists() or destination.is_symlink() or destination.is_relative_to(repository):
        raise ValueError('Use a new artifact directory outside the checkout')
    commit = git(repository, 'rev-parse', '--verify', '--end-of-options', revision + '^{commit}').decode().strip()
    tree = git(repository, 'rev-parse', commit + '^{tree}').decode().strip()
    archive_bytes = git(repository, 'archive', '--format=tar', commit)
    with tarfile.open(fileobj=io.BytesIO(archive_bytes)) as archive:
        for entry in archive.getmembers():
            path = Path(entry.name)
            if path.is_absolute() or '..' in path.parts or not (entry.isfile() or entry.isdir()):
                raise ValueError('Only ordinary tracked source files are allowed')
            if (path.name == '.env' or path.name.startswith('.env.') and not path.name.endswith('.example')
                    or path.suffix.lower() in {'.sqlite', '.sqlite3', '.pem', '.key', '.p12', '.p8'}):
                raise ValueError('Private runtime material is not release source')
        runtime = {}
        for label, executable in interpreters:
            if not label.replace('-', '').isalnum() or label in runtime:
                raise ValueError('Unique alphanumeric interpreter labels required')
            # Metadata only, in isolated mode. Never pip install/freeze or import
            # vendor SDKs/configuration. URLs (potential credentials) are omitted.
            raw = subprocess.check_output([str(executable), '-I', '-B', '-c', DEPENDENCIES],
                                          stderr=subprocess.DEVNULL, timeout=20)
            runtime[label] = json.loads(raw)
        old_mask = os.umask(0o077)
        try:
            destination.mkdir(mode=0o700)
            source = destination / 'source'
            source.mkdir(mode=0o700)
            archive.extractall(source, filter='data')
            manifest = {'schema': 1, 'commit': commit, 'tree': tree,
                'verification': 'not_run', 'activation': 'not_performed',
                'runtimeMetadata': runtime,
                'files': {str(p.relative_to(source)): hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in sorted(source.rglob('*')) if p.is_file()}}
            (destination / 'source-manifest.json').write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')
        finally:
            os.umask(old_mask)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument('--revision', default='HEAD', help='Committed revision; working-tree edits are never included')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--python', action='append', default=[], metavar='LABEL=INTERPRETER')
    args = parser.parse_args()
    try:
        interpreters = [tuple(value.split('=', 1)) for value in args.python]
        if any(len(row) != 2 for row in interpreters):
            raise ValueError('Invalid interpreter option')
        manifest = prepare(args.repository, args.revision, args.output, interpreters)
    except Exception:
        parser.exit(1, 'Release preparation failed; artifact must not be activated. No services changed.\n')
    print(json.dumps({'commit': manifest['commit'], 'files': len(manifest['files']),
                      'verification': 'not_run', 'activation': 'not_performed'}))


if __name__ == '__main__':
    main()
