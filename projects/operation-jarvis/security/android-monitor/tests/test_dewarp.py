"""Dewarp geometry and lifecycle guards; on-device visuals/performance are separate."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'android/src/local/jarvis/monitor'


class DewarpTests(unittest.TestCase):
    def test_geometry(self):
        java = Path(os.environ.get('JAVA_HOME', '/opt/homebrew/opt/openjdk@17')) / 'bin'
        with tempfile.TemporaryDirectory(prefix='jarvis-dewarp-test-') as out:
            subprocess.run([str(java/'javac'), '-d', out, str(SRC/'DewarpModel.java'),
                            str(ROOT/'tests/DewarpModelTest.java')], check=True, capture_output=True, timeout=30)
            result = subprocess.run([str(java/'java'), '-cp', out, 'DewarpModelTest'],
                                    check=True, capture_output=True, text=True, timeout=10)
            self.assertIn('dewarp assertions passed.', result.stdout)

    def test_no_cpu_frames_or_busy_render_loop(self):
        source = (SRC/'DewarpView.java').read_text()
        self.assertIn('RENDERMODE_WHEN_DIRTY', source)
        self.assertIn('framePending.getAndSet(false)', source)
        self.assertIn('if (fresh) frames++', source)
        self.assertIn('texMatrix*vec4(source,0.0,1.0)', source)
        self.assertIn('atan(t)/t', source)
        self.assertIn('1.0/aspect', source)
        for unwanted in ('glReadPixels', 'Bitmap', 'MediaRecorder', 'Socket', 'RENDERMODE_CONTINUOUSLY'):
            self.assertNotIn(unwanted, source)

    def test_lifecycle_and_fallback(self):
        source = (SRC/'ViewerActivity.java').read_text()
        self.assertIn('resumed = false; close(); stopOutput();', source)
        self.assertIn('close(); stopOutput(); show("Paused")', source)
        self.assertIn('token != outputGeneration || !resumed || !unlocked()', source)
        self.assertIn('close(); stopOutput(); lensFallback = true;', source)
        self.assertIn('updateLensButton(); failed();', source)
        self.assertIn('health.stalled(presented, now)', source)
        self.assertIn('dewarp.frames() - glFrameBase', source)
        renderer = (SRC/'DewarpView.java').read_text()
        self.assertIn('if (created) { fail(); return; }', renderer)
        self.assertIn('output.release()', renderer)
        self.assertIn('texture.release()', renderer)
        self.assertIn('main.removeCallbacksAndMessages(null)', renderer)

    def test_compact_icons_keep_accessibility_and_touch_targets(self):
        source = (SRC/'ViewerActivity.java').read_text()
        self.assertIn('new FrameLayout.LayoutParams(dp(48), dp(48), gravity)', source)
        self.assertIn('button.setPadding(dp(12), dp(12), dp(12), dp(12))', source)
        self.assertIn('new InsetDrawable(new RippleDrawable(', source)
        self.assertLess(source.index('button.setBackground('), source.index('button.setPadding('))
        self.assertIn('lensButton.setContentDescription(', source)
        self.assertIn('audioButton.setContentDescription(', source)
        self.assertIn('button.getContentDescription()', source)
        self.assertIn('audioIcon.state(audio.listening() ? 1 : 0)', source)
        self.assertNotIn('lensButton.setText(', source)
        self.assertNotIn('audioButton.setText(', source)
        icons = (SRC/'ViewerIcon.java').read_text()
        self.assertIn('i < state ? alpha : alpha/4', icons)
        self.assertNotIn('Bitmap', icons)

    def test_toggle_only_changes_renderer_and_lens_preference(self):
        source = (SRC/'ViewerActivity.java').read_text()
        toggle = source.split('lensButton.setOnClickListener',1)[1].split('layout.addView(lensButton',1)[0]
        self.assertIn('dewarp.mode(lensMode)', toggle)
        self.assertNotIn('player.', toggle)
        self.assertNotIn('open()', toggle)
        renderer = (SRC/'DewarpView.java').read_text()
        self.assertIn('getInt("lens-mode", DewarpModel.DEFAULT_MODE)', renderer)
        self.assertEqual(renderer.count('.putInt('), 1)
        self.assertNotIn('.putBoolean(', renderer)


if __name__ == '__main__':
    unittest.main()
