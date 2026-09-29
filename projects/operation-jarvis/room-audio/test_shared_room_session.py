import json
import os
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest
import wave
from unittest import mock
from shared_room_session import SharedRoomSession

class SharedSessionTests(unittest.TestCase):
    def test_both_adapters_use_same_owner_and_translate_only_final_reply(self):
        with tempfile.TemporaryDirectory(dir='/tmp', prefix='room-') as tmp:
            root=Path(tmp); directory=root/'.pi/runtime/room-audio-session';directory.mkdir(parents=True,mode=0o700)
            path=directory/f'room-{os.getpid()}.sock'; server=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);server.bind(str(path));path.chmod(0o600);server.listen(2)
            descriptor=directory/'owner.json';descriptor.write_text(json.dumps({'version':1,'sessionID':10,'pid':os.getpid(),'generation':'fixture','socketPath':str(path)}));descriptor.chmod(0o600)
            prompts=[]
            def peer():
                for _ in range(2):
                    c,_=server.accept();raw=b''
                    while not raw.endswith(b'\n'):raw+=c.recv(65536)
                    request=json.loads(raw);prompts.append(request['text'])
                    c.sendall(json.dumps({'ok':True,'requestID':request['id'],'text':'answer'}).encode()+b'\n');c.close()
            thread=threading.Thread(target=peer);thread.start()
            try:
                for name in ('pi','mac'):
                    events=[];SharedRoomSession(root).run_prompt(name,on_event=events.append,timeout_seconds=2)
                    self.assertEqual(events[0]['assistantMessageEvent']['delta'],'answer')
                thread.join(3);self.assertEqual(prompts,['pi','mac'])
            finally:server.close()

    def test_missing_owner_never_starts_rpc_or_creates_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            session=SharedRoomSession(Path(tmp))
            with self.assertRaises(Exception):session.run_prompt('test',timeout_seconds=.1)
            self.assertEqual(list(Path(tmp).iterdir()),[])
            self.assertFalse(session.abort_active())

    def test_stop_never_resets_or_closes_shared_conversation(self):
        session=SharedRoomSession(Path('/unused'))
        with mock.patch.object(session,'exchange') as exchange:
            session.stop();exchange.assert_not_called()
            self.assertFalse(session.start_new_session_if_idle(0))
            self.assertIsNone(session.seconds_since_last_activity())

    def test_error_is_not_retried_and_other_active_turn_not_aborted(self):
        session=SharedRoomSession(Path('/unused'))
        with mock.patch.object(session,'exchange',return_value={'ok':False,'error':'busy'}) as exchange:
            with self.assertRaises(RuntimeError):session.run_prompt('test')
            exchange.assert_called_once()
            self.assertFalse(session.abort_active())

    def test_bridge_uses_repository_root_not_voice_config_root(self):
        import room_audio_server as server
        with mock.patch.dict(os.environ, {'JARVIS_ROOM_AUDIO_SHARED_SESSION':'10'}), \
             mock.patch.object(server.config, 'PROJECT_ROOT', server.VOICE_ROOT), \
             mock.patch('shared_room_session.SharedRoomSession') as adapter, \
             mock.patch.object(server.voice_pipeline, 'VoicePipeline', side_effect=RuntimeError('fixture boundary')):
            with self.assertRaisesRegex(RuntimeError, 'fixture boundary'):
                server.RoomAudioBridge()
            adapter.assert_called_once_with(server.PROJECT_ROOT)
            self.assertNotEqual(server.PROJECT_ROOT, server.VOICE_ROOT)

    def stream_fixture(self, behavior, *, capable=True):
        tmp=tempfile.TemporaryDirectory(dir='/tmp', prefix='room-stream-')
        self.addCleanup(tmp.cleanup)
        root=Path(tmp.name); directory=root/'.pi/runtime/room-audio-session'
        directory.mkdir(parents=True,mode=0o700)
        path=directory/f'room-{os.getpid()}.sock'
        server=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
        server.bind(str(path));path.chmod(0o600);server.listen(1)
        descriptor=directory/'owner.json'
        data={'version':1,'sessionID':10,'pid':os.getpid(),'generation':'fixture','socketPath':str(path)}
        if capable:data['capabilities']=['tts-candidates-v1']
        descriptor.write_text(json.dumps(data));descriptor.chmod(0o600)
        requests=[];errors=[]
        def peer():
            try:
                server.settimeout(2)
                connection,_=server.accept()
                with connection:
                    raw=b''
                    while not raw.endswith(b'\n'):raw+=connection.recv(8192)
                    request=json.loads(raw);requests.append(request)
                    behavior(connection,request)
            except Exception as error:errors.append(error)
        thread=threading.Thread(target=peer);thread.start()
        def cleanup():
            thread.join(3);server.close()
            self.assertFalse(thread.is_alive())
            self.assertEqual(errors,[])
        self.addCleanup(cleanup)
        return SharedRoomSession(root),requests

    def test_candidates_arrive_early_but_only_terminal_reply_is_final(self):
        received=threading.Event()
        def peer(connection,request):
            common={'ok':True,'generation':'fixture','requestID':request['id']}
            start={**common,'event':'candidate','type':'candidate_start','candidate':1}
            delta={**common,'event':'candidate','type':'candidate_delta','candidate':1,'delta':'Ready, sir.'}
            # Coalesced lines and split reads exercise the stream parser.
            raw=(json.dumps(start)+'\n'+json.dumps(delta)+'\n').encode()
            connection.sendall(raw[:17]);connection.sendall(raw[17:])
            self.assertTrue(received.wait(2),'Candidates must arrive before the terminal reply')
            connection.sendall((json.dumps({**common,'event':'done','text':'Ready, sir.'})+'\n').encode())
        session,requests=self.stream_fixture(peer)
        candidates=[];final=[]
        def candidate(event):
            self.assertEqual(final,[])
            candidates.append(event)
            if event['type']=='candidate_delta':received.set()
        session.run_prompt('fixture',on_candidate=candidate,on_event=final.append,timeout_seconds=3)
        self.assertEqual(len(requests),1)
        self.assertEqual(requests[0]['action'],'prompt_stream')
        self.assertEqual([event['type'] for event in candidates],['candidate_start','candidate_delta'])
        self.assertEqual(len(final),1)
        self.assertEqual(final[0]['assistantMessageEvent']['delta'],'Ready, sir.')

    def test_old_owner_uses_legacy_prompt_once_without_candidates(self):
        def peer(connection,request):
            connection.sendall((json.dumps({'ok':True,'requestID':request['id'],'text':'legacy'})+'\n').encode())
        session,requests=self.stream_fixture(peer,capable=False)
        candidates=[];final=[]
        session.run_prompt('fixture',on_candidate=candidates.append,on_event=final.append,timeout_seconds=2)
        self.assertEqual(requests[0]['action'],'prompt')
        self.assertEqual(len(requests),1)
        self.assertEqual(candidates,[])
        self.assertEqual(final[0]['assistantMessageEvent']['delta'],'legacy')

    def test_wrong_generation_is_rejected_without_replay_or_final_delivery(self):
        def peer(connection,request):
            connection.sendall((json.dumps({'ok':True,'requestID':request['id'],'generation':'wrong',
                'event':'done','text':'must not speak'})+'\n').encode())
        session,requests=self.stream_fixture(peer)
        final=[]
        with self.assertRaisesRegex(RuntimeError,'identity changed'):
            session.run_prompt('fixture',on_candidate=lambda event:None,on_event=final.append,timeout_seconds=2)
        self.assertEqual(len(requests),1)
        self.assertEqual(final,[])
        self.assertFalse(session.abort_active())

    def test_lost_stream_is_not_replayed_or_delivered_as_final(self):
        def peer(connection,request):
            connection.sendall((json.dumps({'ok':True,'requestID':request['id'],'generation':'fixture',
                'event':'candidate','type':'candidate_start','candidate':1})+'\n').encode())
        session,requests=self.stream_fixture(peer)
        final=[]
        with self.assertRaisesRegex(RuntimeError,'lost; never replay'):
            session.run_prompt('fixture',on_candidate=lambda event:None,on_event=final.append,timeout_seconds=2)
        self.assertEqual(len(requests),1)
        self.assertEqual(final,[])

    def test_bridge_prerenders_over_socket_and_returns_only_confirmed_final_audio(self):
        import room_audio_server as server_module
        from voice_pipeline import VoicePipeline, VoicePipelineConfig
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        paths=[];calls=[];ready=threading.Event()
        def synth(text):
            calls.append(text)
            path=Path(directory.name)/f'{len(calls)}.wav'
            with wave.open(str(path),'wb') as wav:
                wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(22050)
                wav.writeframes(b'\x01\x00'*32)
            paths.append(path)
            if text=='Ready, sir.':ready.set()
            return path
        def peer(connection,request):
            common={'ok':True,'generation':'fixture','requestID':request['id']}
            def emit(kind,**fields):
                connection.sendall((json.dumps({**common,'event':'candidate','type':kind,**fields})+'\n').encode())
            emit('candidate_start',candidate=1)
            emit('candidate_delta',candidate=1,delta='Ready, sir.')
            self.assertTrue(ready.wait(2),'Real IPC must feed synthesis before the final answer arrives')
            connection.sendall((json.dumps({**common,'event':'done','text':'Ready, sir.'})+'\n').encode())
        session,requests=self.stream_fixture(peer)
        bridge=server_module.RoomAudioBridge.__new__(server_module.RoomAudioBridge)
        bridge._session=session;bridge.conversation_session_id=10;bridge._tts_prerender_enabled=True
        bridge._lock=threading.Lock();bridge._active_pi_turn_lock=threading.Lock();bridge._active_pi_turn_id=''
        bridge._model='fixture';bridge._thinking='off'
        bridge._pipeline=VoicePipeline(VoicePipelineConfig(stream_tts=False),response_callback=bridge._run_pi_response)
        bridge._pipeline._synthesize_segment=synth
        response=bridge._synthesize_accepted_turn(Path('unused'),transcript='fixture',input_seconds=0,
            asr_seconds=0,started_at=time.monotonic(),include_ack=False)
        self.assertEqual(response['replyText'],'Ready, sir.')
        self.assertEqual(response['ttsPrerender']['reusedSegments'],1)
        self.assertEqual(calls,['Ready, sir.'])
        self.assertTrue(response['audioWavBase64'])
        self.assertTrue(all(not path.exists() for path in paths))
        self.assertEqual(requests[0]['action'],'prompt_stream')

    def test_broken_speculative_callback_does_not_lose_the_answer(self):
        def peer(connection,request):
            common={'ok':True,'requestID':request['id'],'generation':'fixture'}
            connection.sendall((json.dumps({**common,'event':'candidate','type':'candidate_start','candidate':1})+'\n'+
                                json.dumps({**common,'event':'done','text':'answer'})+'\n').encode())
        session,requests=self.stream_fixture(peer)
        final=[]
        def broken(event):raise RuntimeError('fixture renderer failure')
        session.run_prompt('fixture',on_candidate=broken,on_event=final.append,timeout_seconds=2)
        self.assertEqual(len(requests),1)
        self.assertEqual(final[0]['assistantMessageEvent']['delta'],'answer')
