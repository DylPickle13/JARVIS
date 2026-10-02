"""Local PCM DSP and playback integration guards; acoustic quality needs owner acceptance."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'android/src/local/jarvis/monitor'


class VoiceFocusTests(unittest.TestCase):
    def test_dsp(self):
        java = Path(os.environ.get('JAVA_HOME', '/opt/homebrew/opt/openjdk@17')) / 'bin'
        with tempfile.TemporaryDirectory(prefix='jarvis-voice-test-') as out:
            subprocess.run([str(java/'javac'), '-d', out, str(SRC/'VoiceFocus.java'),
                            str(ROOT/'tests/VoiceFocusTest.java')], check=True, capture_output=True, timeout=30)
            result = subprocess.run([str(java/'java'), '-cp', out, 'VoiceFocusTest'],
                                    check=True, capture_output=True, text=True, timeout=15)
            self.assertIn('voice DSP assertions passed.', result.stdout)

    def test_bounded_local_native_rate_processing(self):
        adapter = (SRC/'VoiceFocusProcessor.java').read_text()
        self.assertIn('format.sampleRate == 8000 && format.channelCount == 1', adapter)
        self.assertIn('C.ENCODING_PCM_16BIT', adapter)
        self.assertIn('return supported ? format : AudioFormat.NOT_SET', adapter)
        self.assertIn('Math.min(2048, input.remaining()/2)', adapter)
        self.assertIn('i<VoiceFocus.SIZE', adapter)
        self.assertIn('samplesIn-samplesOut', adapter)
        self.assertIn('dsp = null; supported = false', adapter)
        self.assertIn('volatile boolean focus', adapter)
        core = (SRC/'VoiceFocus.java').read_text()
        for bad in ('new Thread', 'Socket', 'FileOutputStream', 'AudioRecord', 'MediaRecorder'):
            self.assertNotIn(bad, core+adapter)
        self.assertNotIn('new ', core.split('public boolean push(', 1)[1])
        self.assertIn('if (!focus && mix == 0) running = false', core)

    def test_toggle_keeps_mute_focus_and_transport_unchanged(self):
        source = (SRC/'ViewerActivity.java').read_text()
        toggle = source.split('voiceButton.setOnClickListener', 1)[1].split('FrameLayout.LayoutParams voiceParams', 1)[0]
        self.assertIn('!resumed || !unlocked()', toggle)
        self.assertIn('voiceProcessor.focus(voiceFocus)', toggle)
        self.assertIn('putBoolean("voice-focus", voiceFocus)', toggle)
        for bad in ('setVolume', 'startAudio(', 'open()', 'close()', 'requestAudioFocus'):
            self.assertNotIn(bad, toggle)
        self.assertIn('getBoolean("voice-focus", true)', source)
        self.assertIn('setAudioProcessors(new AudioProcessor[] { processor })', source)
        self.assertIn('setEnableFloatOutput(false)', source)
        self.assertIn('OFFLOAD_MODE_DISABLED', source)
        self.assertIn('voiceProcessor = null', source)
        self.assertIn('voiceButton.setContentDescription', source)
        self.assertNotIn('android.permission.RECORD_AUDIO', (ROOT/'android/AndroidManifest.xml').read_text())


if __name__ == '__main__':
    unittest.main()
