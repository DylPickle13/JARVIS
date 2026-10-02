import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import android_transport as t
import pair_control as pair


class TransportTests(unittest.TestCase):
    def settings(self):
        return {'lg':{'mode':'wifi','host':'192.168.21.113','port':5555},
                'samsung':{'mode':'wifi','host':'192.168.21.12','port':34115,'service':'adb-R5CRC27FBMP-Sw7P7P'}}

    def test_missing_config_never_falls_back_to_usb(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(RuntimeError, 'no USB fallback'):
                t.config(Path(root))

    def test_explicit_usb_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            (Path(root)/'android-transports.json').write_text(json.dumps({r:{'mode':'usb'} for r in t.IDENTITIES}))
            with self.assertRaisesRegex(ValueError, 'USB is disabled'):
                t.config(Path(root))

    def test_config_allowlist(self):
        for field,value in [('host','8.8.8.8'),('port',0),('service','adb-wrong-identity'),('mode','automatic')]:
            with self.subTest(field=field),tempfile.TemporaryDirectory() as root:
                cfg=self.settings();cfg['samsung'][field]=value
                (Path(root)/'android-transports.json').write_text(json.dumps(cfg))
                with self.assertRaises(ValueError):t.config(Path(root))

    def test_connected_identity_checked_without_connect(self):
        cfg=self.settings();selected=t.targets(cfg)
        with patch.object(t.subprocess,'check_output',return_value='R5CRC27FBMP\n') as read,patch.object(t.subprocess,'run') as connect:
            self.assertEqual(t.ensure('samsung',cfg,selected),'192.168.21.12:34115')
            self.assertEqual(read.call_args.args[0][-3:],['shell','getprop','ro.serialno'])
            connect.assert_not_called()

    def test_mismatch_blocks_discovery_and_commands(self):
        cfg=self.settings()
        with patch.object(t.subprocess,'check_output',return_value='other-phone'),patch.object(t,'discover_port') as discover,patch.object(t.subprocess,'run') as connect:
            with self.assertRaises(RuntimeError):t.ensure('samsung',cfg,t.targets(cfg))
            discover.assert_not_called();connect.assert_not_called()

    def test_tls_port_changes_only_same_paired_service(self):
        cfg=self.settings();selected=t.targets(cfg)
        with patch.object(t,'verify',side_effect=[subprocess.TimeoutExpired('adb',8),None]) as identity,patch.object(t,'discover_port',return_value=43210) as discover,patch.object(t.subprocess,'run') as connect:
            self.assertEqual(t.ensure('samsung',cfg,selected),'192.168.21.12:43210')
            discover.assert_called_once_with('adb-R5CRC27FBMP-Sw7P7P')
            self.assertEqual(identity.call_args.args,('samsung','192.168.21.12:43210'))
            self.assertEqual(connect.call_args.args[0][-2:],['connect','192.168.21.12:43210'])
            self.assertEqual(selected['samsung'],'192.168.21.12:43210')

    def test_lg_connect_uses_only_configured_wifi(self):
        cfg=self.settings()
        with patch.object(t,'verify',side_effect=[OSError('offline'),OSError('offline')]),patch.object(t.subprocess,'run') as connect:
            with self.assertRaises(OSError):t.ensure('lg',cfg,t.targets(cfg))
            connect.assert_called_once()
            self.assertEqual(connect.call_args.args[0][-1],'192.168.21.113:5555')

    def test_usb_unavailable_does_not_try_network(self):
        cfg={r:{'mode':'usb'} for r in t.IDENTITIES}
        with patch.object(t,'verify',side_effect=OSError('offline')),patch.object(t.subprocess,'run') as connect:
            with self.assertRaises(OSError):t.ensure('lg',cfg,t.targets(cfg))
            connect.assert_not_called()

    def test_ambiguous_mutation_never_replayed(self):
        with patch.object(t,'ensure',return_value='192.168.21.12:34115'),patch.object(pair.subprocess,'check_output',side_effect=subprocess.TimeoutExpired('adb',15)) as command:
            with self.assertRaises(subprocess.TimeoutExpired):pair.toggle('samsung')
            command.assert_called_once()
            self.assertEqual(command.call_args.args[0][-1],'KEYCODE_VOLUME_UP')

    def test_guard_failure_prevents_camera_command(self):
        with patch.object(t,'ensure',side_effect=RuntimeError('identity mismatch')),patch.object(pair.subprocess,'check_output') as command:
            with self.assertRaises(RuntimeError):pair.toggle('samsung')
            command.assert_not_called()


if __name__=='__main__':unittest.main()
