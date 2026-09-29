#!/usr/bin/env python3
"""Build a signed API-23 APK without Gradle or third-party app libraries.
Requires official Android SDK build-tools 35 + platform 23 and JDK 17.
APK contains no credentials; provision separately over USB. Keep keys private.
"""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parent


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--sdk', type=Path, required=True)
    p.add_argument('--java-home', type=Path, required=True)
    p.add_argument('--private-dir', type=Path, required=True)
    args = p.parse_args()
    os.umask(0o077)
    private = args.private_dir.resolve()
    # Private state must never accidentally be created inside the source tree.
    if ROOT == private or ROOT in private.parents:
        raise SystemExit('Private directory must be outside the project.')
    out = private / 'build'
    if out.exists(): shutil.rmtree(out)
    for sub in ('gen', 'classes', 'dex'):
        (out / sub).mkdir(parents=True, exist_ok=True)
    tools = args.sdk / 'android-15'
    android = args.sdk / 'android-6.0/android.jar'
    env = dict(os.environ, JAVA_HOME=str(args.java_home), PATH=str(args.java_home / 'bin') + ':' + os.environ['PATH'])
    def run(*cmd): subprocess.run([str(x) for x in cmd], env=env, check=True)
    for executable in ('aapt', 'd8', 'zipalign', 'apksigner'):
        (tools / executable).chmod(0o755)
    run(tools / 'aapt', 'package', '-f', '-M', ROOT / 'android/AndroidManifest.xml',
        '-S', ROOT / 'android/res', '-I', android,
        '-J', out / 'gen', '-F', out / 'resources.apk')
    sources = sorted((ROOT / 'android/src').rglob('*.java')) + sorted((out / 'gen').rglob('*.java'))
    run(args.java_home / 'bin/javac', '-source', '8', '-target', '8', '-bootclasspath', android,
        '-d', out / 'classes', *sources)
    run(tools / 'd8', '--min-api', '23', '--lib', android, '--output', out / 'dex',
        *sorted((out / 'classes').rglob('*.class')))
    shutil.copyfile(out / 'resources.apk', out / 'unaligned.apk')
    with zipfile.ZipFile(out / 'unaligned.apk', 'a') as apk:
        apk.write(out / 'dex/classes.dex', 'classes.dex')
    run(tools / 'zipalign', '-f', '4', out / 'unaligned.apk', out / 'aligned.apk')
    run(tools / 'apksigner', 'sign', '--ks', private / 'signing.p12',
        '--ks-pass', 'file:' + str(private / 'signing-password'), '--v1-signing-enabled', 'true',
        '--out', private / 'jarvis-monitor.apk', out / 'aligned.apk')
    run(tools / 'apksigner', 'verify', '--verbose', private / 'jarvis-monitor.apk')
    print('Signed credential-free APK ready. Install, then run provision_phone.py over USB.')


if __name__ == '__main__': main()
