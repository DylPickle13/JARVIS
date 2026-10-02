"""Host audio-consent regressions; device tests verify wiring and actual rendering."""
from pathlib import Path
import os
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ListenAudioTests(unittest.TestCase):
    def test_consent_policy(self):
        home = Path(os.environ.get('JAVA_HOME', '/opt/homebrew/opt/openjdk@17'))
        javac = str(home / 'bin/javac') if (home / 'bin/javac').is_file() else shutil.which('javac')
        java = str(home / 'bin/java') if (home / 'bin/java').is_file() else shutil.which('java')
        if not javac or not java:
            self.skipTest('JDK required for audio-consent tests')
        with tempfile.TemporaryDirectory(prefix='jarvis-audio-policy-') as directory:
            subprocess.run([javac, '-d', directory,
                            str(ROOT / 'android/src/local/jarvis/monitor/ListenAudioPolicy.java'),
                            str(ROOT / 'tests/ListenAudioPolicyTest.java')],
                           check=True, capture_output=True, timeout=30)
            result = subprocess.run([java, '-cp', directory, 'ListenAudioPolicyTest'],
                                    check=True, capture_output=True, text=True, timeout=10)
            self.assertIn('listen-audio assertions passed.', result.stdout)

    def test_volume_zero_before_prepare_and_no_persisted_consent(self):
        source = (ROOT / 'android/src/local/jarvis/monitor/ViewerActivity.java').read_text()
        opening = source.split('private void open() {', 1)[1].split('private void failed()', 1)[0]
        self.assertLess(opening.index('player.setVolume(0f)'), opening.index('player.prepare()'))
        # Filter preference may persist; listening/mute/focus permission must not.
        self.assertEqual(re.findall(r'\.(?:get|put)(?:Boolean|Int|String|Long|Float)\("([^"]+)"', source),
                         ['voice-focus', 'voice-focus', 'host', 'path', 'username', 'password', 'port', 'version'])
        policy = (ROOT / 'android/src/local/jarvis/monitor/ListenAudioPolicy.java').read_text()
        self.assertNotIn('SharedPreferences', policy)
        self.assertNotIn('setStreamVolume', source)
        self.assertNotIn('setSpeakerphoneOn', source)
        self.assertIn('AudioManager.ACTION_AUDIO_BECOMING_NOISY', source)
        self.assertIn('Intent.ACTION_SCREEN_OFF', source)
        self.assertIn('silenceAudio(); audio.closed();', source)
        self.assertIn('audioDisabled = false; audio.reset();', source)
        self.assertIn('else if (audio.autoRequested()) startAudio(false);', source)
        self.assertIn('audioManager.abandonAudioFocus(focusListener)', source)

    def test_update_keeps_enable_pending_and_presence_gates(self):
        source = (ROOT / 'android/src/local/jarvis/monitor/Boot.java').read_text()
        self.assertIn('Intent.ACTION_MY_PACKAGE_REPLACED.equals(action)', source)
        self.assertIn('if (!boot && !power && !updated) return;', source)
        self.assertIn('p.getBoolean("enabled", false) && !p.getBoolean("pending", false)', source)
        self.assertIn('if (boot) p.edit().remove("applied").commit();', source)
        self.assertNotIn('putBoolean', source)
        manifest = (ROOT / 'android/AndroidManifest.xml').read_text()
        self.assertIn('android.intent.action.MY_PACKAGE_REPLACED', manifest)

    def test_audio_failure_uses_bounded_video_fallback(self):
        source = (ROOT / 'android/src/local/jarvis/monitor/ViewerActivity.java').read_text()
        self.assertIn('if (audioFailure(error)) audioDisabled = true;', source)
        self.assertIn('setTrackTypeDisabled(C.TRACK_TYPE_AUDIO, audioDisabled)', source)
        self.assertIn('long delay = health.retryDelay();', source)


if __name__ == '__main__':
    unittest.main()
