#!/usr/bin/env python3
"""Build a signed API-23 handset APK with checksum-locked ExoPlayer dependencies.

JDK 17, platform 33 for compilation, build-tools 35; runtime min/target stay 23.
No Gradle, credentials in APK assets, dependency downloads during build, or analytics.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--sdk', type=Path, required=True)
    parser.add_argument('--java-home', type=Path, required=True)
    parser.add_argument('--private-dir', type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    private = args.private_dir.resolve()
    if ROOT == private or ROOT in private.parents:
        raise SystemExit('Private directory must be outside the project.')
    out = private / 'build'
    if out.exists():
        shutil.rmtree(out)
    for sub in ('gen', 'classes', 'dex', 'deps'):
        (out / sub).mkdir(parents=True, exist_ok=True)
    jars, resources, packages = [], [], set()
    for item in json.loads((ROOT / 'player-dependencies.json').read_text()):
        if Path(item['name']).name != item['name']:
            raise SystemExit('Invalid dependency path.')
        path = args.sdk / 'player-deps' / item['name']
        if hashlib.sha256(path.read_bytes()).hexdigest() != item['sha256']:
            raise SystemExit('Dependency checksum mismatch; refusing build.')
        if item['type'] == 'platform':
            with zipfile.ZipFile(path) as archive:
                android = out / 'android.jar'
                android.write_bytes(archive.read(item['member']))
        elif item['type'] == 'rtsp-sources':
            with zipfile.ZipFile(path) as archive:
                name = 'com/google/android/exoplayer2/source/rtsp/RtspMessageUtil.java'
                source = archive.read(name).decode()
            # ExoPlayer 2.19.1 splits DECODED authority at the first @, routing an
            # email-style username to its email domain. Preserve encoding and
            # strip user-info at the final delimiter instead. Fail on source drift.
            patches = [
                ('checkNotNull(uri.getAuthority())', 'checkNotNull(uri.getEncodedAuthority())'),
                ('Util.split(authorityWithUserInfo, "@")[1]',
                 'authorityWithUserInfo.substring(authorityWithUserInfo.lastIndexOf(\'@\') + 1)'),
            ]
            for before, after in patches:
                if source.count(before) != 1:
                    raise SystemExit('Pinned RTSP parser patch did not match uniquely.')
                source = source.replace(before, after)
            patched = out / 'gen' / name
            patched.parent.mkdir(parents=True, exist_ok=True)
            patched.write_text(source)
        elif item['type'] == 'jar':
            jars.append(path)
        else:
            target = out / 'deps' / path.stem
            with zipfile.ZipFile(path) as archive:
                for name in archive.namelist():
                    if name in ('classes.jar', 'AndroidManifest.xml') or name.startswith('res/'):
                        if '..' in Path(name).parts or name.startswith('/'):
                            raise SystemExit('Invalid dependency archive path.')
                        archive.extract(name, target)
            jar = target / 'classes.jar'
            if path.name == 'com.google.android.exoplayer.exoplayer-rtsp-2.19.1.aar':
                filtered = target / 'patched-classes.jar'
                with zipfile.ZipFile(jar) as original, zipfile.ZipFile(filtered, 'w') as modified:
                    for entry in original.infolist():
                        if not entry.filename.startswith('com/google/android/exoplayer2/source/rtsp/RtspMessageUtil'):
                            modified.writestr(entry, original.read(entry.filename))
                jar = filtered
            jars.append(jar)
            if (target / 'res').is_dir():
                resources.append(target / 'res')
            package = ET.parse(target / 'AndroidManifest.xml').getroot().get('package')
            if package:
                packages.add(package)
    tools = args.sdk / 'android-15'
    env = dict(os.environ, JAVA_HOME=str(args.java_home),
               PATH=str(args.java_home / 'bin') + ':' + os.environ['PATH'])

    def run(*command):
        subprocess.run([str(x) for x in command], env=env, check=True)

    for executable in ('aapt2', 'd8', 'zipalign', 'apksigner'):
        (tools / executable).chmod(0o755)
    compiled = []
    for index, resource in enumerate(resources + [ROOT / 'android/res']):
        target = out / ('resource-' + str(index) + '.zip')
        run(tools / 'aapt2', 'compile', '--dir', resource, '-o', target)
        compiled += ['-R', target]
    run(tools / 'aapt2', 'link', '--manifest', ROOT / 'android/AndroidManifest.xml',
        *compiled, '-I', android, '--auto-add-overlay',
        '--extra-packages', ':'.join(sorted(packages)),
        '--java', out / 'gen', '-o', out / 'resources.apk')
    sources = sorted((ROOT / 'android/src').rglob('*.java')) + sorted((out / 'gen').rglob('*.java'))
    run(args.java_home / 'bin/javac', '-source', '8', '-target', '8', '-bootclasspath', android,
        '-classpath', os.pathsep.join(map(str, jars)), '-d', out / 'classes', *sources)
    run(tools / 'd8', '--min-api', '23', '--lib', android, '--output', out / 'dex',
        *jars, *sorted((out / 'classes').rglob('*.class')))
    shutil.copyfile(out / 'resources.apk', out / 'unaligned.apk')
    with zipfile.ZipFile(out / 'unaligned.apk', 'a') as apk:
        for dex in sorted((out / 'dex').glob('*.dex')):
            apk.write(dex, dex.name)
        apk.write(ROOT / 'THIRD_PARTY.md', 'assets/THIRD_PARTY.md')
    run(tools / 'zipalign', '-f', '4', out / 'unaligned.apk', out / 'aligned.apk')
    run(tools / 'apksigner', 'sign', '--ks', private / 'signing.p12',
        '--ks-pass', 'file:' + str(private / 'signing-password'), '--v1-signing-enabled', 'true',
        '--out', private / 'jarvis-monitor.apk', out / 'aligned.apk')
    run(tools / 'apksigner', 'verify', '--verbose', private / 'jarvis-monitor.apk')
    print('Signed credential-free APK ready; existing pairing is retained by install -r.')


if __name__ == '__main__':
    main()
