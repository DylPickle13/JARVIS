"""Offline tests: no real inference, speaker playback, or household actions."""
import tempfile
import threading
import time
import unittest
import wave
from pathlib import Path
from dataclasses import replace
import os
from unittest import mock

import room_audio_server
from room_tts_prerender import RoomTTSPrerender, RoomTTSPrerenderCancelled, speech_segments
from voice_pipeline import VoicePipeline, VoicePipelineConfig, VoicePipelineResult


def wait_for(predicate, timeout=2):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.005)
    raise AssertionError('Timed out waiting for fixture worker')


class PrerenderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.pipeline = VoicePipeline(VoicePipelineConfig(max_tts_chars_per_segment=80))
        self.calls = []
        self.paths = []
        self.pipeline._synthesize_segment = self.synth
        self.renderers = []
        self.addCleanup(self.cleanup_renderers)

    def cleanup_renderers(self):
        for renderer in self.renderers:
            renderer.close()
            if renderer._thread is not None:
                renderer._thread.join(2)
                self.assertFalse(renderer._thread.is_alive())

    def synth(self, text):
        self.calls.append(text)
        path = Path(self.temp.name)/f'{len(self.calls)}.wav'
        with wave.open(str(path), 'wb') as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(22050)
            wav.writeframes(b'\x01\x00' * 32)
        self.paths.append(path)
        return path

    def renderer(self, **kwargs):
        renderer = RoomTTSPrerender(self.pipeline, **kwargs)
        self.renderers.append(renderer)
        return renderer

    def start(self, renderer, text, candidate=1, end=False):
        renderer.on_candidate({'type': 'candidate_start', 'candidate': candidate})
        renderer.on_candidate({'type': 'candidate_delta', 'candidate': candidate, 'delta': text})
        if end:
            renderer.on_candidate({'type': 'candidate_end', 'candidate': candidate, 'text': text})

    def test_renders_during_generation_but_only_commit_returns_audio(self):
        renderer = self.renderer()
        self.start(renderer, 'Done, sir. The light is off.')
        wait_for(lambda: renderer.stats()['renderedSegments'] == 2)
        self.assertFalse(renderer._committing)
        self.assertEqual(renderer.stats()['reusedSegments'], 0)
        speculative = list(self.paths)
        output = renderer.commit('Done, sir. The light is off.')
        self.assertEqual(output, speculative)
        self.assertEqual(self.calls, ['Done, sir.', 'The light is off.'])
        self.assertEqual(renderer.stats()['reusedSegments'], 2)
        self.assertTrue(all(p.exists() for p in output), 'Transferred files belong to final response cleanup')

    def test_tool_chatter_and_old_candidate_are_discarded(self):
        renderer = self.renderer()
        self.start(renderer, 'I will check the light.')
        wait_for(lambda: renderer.stats()['renderedSegments'] == 1)
        stale = self.paths[0]
        renderer.on_candidate({'type': 'candidate_invalidate', 'candidate': 1})
        renderer.on_candidate({'type': 'candidate_delta', 'candidate': 1, 'delta': 'Late old text.'})
        self.assertFalse(stale.exists())
        self.start(renderer, 'Done, sir.', candidate=2)
        wait_for(lambda: renderer.stats()['renderedSegments'] == 2)
        output = renderer.commit('Done, sir.')
        self.assertEqual(len(output), 1)
        self.assertEqual(renderer.stats()['reusedSegments'], 1)
        self.assertNotIn('Late old text.', self.calls)
        self.assertNotIn(stale, output)

    def test_same_text_from_invalidated_message_is_not_reused(self):
        renderer = self.renderer()
        self.start(renderer, 'Done, sir.')
        wait_for(lambda: renderer.stats()['renderedSegments'] == 1)
        stale = self.paths[0]
        renderer.on_candidate({'type': 'candidate_invalidate', 'candidate': 1})
        output = renderer.commit('Done, sir.')
        self.assertNotIn(stale, output)
        self.assertEqual(renderer.stats()['reusedSegments'], 0)
        self.assertEqual(self.calls, ['Done, sir.', 'Done, sir.'])

    def test_final_mismatch_never_returns_provisional_audio(self):
        renderer = self.renderer()
        self.start(renderer, 'The request succeeded.')
        wait_for(lambda: renderer.stats()['renderedSegments'] == 1)
        stale = self.paths[0]
        output = renderer.commit('The request failed, sir.')
        self.assertFalse(stale.exists())
        self.assertNotIn(stale, output)
        self.assertEqual(self.calls[-1], 'The request failed, sir.')
        self.assertEqual(renderer.stats()['reusedSegments'], 0)

    def test_remaining_fragment_is_rendered_at_commit(self):
        renderer = self.renderer()
        self.start(renderer, 'Done, sir. Trailing fragment')
        wait_for(lambda: renderer.stats()['renderedSegments'] == 1)
        output = renderer.commit('Done, sir. Trailing fragment')
        self.assertEqual(len(output), 2)
        self.assertEqual(self.calls, ['Done, sir.', 'Trailing fragment'])
        self.assertEqual(renderer.stats()['reusedSegments'], 1)

    def test_message_end_renders_fragment_before_agent_settled(self):
        renderer = self.renderer()
        self.start(renderer, 'Trailing fragment', end=True)
        wait_for(lambda: renderer.stats()['renderedSegments'] == 1)
        renderer.commit('Trailing fragment')
        self.assertEqual(renderer.stats()['reusedSegments'], 1)

    def test_matching_inflight_work_is_not_synthesized_twice(self):
        entered, release = threading.Event(), threading.Event()
        def blocked(text):
            entered.set()
            self.assertTrue(release.wait(2))
            return self.synth(text)
        self.pipeline._synthesize_segment = blocked
        renderer = self.renderer()
        self.start(renderer, 'Ready, sir.')
        self.assertTrue(entered.wait(2))
        result = []
        thread = threading.Thread(target=lambda: result.extend(renderer.commit('Ready, sir.')))
        thread.start()
        wait_for(lambda: renderer._committing)
        self.assertEqual(result, [])
        release.set()
        thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(self.calls, ['Ready, sir.'])
        self.assertEqual(len(result), 1)

    def test_cancel_discards_ready_and_late_inflight_files(self):
        entered, release = threading.Event(), threading.Event()
        def blocked(text):
            entered.set()
            self.assertTrue(release.wait(2))
            return self.synth(text)
        self.pipeline._synthesize_segment = blocked
        cancel = threading.Event()
        renderer = self.renderer(cancel_event=cancel)
        self.start(renderer, 'Ready, sir.')
        self.assertTrue(entered.wait(2))
        cancel.set()
        renderer.close()
        self.assertFalse(release.is_set(), 'Close must not wait for inference')
        with self.assertRaises(RoomTTSPrerenderCancelled):
            renderer.commit('Ready, sir.')
        release.set()
        renderer._thread.join(2)
        self.assertTrue(self.paths)
        self.assertTrue(all(not path.exists() for path in self.paths))

    def test_speculative_error_falls_back_to_normal_final_synthesis(self):
        attempts = []
        def flaky(text):
            attempts.append(text)
            if len(attempts) == 1:
                raise RuntimeError('fixture speculative failure')
            return self.synth(text)
        self.pipeline._synthesize_segment = flaky
        renderer = self.renderer()
        self.start(renderer, 'Ready, sir.')
        wait_for(lambda: len(attempts) == 1 and renderer._inflight is None)
        output = renderer.commit('Ready, sir.')
        self.assertEqual(len(output), 1)
        self.assertEqual(len(attempts), 2)
        self.assertEqual(renderer.stats()['reusedSegments'], 0)

    def test_work_is_bounded_but_final_answer_not_truncated(self):
        renderer = self.renderer(max_segments=2)
        self.start(renderer, 'One. Two. Three. Four.')
        wait_for(lambda: renderer.stats()['renderedSegments'] == 2)
        self.assertEqual(renderer._attempts, 2)
        output = renderer.commit('One. Two. Three. Four.')
        self.assertEqual(len(output), 4)
        self.assertEqual(self.calls, ['One.', 'Two.', 'Three.', 'Four.'])

    def test_byte_budget_is_enforced_and_falls_back(self):
        renderer = self.renderer(max_bytes=45)
        self.start(renderer, 'One.', end=True)
        wait_for(lambda: renderer._attempts == 1 and renderer._inflight is None)
        self.assertEqual(renderer.stats()['renderedSegments'], 0)
        self.assertFalse(self.paths[0].exists())
        output = renderer.commit('One.')
        self.assertEqual(len(output), 1)
        self.assertEqual(renderer.stats()['reusedSegments'], 0)

    def test_duplicate_delta_end_and_stale_generation_do_not_duplicate_audio(self):
        renderer = self.renderer()
        self.start(renderer, 'One.', candidate=2, end=True)
        renderer.on_candidate({'type': 'candidate_start', 'candidate': 1})
        renderer.on_candidate({'type': 'candidate_delta', 'candidate': 1, 'delta': 'Stale.'})
        renderer.on_candidate({'type': 'candidate_end', 'candidate': 2, 'text': 'One.'})
        wait_for(lambda: renderer.stats()['renderedSegments'] == 1)
        renderer.commit('One.')
        self.assertEqual(self.calls, ['One.'])

    def test_canonical_cleaning_and_abbreviations(self):
        self.assertEqual(speech_segments(self.pipeline, '**Done**, sir. Next.', final=True), ['Done, sir.', 'Next.'])
        self.assertEqual(speech_segments(self.pipeline, 'Dr. Smith is here. It is 3.5 degrees.', final=True),
                         ['Dr. Smith is here.', 'It is 3.5 degrees.'])
        self.assertEqual(speech_segments(self.pipeline, 'It is 3.', final=False), [])
        self.assertEqual(speech_segments(self.pipeline, 'Dr.', final=False), [])
        self.assertEqual(speech_segments(self.pipeline, '<think>private</think> Ready.', final=True), ['Ready.'])

    def test_voice_settings_change_invalidates_prepared_audio(self):
        renderer = self.renderer()
        self.start(renderer, 'Ready, sir.')
        wait_for(lambda: renderer.stats()['renderedSegments'] == 1)
        stale = self.paths[0]
        self.pipeline.config = replace(self.pipeline.config, tts_piper_volume=.5)
        output = renderer.commit('Ready, sir.')
        self.assertNotIn(stale, output)
        self.assertFalse(stale.exists())
        self.assertEqual(renderer.stats()['reusedSegments'], 0)
        self.assertEqual(self.calls, ['Ready, sir.', 'Ready, sir.'])

    def test_partial_prefix_budget_does_not_truncate_final_answer(self):
        renderer = self.renderer(max_chars=8)
        self.start(renderer, 'One. Two. Three.', end=True)
        wait_for(lambda: renderer.stats()['renderedSegments'] >= 1)
        output = renderer.commit('One. Two. Three.')
        self.assertEqual(len(output), 3)
        self.assertEqual(self.calls[-1], 'Three.')
        self.assertLessEqual(len(renderer._raw), 8)

    def test_feature_is_shared_session_only_and_can_be_disabled(self):
        for shared, enabled, expected in [('10', '1', True), ('10', '0', False), ('', '1', False)]:
            with self.subTest(shared=shared, enabled=enabled), \
                 mock.patch.dict(os.environ, {'JARVIS_ROOM_AUDIO_SHARED_SESSION':shared,
                     'JARVIS_ROOM_AUDIO_TTS_PRERENDER':enabled}), \
                 mock.patch('shared_room_session.SharedRoomSession'), \
                 mock.patch.object(room_audio_server.pi_rpc, 'PiRpcSession'):
                bridge = room_audio_server.RoomAudioBridge()
                self.assertEqual(bridge._tts_prerender_enabled, expected)
                self.assertFalse(bridge._pipeline.config.stream_tts)

    def test_final_renderer_only_runs_after_successful_complete_response(self):
        renderer = self.renderer()
        def response(_text, _on_delta, _context):
            self.start(renderer, 'Ready, sir.')
            wait_for(lambda: renderer.stats()['renderedSegments'] == 1)
            self.assertFalse(renderer._committing)
            return 'Ready, sir.'
        self.pipeline.response_callback = response
        result = self.pipeline.synthesize_turn(Path('unused'), transcript='fixture', input_seconds=0,
            asr_seconds=0, final_synthesis=renderer.commit)
        self.assertEqual(result.reply_text, 'Ready, sir.')
        self.assertEqual(renderer.stats()['reusedSegments'], 1)
        self.assertEqual(self.calls, ['Ready, sir.'])

    def test_failed_generation_never_commits(self):
        self.pipeline.response_callback = mock.Mock(side_effect=RuntimeError('fixture failure'))
        final = mock.Mock()
        with self.assertRaisesRegex(RuntimeError, 'fixture failure'):
            self.pipeline.synthesize_turn(Path('unused'), transcript='fixture', input_seconds=0,
                asr_seconds=0, final_synthesis=final)
        final.assert_not_called()

    def test_cancel_racing_committed_result_cleans_every_wav(self):
        cancel = threading.Event()
        paths = [self.synth('One.'), self.synth('Two.')]
        def result(*_args, **_kwargs):
            cancel.set()
            return VoicePipelineResult('fixture', 'One. Two.', paths, 0, 0, 0, 0, 0)
        bridge = room_audio_server.RoomAudioBridge.__new__(room_audio_server.RoomAudioBridge)
        bridge._pipeline = mock.Mock(synthesize_turn=result)
        with self.assertRaises(room_audio_server.RoomAudioTurnCancelled):
            bridge._synthesize_accepted_turn(Path('unused'), transcript='fixture', input_seconds=0,
                asr_seconds=0, started_at=time.monotonic(), include_ack=False, cancel_event=cancel)
        self.assertTrue(all(not path.exists() for path in paths))


if __name__ == '__main__':
    unittest.main()
