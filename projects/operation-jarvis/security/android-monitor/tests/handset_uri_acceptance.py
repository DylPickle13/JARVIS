#!/usr/bin/env python3
"""Run synthetic URI tests against the installed player APK; no screen/network changes."""
import argparse
from pathlib import Path
import os
import subprocess
import tempfile
import zipfile


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--serial', required=True)
    p.add_argument('--sdk', type=Path, required=True)
    p.add_argument('--private-dir', type=Path, required=True)
    p.add_argument('--java-home', type=Path, required=True)
    args = p.parse_args()
    build = args.private_dir / 'build'
    env = dict(os.environ, JAVA_HOME=str(args.java_home),
               PATH=str(args.java_home / 'bin') + ':' + os.environ['PATH'])

    def run(*command):
        return subprocess.check_output(list(map(str, command)), env=env, text=True, timeout=30)

    adb = ['adb', '-s', args.serial]
    apk = run(*adb, 'shell', 'pm', 'path', 'local.jarvis.monitor').strip()
    if not apk.startswith('package:/data/app/') or '\n' in apk:
        raise SystemExit('Unexpected installed APK path.')
    remote = '/data/local/tmp/jarvis-player-uri-test.jar'
    with tempfile.TemporaryDirectory(prefix='jarvis-uri-test-') as directory:
        out = Path(directory)
        classes = out / 'classes'
        dex = out / 'dex'
        classes.mkdir(); dex.mkdir()
        jars = list((build / 'deps').rglob('*.jar')) + list((args.sdk / 'player-deps').glob('*.jar'))
        classpath = os.pathsep.join(map(str, [build / 'classes'] + jars))
        run(args.java_home / 'bin/javac', '-source', '8', '-target', '8',
            '-bootclasspath', build / 'android.jar', '-classpath', classpath,
            '-d', classes, Path(__file__).with_name('PlayerUriTest.java'))
        run(args.sdk / 'android-15/d8', '--min-api', '23', '--lib', build / 'android.jar',
            '--output', dex, *classes.rglob('*.class'))
        archive = out / 'test.jar'
        with zipfile.ZipFile(archive, 'w') as z:
            z.write(dex / 'classes.dex', 'classes.dex')
        try:
            run(*adb, 'push', archive, remote)
            result = run(*adb, 'shell', 'CLASSPATH=' + apk.removeprefix('package:') + ':' + remote,
                         'app_process', '/system/bin',
                         'com.google.android.exoplayer2.source.rtsp.PlayerUriTest')
            if '17 on-device RTSP URI assertions passed.' not in result:
                raise SystemExit('Installed parser regression failed; do not deploy.')
            print(result.strip())
        finally:
            run(*adb, 'shell', 'rm', '-f', remote)


if __name__ == '__main__':
    main()
