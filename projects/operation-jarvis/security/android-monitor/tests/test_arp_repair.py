import importlib.util
import ipaddress
from pathlib import Path
import socket
import sys
import unittest

SPEC = importlib.util.spec_from_file_location('monitor_arp_repair', Path(__file__).parents[1] / 'arp_repair.py')
arp = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = arp
SPEC.loader.exec_module(arp)

LOCAL = arp.Peer.parse('192.168.40.10', '02:11:22:33:44:10')
PHONE = arp.Peer.parse('192.168.40.11', '02:11:22:33:44:11')
CAMERA = arp.Peer.parse('192.168.40.12', '02:11:22:33:44:12')


def reply(source, destination):
    return (destination.mac + source.mac + b'\x08\x06' + arp.HEADER +
            b'\x00\x02' + source.mac + source.ip.packed +
            destination.mac + destination.ip.packed)


class FakeSocket:
    def __init__(self, replies):
        self.replies = list(replies)
        self.queue = []
        self.sent = []
        self.blocking = True

    def setblocking(self, value):
        self.blocking = value

    def settimeout(self, value):
        self.blocking = True

    def send(self, frame):
        self.sent.append(frame)
        self.queue.extend(self.replies.pop(0) if self.replies else [])
        return len(frame)

    def recv(self, limit):
        if self.queue:
            return self.queue.pop(0)
        if not self.blocking:
            raise BlockingIOError()
        raise socket.timeout()


class ArpRepairTests(unittest.TestCase):
    def test_directed_request_does_not_move_phone_bridge_entry(self):
        frame = arp.request(LOCAL.mac, PHONE, CAMERA)
        self.assertEqual(len(frame), 42)
        self.assertEqual(frame[:6], CAMERA.mac)
        self.assertEqual(frame[6:12], LOCAL.mac)
        self.assertEqual(frame[20:22], b'\x00\x01')  # Request, never a fabricated reply.
        self.assertEqual(frame[22:28], PHONE.mac)
        self.assertEqual(frame[28:32], PHONE.ip.packed)
        self.assertEqual(frame[38:42], CAMERA.ip.packed)

    def test_only_consistent_reply_from_expected_peer_is_accepted(self):
        valid = reply(CAMERA, LOCAL)
        self.assertTrue(arp.is_reply(valid, CAMERA, LOCAL))
        self.assertTrue(arp.is_reply(valid + b'\x00' * 18, CAMERA, LOCAL))
        for position in (0, 6, 12, 14, 16, 18, 20, 22, 28, 32, 38):
            altered = bytearray(valid)
            altered[position] ^= 1
            self.assertFalse(arp.is_reply(bytes(altered), CAMERA, LOCAL), position)
        self.assertFalse(arp.is_reply(valid[:41], CAMERA, LOCAL))
        self.assertFalse(arp.is_reply(reply(PHONE, LOCAL), CAMERA, LOCAL))

    def test_repair_requires_both_current_associations(self):
        sock = FakeSocket([[reply(CAMERA, LOCAL)], [reply(PHONE, LOCAL)]])
        self.assertEqual(arp.repair(sock, LOCAL, PHONE, CAMERA), 'lookup-relayed')
        self.assertEqual(sock.sent, [arp.request(LOCAL.mac, LOCAL, CAMERA),
                                    arp.request(LOCAL.mac, LOCAL, PHONE),
                                    arp.request(LOCAL.mac, PHONE, CAMERA)])

    def test_doorbell_failure_never_emits_on_behalf_of_phone(self):
        sock = FakeSocket([[]])
        self.assertEqual(arp.repair(sock, LOCAL, PHONE, CAMERA), 'doorbell-unverified')
        self.assertEqual(len(sock.sent), 1)

    def test_phone_failure_never_emits_on_behalf_of_phone(self):
        sock = FakeSocket([[reply(CAMERA, LOCAL)], []])
        self.assertEqual(arp.repair(sock, LOCAL, PHONE, CAMERA), 'phone-unverified')
        self.assertEqual(len(sock.sent), 2)

    def test_wrong_mac_or_address_fails_closed(self):
        sock = FakeSocket([[reply(PHONE, LOCAL)]])
        self.assertEqual(arp.repair(sock, LOCAL, PHONE, CAMERA), 'doorbell-unverified')
        self.assertEqual(len(sock.sent), 1)

    def test_queued_old_reply_cannot_validate_current_association(self):
        sock = FakeSocket([[]])
        sock.queue = [reply(CAMERA, LOCAL)]
        self.assertFalse(arp.verified(sock, LOCAL, CAMERA))

    def test_receive_flood_is_bounded_and_fails_closed(self):
        sock = FakeSocket([])
        sock.queue = [reply(CAMERA, LOCAL)] * 128
        self.assertFalse(arp.verified(sock, LOCAL, CAMERA))
        self.assertEqual(sock.sent, [])

    def test_address_and_mac_validation(self):
        for ip in ('8.8.8.8', '127.0.0.1', '169.254.2.1', '224.1.1.1', '::1'):
            with self.assertRaises(ValueError):
                arp.Peer.parse(ip, '02:11:22:33:44:10')
        for mac in ('ff:ff:ff:ff:ff:ff', '01:11:22:33:44:55', '00:00:00:00:00:00', 'bad'):
            with self.assertRaises(ValueError):
                arp.mac_bytes(mac)

    def test_same_subnet_and_distinct_identities_required(self):
        network = ipaddress.IPv4Network('192.168.40.0/24')
        arp.validate_peers(LOCAL, network, PHONE, CAMERA)
        invalid = [LOCAL, arp.Peer(PHONE.ip, LOCAL.mac),
                   arp.Peer.parse('192.168.41.1', CAMERA.mac.hex(':')),
                   arp.Peer.parse('192.168.40.255', CAMERA.mac.hex(':')),
                   arp.Peer.parse('192.168.40.0', CAMERA.mac.hex(':'))]
        for phone in invalid:
            with self.assertRaises(ValueError):
                arp.validate_peers(LOCAL, network, phone, CAMERA)


if __name__ == '__main__':
    unittest.main()
