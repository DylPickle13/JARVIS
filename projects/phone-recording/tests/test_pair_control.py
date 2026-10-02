import unittest
from unittest.mock import patch
from pair_control import parse_state, change


class PairTests(unittest.TestCase):
    def test_idle(self):
        self.assertEqual(parse_state('<hierarchy><node resource-id="net.sourceforge.opencamera:id/take_photo" content-desc="Start recording video"/></hierarchy>'), 'idle')

    def test_settings_obscure_shutter(self):
        self.assertEqual(parse_state('<hierarchy><node text="Video settings"/><node resource-id="net.sourceforge.opencamera:id/take_photo" content-desc="Start recording video"/></hierarchy>'), 'unknown_or_overlay')

    def test_refuses_existing_recording(self):
        with patch('pair_control.status', return_value={'lg':'recording','samsung':'idle'}), patch('pair_control.parallel') as send:
            self.assertFalse(change('start')['ok'])
            send.assert_not_called()

    def test_partial_start_rollback(self):
        with patch('pair_control.status', side_effect=[{'lg':'idle','samsung':'idle'}, {'lg':'recording','samsung':'unknown'}, {'lg':'idle','samsung':'unknown'}]), patch('pair_control.parallel', return_value={}) as send:
            r = change('start')
            self.assertFalse(r['ok'])
            self.assertEqual(send.call_args_list[-1].args[1], ['lg'])

    def test_stop_skips_unknown(self):
        with patch('pair_control.status', side_effect=[{'lg':'recording','samsung':'unknown'}, {'lg':'idle','samsung':'unknown'}]), patch('pair_control.parallel', return_value={}) as send:
            self.assertFalse(change('stop')['ok'])
            self.assertEqual(send.call_args.args[1], ['lg'])


if __name__ == '__main__':
    unittest.main()
