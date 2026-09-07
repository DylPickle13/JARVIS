import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from room_audio_control import RoomAudioControl
import pi_room_audio_client as client

class ControlTests(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.control = RoomAudioControl(lambda: self.now)
        self.payload = dict(clientID='a'*32, sequence=1, turnID='b'*32, phase='processing')
    def report(self, **changes):
        self.payload.update(changes)
        return self.control.report(dict(self.payload))
    def test_idle_processing_and_actual_playback(self):
        self.assertFalse(self.control.status()['clientOnline'])
        self.report()
        self.assertTrue(self.control.status()['canStop'])
        self.report(sequence=2, phase='speaking')
        self.assertEqual(self.control.status()['phase'], 'speaking')
        self.report(sequence=3, phase='idle', turnID=None)
        self.assertFalse(self.control.status()['canStop'])
    def test_stale_client_is_never_idle_or_stoppable(self):
        self.report(); self.now = 7
        self.assertEqual(self.control.status()['phase'], 'unavailable')
        with self.assertRaises(ValueError): self.control.stop('b'*32)
    def test_stop_is_exact_and_idempotent_without_cancelling_new_turn(self):
        self.report()
        with self.assertRaises(ValueError): self.control.stop('c'*32)
        self.assertEqual(self.control.stop('b'*32)['phase'], 'cancelling')
        self.control.stop('b'*32)
        self.assertEqual(self.report(sequence=2)['cancelTurnID'], 'b'*32)
        self.assertTrue(self.control.is_cancelled('b'*32))
        self.assertIsNone(self.report(sequence=3, turnID='c'*32)['cancelTurnID'])
        with self.assertRaises(ValueError): self.control.stop('b'*32)
    def test_replays_invalid_data_and_retired_clients_rejected(self):
        self.report()
        with self.assertRaises(ValueError): self.report()
        with self.assertRaises(ValueError): self.report(sequence=True)
        with self.assertRaises(ValueError): self.report(sequence=2, phase='arbitrary')
        self.report(sequence=1, phase='idle', turnID=None, clientID='d'*32)
        with self.assertRaises(ValueError): self.report(sequence=8, clientID='a'*32)
        with self.assertRaises(ValueError): self.control.report({'prompt':'private'})
    def test_cancellation_records_are_bounded_and_expire(self):
        for i in range(300):
            turn=f'{i:032x}'
            self.report(sequence=i+1, turnID=turn)
            self.control.stop(turn)
        self.assertEqual(len(self.control.cancelled),256)
        self.now=601
        self.assertTrue(self.control.is_cancelled(turn), "in-flight cancellation survives a long ASR call")
        self.report(sequence=301, phase="idle", turnID=None)
        self.assertFalse(self.control.is_cancelled(turn))
    def test_no_private_content_in_status(self):
        self.report()
        self.assertEqual(set(self.control.status()), {'ok','clientOnline','phase','turnID','canStop','ageSeconds'})

class ClientControlTests(unittest.TestCase):
    def test_report_uses_playback_phase_and_matching_cancel_only(self):
        controller=client.RoomAudioTurnController(SimpleNamespace(server_url='http://localhost:1234',token='fixture'))
        controller._turn_id='b'*32
        controller._state='PLAYING'
        import threading
        controller._cancel_event=threading.Event()
        class Response:
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def read(self,*args): return json.dumps({'ok':True,'cancelTurnID':'b'*32}).encode()
        with patch.object(client.urllib.request,'urlopen',return_value=Response()) as send, patch.object(controller.playback,'stop') as stop:
            controller._report_once()
            sent=json.loads(send.call_args.args[0].data)
            self.assertEqual(sent['phase'],'speaking')
            self.assertEqual(set(sent),{'clientID','sequence','turnID','phase'})
            self.assertTrue(controller._cancel_event.is_set())
            stop.assert_called_once()
    def test_old_cancel_cannot_stop_new_playback(self):
        controller=client.RoomAudioTurnController(SimpleNamespace())
        controller._turn_id='c'*32
        with patch.object(controller.playback,'stop') as stop:
            self.assertFalse(controller.cancel_local('b'*32))
            stop.assert_not_called()


class ControlHTTPTests(unittest.TestCase):
    def setUp(self):
        import room_audio_server as server
        import threading
        self.server_module = server
        self.control = RoomAudioControl()
        self.cancelled = []
        self.server = server.RoomAudioHTTPServer(("127.0.0.1", 0), server.RoomAudioHandler)
        self.server.token = "fixture"
        self.server.bridge = SimpleNamespace(control=self.control, cancel_turn=self.cancelled.append)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()
    def request(self,path,payload=None,token=None):
        import http.client
        conn=http.client.HTTPConnection("127.0.0.1",self.server.server_port,timeout=2)
        headers={"Content-Type":"application/json"}
        if token: headers["x-jarvis-room-token"]=token
        conn.request("POST" if payload is not None else "GET",path,
                     json.dumps(payload) if payload is not None else None,headers)
        res=conn.getresponse(); value=json.loads(res.read()); conn.close()
        return res.status,value
    def test_authenticated_player_reports_and_loopback_stop(self):
        payload=dict(clientID="a"*32,sequence=1,turnID="b"*32,phase="speaking")
        self.assertEqual(self.request("/client-state",payload)[0],403)
        self.assertEqual(self.request("/client-state",payload,"fixture")[0],200)
        status,value=self.request("/control/status")
        self.assertEqual(value["phase"],"speaking")
        self.assertEqual(self.request("/control/stop",{"turnID":"c"*32})[0],409)
        self.assertEqual(self.cancelled,[])
        self.assertEqual(self.request("/control/stop",{"turnID":"b"*32})[0],200)
        self.assertEqual(self.cancelled,["b"*32])
        payload["sequence"]=2
        self.assertEqual(self.request("/client-state",payload,"fixture")[1]["cancelTurnID"],"b"*32)
    def test_lan_control_denied_even_with_room_token(self):
        with patch.object(self.server_module,"is_loopback_address",return_value=False):
            self.assertEqual(self.request("/control/status",token="fixture")[0],403)
            self.assertEqual(self.request("/control/stop",{"turnID":"b"*32},"fixture")[0],403)
        self.assertEqual(self.cancelled,[])

if __name__=='__main__': unittest.main()
