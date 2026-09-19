import json
import os
from pathlib import Path
import socket
import tempfile
import threading
import unittest
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
