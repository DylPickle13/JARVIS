#!/usr/bin/env python3
"""Synthetic-only DSP/ExoPlayer tests on the handset CPU, before installing the candidate APK.

No camera, playback, microphone, screen, volume or network operations. Temporary
credential-free candidate APK/test JAR are deleted afterwards. Never clears app data.
"""
import argparse
from pathlib import Path
import os
import subprocess
import tempfile
import zipfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial', required=True)
    parser.add_argument('--sdk', type=Path, required=True)
    parser.add_argument('--private-dir', type=Path, required=True)
    parser.add_argument('--java-home', type=Path, required=True)
    parser.add_argument('--confirm-synthetic-cpu-test', action='store_true')
    args = parser.parse_args()
    if ':' in args.serial or not args.confirm_synthetic_cpu_test:
        parser.error('USB serial and explicit synthetic CPU test confirmation required.')
    build = args.private_dir / 'build'
    env = dict(os.environ, JAVA_HOME=str(args.java_home),
               PATH=str(args.java_home / 'bin') + ':' + os.environ['PATH'])

    def run(*command):
        return subprocess.check_output(list(map(str, command)), env=env, text=True, timeout=90)

    adb = ['adb', '-s', args.serial]
    with tempfile.TemporaryDirectory(prefix='jarvis-voice-test-') as directory:
        out = Path(directory)
        classes, dex = out/'classes', out/'dex'
        classes.mkdir(); dex.mkdir()
        jars = list((build/'deps').rglob('*.jar')) + list((args.sdk/'player-deps').glob('*.jar'))
        classpath = os.pathsep.join(map(str, [build/'classes'] + jars))
        run(args.java_home/'bin/javac', '-source', '8', '-target', '8',
            '-bootclasspath', build/'android.jar', '-classpath', classpath,
            '-d', classes, Path(__file__).with_name('VoiceFocusTest.java'),
            Path(__file__).with_name('VoiceFocusProcessorTest.java'))
        run(args.sdk/'android-15/d8', '--min-api', '23', '--lib', build/'android.jar',
            '--classpath', build/'classes', *sum((['--classpath', jar] for jar in jars), []),
            '--output', dex, *classes.rglob('*.class'))
        archive = out/'test.jar'
        with zipfile.ZipFile(archive, 'w') as z:
            z.write(dex/'classes.dex', 'classes.dex')
        remote = '/data/local/tmp/' + out.name
        try:
            run(*adb, 'shell', 'mkdir', '-p', remote+'/oat/arm')
            run(*adb, 'push', args.private_dir/'jarvis-monitor.apk', remote+'/candidate.apk')
            run(*adb, 'push', archive, remote+'/test.jar')
            # app_process otherwise interprets the uninstalled APK on Android 6 (no JIT),
            # grossly overstating DSP cost. Precompile our private temporary copy only.
            run(*adb, 'shell', 'dex2oat', '--dex-file='+remote+'/candidate.apk',
                '--oat-file='+remote+'/oat/arm/candidate.odex', '--instruction-set=arm', '--compiler-filter=speed')
            run(*adb, 'shell', 'dex2oat', '--dex-file='+remote+'/test.jar',
                '--oat-file='+remote+'/oat/arm/test.odex', '--instruction-set=arm', '--compiler-filter=speed')
            for test, marker in [('VoiceFocusTest', 'voice DSP assertions passed.'),
                                 ('VoiceFocusProcessorTest', 'on-device voice processor assertions passed.')]:
                result = run(*adb, 'shell', 'CLASSPATH='+remote+'/candidate.apk:'+remote+'/test.jar', 'app_process', '/system/bin', test)
                print(result.strip())  # Synthetic harness only; no camera/config inputs.
                if marker not in result:
                    raise RuntimeError('Synthetic on-device regression failed; candidate must not be installed.')
        finally:
            run(*adb, 'shell', 'rm', '-rf', remote)  # Exactly our uniquely named temporary test directory.


if __name__ == '__main__':
    main()
