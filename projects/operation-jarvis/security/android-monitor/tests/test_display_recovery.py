from pathlib import Path
import os
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
JAVA=ROOT/'android/src/local/jarvis/monitor'

class Recovery(unittest.TestCase):
    def test_pure_admission_and_observation_policy(self):
        java=Path(os.environ.get('JAVA_HOME','/opt/homebrew/opt/openjdk@17'))/'bin'
        with tempfile.TemporaryDirectory() as d:
            subprocess.run([str(java/'javac'),'-d',d,str(JAVA/'DisplayRecovery.java'),str(ROOT/'tests/DisplayRecoveryTest.java')],check=True,capture_output=True,timeout=30)
            subprocess.run([str(java/'java'),'-cp',d,'DisplayRecoveryTest'],check=True,capture_output=True,timeout=10)

    def test_errors_preserve_enable_intent_and_boot_does_not_clear_pending(self):
        service=(JAVA/'MonitorService.java').read_text();boot=(JAVA/'Boot.java').read_text()
        fail=service.split('private void fail() {',1)[1].split('@Override public void onDestroy()',1)[0]
        self.assertNotIn('putBoolean("enabled", false)',fail)
        self.assertNotIn('stopSelf()',fail)
        self.assertIn('DisplayRecovery.observed(state, pm.isInteractive(), keyguard.isKeyguardLocked())',service)
        self.assertIn('if (!DisplayRecovery.admitted(state, age, power))',service)
        self.assertNotIn('putBoolean("pending", false)',boot)
        self.assertIn('if (p.getBoolean("enabled", false))',boot)
        self.assertIn('isKeyguardSecure()',service)

    def test_permission_repair_and_enable_button_never_clear_an_unknown_action(self):
        admin=(JAVA/'Admin.java').read_text(); activity=(JAVA/'MainActivity.java').read_text()
        self.assertNotIn('.edit()', admin)
        self.assertNotIn('stopService', admin)
        self.assertIn('getBoolean("enabled", false)', admin)
        self.assertIn('void onEnabled', admin)
        self.assertIn('void onDisabled', admin)
        self.assertNotIn('putBoolean("pending", false)', activity)
        self.assertNotIn('acknowledge reviewed error', activity)
        self.assertIn('putBoolean("enabled", false)', activity)  # Deliberate Off remains.

if __name__=='__main__':unittest.main()
