"""Steering recording provider regressions; no inference or audio playback."""
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock

import voice_pipeline as pipeline_module


class SteeringBankTests(unittest.TestCase):
    def run_stream(self, provider, *, enabled=True, text='Generating your response, sir.', cancel=None):
        pipeline = pipeline_module.VoicePipeline(pipeline_module.VoicePipelineConfig(
            processing_ack_enabled=enabled, processing_ack_text=text),
            response_callback=lambda *_: 'Final reply.')
        pipeline.processing_ack_provider = provider
        paths, callback = [], mock.Mock()
        generations = iter([0])
        with mock.patch.object(pipeline, '_synthesize_segment', return_value=Path('final-fixture.wav')) as synth, \
             mock.patch.object(pipeline_module, '_turn_context_steering_generation',
                side_effect=lambda _: next(generations, 1)), \
             mock.patch.object(pipeline_module, '_turn_context_steering_tts_delay_seconds', return_value=0):
            pipeline._complete_with_callback_and_synthesize_streaming('fixture', audio_paths=paths,
                audio_path_callback=callback, turn_context={'cancelEvent': cancel})
        return paths, callback, synth

    def test_provider_receives_unique_steering_key_and_no_ack_synthesis_occurs(self):
        provider = mock.Mock(return_value=Path('ack-copy.wav'))
        paths, callback, synth = self.run_stream(provider)
        provider.assert_called_once()
        self.assertRegex(provider.call_args.args[0], r'^steering:[0-9a-f]{32}:1$')
        synth.assert_called_once_with('Final reply.')
        self.assertEqual(paths[0], Path('ack-copy.wav'))
        self.assertEqual(callback.call_args_list[0].args, (Path('ack-copy.wav'), 1))

    def test_disabled_empty_or_cancelled_never_calls_provider(self):
        cancel = threading.Event()
        cancel.set()
        for opts in ({'enabled': False}, {'text': ''}, {'text': '   '}, {'cancel': cancel}):
            provider = mock.Mock()
            self.run_stream(provider, **opts)
            provider.assert_not_called()

    def test_suppressed_duplicate_has_no_live_synthesis_fallback(self):
        provider = mock.Mock(return_value=None)
        paths, callback, synth = self.run_stream(provider)
        self.assertEqual(paths, [Path('final-fixture.wav')])
        synth.assert_called_once_with('Final reply.')

    def test_cancel_during_selection_deletes_disposable_without_playback(self):
        cancel = threading.Event()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'copy.wav'
            path.write_bytes(b'fixture')
            def provide(_key):
                cancel.set()
                return path
            paths, callback, synth = self.run_stream(provide, cancel=cancel)
            self.assertFalse(path.exists())
            self.assertNotIn(path, paths)
            self.assertFalse(any(call.args[0] == path for call in callback.call_args_list))


if __name__ == '__main__':
    unittest.main()
