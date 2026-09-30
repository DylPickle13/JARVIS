#!/usr/bin/env python3
"""Linux-only, two-device ARP lookup repair. No listener, camera RPC or video.

Validate both configured IP/MAC pairs using ordinary directed ARP requests,
then relay the handset's lookup to the doorbell as a directed request. The
Ethernet source remains this host (never move another device's bridge entry).
The doorbell, not this process, supplies its real ARP reply to the handset.
Requires CAP_NET_RAW; does not modify routes, neighbours or camera settings.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import fcntl
import ipaddress
import logging
import re
import signal
import socket
import struct
import time

ARP = 0x0806
HEADER = struct.pack('!HHBB', 1, 0x0800, 6, 4)
LOG = logging.getLogger('jarvis-monitor-arp')


def mac_bytes(value: str) -> bytes:
    if not re.fullmatch(r'(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}', value):
        raise ValueError('invalid MAC address')
    result = bytes.fromhex(value.replace(':', ''))
    if result == b'\x00' * 6 or result[0] & 1:
        raise ValueError('MAC must be nonzero unicast')
    return result


@dataclass(frozen=True)
class Peer:
    ip: ipaddress.IPv4Address
    mac: bytes

    @classmethod
    def parse(cls, ip: str, mac: str) -> 'Peer':
        address = ipaddress.IPv4Address(ip)
        if not any(address in ipaddress.IPv4Network(n) for n in
                   ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16')):
            raise ValueError('peer address must be RFC1918 IPv4')
        return cls(address, mac_bytes(mac))


def request(ether_source: bytes, sender: Peer, target: Peer) -> bytes:
    """Directed Ethernet request; ARP sender may be the verified handset."""
    return (target.mac + ether_source + struct.pack('!H', ARP) + HEADER +
            struct.pack('!H', 1) + sender.mac + sender.ip.packed +
            b'\x00' * 6 + target.ip.packed)


def is_reply(frame: bytes, source: Peer, destination: Peer) -> bool:
    # Reject foreign, proxy, outgoing, malformed and inconsistent identities.
    return (len(frame) >= 42 and frame[:6] == destination.mac and
            frame[6:12] == source.mac and frame[12:14] == b'\x08\x06' and
            frame[14:20] == HEADER and frame[20:22] == b'\x00\x02' and
            frame[22:28] == source.mac and frame[28:32] == source.ip.packed and
            frame[32:38] == destination.mac and frame[38:42] == destination.ip.packed)


def local_peer(interface: str) -> tuple[Peer, ipaddress.IPv4Network]:
    if not re.fullmatch(r'[a-zA-Z0-9_.-]{1,15}', interface):
        raise ValueError('invalid interface')
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as control:
        name = struct.pack('256s', interface.encode())
        address = socket.inet_ntoa(fcntl.ioctl(control, 0x8915, name)[20:24])
        netmask = socket.inet_ntoa(fcntl.ioctl(control, 0x891b, name)[20:24])
        mac = fcntl.ioctl(control, 0x8927, name)[18:24].hex(':')
    peer = Peer.parse(address, mac)
    return peer, ipaddress.IPv4Network(f'{address}/{netmask}', strict=False)


def validate_peers(local: Peer, network: ipaddress.IPv4Network,
                   phone: Peer, doorbell: Peer) -> None:
    peers = (local, phone, doorbell)
    if len({p.ip for p in peers}) != 3 or len({p.mac for p in peers}) != 3:
        raise ValueError('IP and MAC identities must be distinct')
    for peer in peers:
        if peer.ip not in network or peer.ip in (network.network_address, network.broadcast_address):
            raise ValueError('all peers must be usable addresses on the current interface subnet')


def verified(sock, local: Peer, peer: Peer, timeout: float = 1.0) -> bool:
    # Do not use a queued reply from an earlier cycle as current validation.
    sock.setblocking(False)
    for _ in range(128):
        try:
            sock.recv(2048)
        except BlockingIOError:
            break
    else:
        return False  # Receive flood: fail closed, rather than drain forever.
    sock.settimeout(timeout)
    sock.send(request(local.mac, local, peer))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        sock.settimeout(max(0.001, deadline - time.monotonic()))
        try:
            frame = sock.recv(2048)
        except socket.timeout:
            return False
        if is_reply(frame, peer, local):
            return True
    return False


def repair(sock, local: Peer, phone: Peer, doorbell: Peer) -> str:
    # No emission on behalf of a peer until BOTH current associations answer.
    if not verified(sock, local, doorbell):
        return 'doorbell-unverified'
    if not verified(sock, local, phone):
        return 'phone-unverified'
    sock.send(request(local.mac, phone, doorbell))
    # Dispatch is not evidence of handset receipt or decoded-video liveness.
    return 'lookup-relayed'


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--interface', required=True)
    parser.add_argument('--phone-ip', required=True)
    parser.add_argument('--phone-mac', required=True)
    parser.add_argument('--doorbell-ip', required=True)
    parser.add_argument('--doorbell-mac', required=True)
    parser.add_argument('--interval', type=float, default=10)
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    if not 5 <= args.interval <= 300:
        parser.error('interval must be 5–300 seconds')
    try:
        phone = Peer.parse(args.phone_ip, args.phone_mac)
        doorbell = Peer.parse(args.doorbell_ip, args.doorbell_mac)
        local, network = local_peer(args.interface)
        validate_peers(local, network, phone, doorbell)
    except (ValueError, OSError):
        parser.error('invalid identity, subnet or interface configuration')
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    stopping = False

    def stop(signum, frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    last_status = None
    last_log = 0.0
    relayed = 0
    try:
        with socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(ARP)) as sock:
            sock.bind((args.interface, 0))
            while not stopping:
                began = time.monotonic()
                try:
                    # Re-read interface addressing every cycle; never trust a stale local IP.
                    local, network = local_peer(args.interface)
                    validate_peers(local, network, phone, doorbell)
                    status = repair(sock, local, phone, doorbell)
                except (ValueError, OSError):
                    status = 'interface-unavailable'
                if status == 'lookup-relayed':
                    relayed += 1
                if status != last_status or began - last_log >= 300:
                    LOG.info('status=%s relayed=%d', status, relayed)
                    last_status, last_log = status, began
                if args.once:
                    return 0 if status == 'lookup-relayed' else 1
                deadline = began + args.interval
                while not stopping and time.monotonic() < deadline:
                    time.sleep(max(0.0, min(0.2, deadline - time.monotonic())))
    except OSError:
        LOG.error('raw ARP socket unavailable; requires Linux CAP_NET_RAW')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
