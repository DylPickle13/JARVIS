"""Owner-opted-in departure trial. Paired snapshots, outdoor speech, no arrivals."""
import asyncio
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import secrets
import signal
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'jarvisd'))
from jarvisd_core import automatic_voice
import departure
import person_gate
import runtime
import identity_preflight


class HubSession:
    def __init__(self, args, entries):
        self.args = args
        self.entries = entries
        self.device = None
        self.http_client = None
        self.motion_id = self.door_id = None
        self.hub_info = None
        self.person_camera = self.person_binding = None
        self.identity_evidence = None
        self.phase = 'starting'

    async def connect(self):
        from kasa import Discover
        hub_alias, entry, motion, door = self.entries
        settings = departure.cli.load_settings(self.args.env_file)
        if settings.missing:
            raise departure.cli.ControlError(settings.missing)
        host = settings.host if entry['host'] == '@hub' else entry['host']
        with departure.cli.device_lock(hub_alias):
            async with asyncio.timeout(20):
                self.phase = 'discovery'
                self.device = await Discover.discover_single(host, username=settings.username,
                    password=settings.password, discovery_timeout=3, timeout=5)
                device = self.device
                if device is None:
                    raise ConnectionError()
                if device.model != 'H200' or device.device_type.value != 'hub':
                    raise runtime.TrialError('hub_identity_mismatch')
                # Isolated HTTP client: never reuse a socket the hub closed.
                # DeviceConfig.http_client is a supported per-device SDK option;
                # no global patch, installed dependency edit, or TLS/auth change.
                self.http_client = departure.owned_http_client(device)
                original = device.protocol.query
                async def once(request, *args, **kwargs):
                    kwargs['retry_count'] = 0
                    return await original(request, *args, **kwargs)
                device.protocol.query = once
                departure.cli.install_empty_child_lists_compat(device.protocol)
                self.phase = 'identity'
                response = await device.protocol.query({'getDeviceInfo': {
                    'device_info': {'name': ['basic_info']}}})
                self.hub_info = response['getDeviceInfo']['device_info']['basic_info']
                if self.hub_info.get('device_model') != 'H200':
                    raise runtime.TrialError('hub_identity_mismatch')
                self.phase = 'initial_state'
                response = await device.protocol.query({'getChildDeviceList': {
                    'childControl': {'start_index': 0}}})
                self.motion_id, self.door_id = departure.select_child_ids(response, motion, door, departure.cli)

    async def sample(self):
        with departure.cli.device_lock(self.entries[0]):
            self.phase = 'paired_read'
            began = time.monotonic()
            async with asyncio.timeout(2):
                response = await self.device.protocol.query({'getChildDeviceList': {
                    'childControl': {'start_index': 0}}})
            motion, opened = departure.paired_states(response, self.motion_id, self.door_id, departure.cli)
            return departure.Sample(time.monotonic(), datetime.now(timezone.utc),
                                    motion, opened, time.monotonic() - began)

    async def preflight_identity(self, value):
        import security_audio as audio
        self.identity_evidence = None
        entry = departure.cli.registry(self.args.registry)[value['speaker_device']]
        env_file = departure.SECURITY_ROOT / '.env'
        self.phase = 'speaker_identity_preflight'
        with departure.cli.device_lock(self.entries[0]), departure.cli.device_lock(value['speaker_device']):
            before = identity_preflight.binding(entry, env_file)
            try:
                async with asyncio.timeout(3):
                    await audio.identify_doorbell(entry, env_file)
            except TimeoutError:
                return  # No evidence: closure uses the original verified path.
            evidence = identity_preflight.evidence(entry, env_file)
            if evidence['binding'] != before:
                raise runtime.TrialError('preflight_configuration_changed')
            self.identity_evidence = evidence

    async def close(self):
        self.identity_evidence = None
        device, self.device = self.device, None
        if device is not None:
            try:
                await asyncio.wait_for(device.disconnect(), 2)
            except Exception:
                pass
        if self.http_client is not None:
            await self.http_client.close()
            self.http_client = None


def run_speaker(root, attempt, expires):
    """Single fixed worker invocation; any uncertainty latches, never retries."""
    process = subprocess.Popen([sys.executable, str(Path(__file__).with_name('speaker.py')), str(root)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True, start_new_session=True)
    try:
        output, _ = process.communicate(json.dumps({'attempt': attempt, 'expires': expires}), timeout=person_gate.VOICE_ONSET_SECONDS + 14)
        if len(output) > 4096:
            return 'unknown'
        result = json.loads(output)
        outcome = result.get('outcome') if type(result) is dict else None
        return outcome if process.returncode == 0 and outcome in (
            'completed', 'expired_before_play', 'failed_before_play') else 'unknown'
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return 'unknown'
    finally:
        if process.poll() is None:
            # Give the exact child time for existing session-scoped cleanup.
            process.terminate()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=3)


async def deliver(root, journal, sample, *, now=time.time, speaker=run_speaker,
                  reader=None, confirm=person_gate.confirm, require_close=False, voice_revision=None):
    gate = automatic_voice.current()
    voice_revision = voice_revision or (gate.revision if gate else None)
    if not automatic_voice.admitted('doorbell-departure', voice_revision):
        return 'suppressed'
    value = runtime.config(root)
    age = now() - sample.observed_at.timestamp()
    if (not value['enabled'] or journal.blocked or not 0 <= age <= 1
            or sample.read_seconds > 2 or sample.motion is None
            or sample.door_open is not (not require_close)):
        return 'suppressed'
    if not person_gate.permitted(person_gate.effective_policy(root)):
        journal.event('person_gate_unverified')
        journal.flush()
        return 'suppressed'
    attempt = secrets.token_hex(16)
    if not journal.reserve(attempt, now()):
        journal.event('durable_cooldown')
        return 'suppressed'
    # Reservation/storage time is part of the expiry, not free setup time.
    if now() - sample.observed_at.timestamp() > 1:
        journal.finish(attempt, 'expired_before_play')
        return 'expired_before_play'
    expires = sample.observed_at.timestamp() + person_gate.VOICE_ONSET_SECONDS
    try:
        async with asyncio.timeout(person_gate.MAX_WAIT):
            evidence = await confirm(root, reader, attempt, sample.observed_at.timestamp(), expires)
    except TimeoutError:
        evidence = person_gate.Result(False, 'person_event_timeout')
    except Exception:
        # No speaker invocation has occurred. Authentication/schema/identity
        # problems require review, not a fallback or automatic auth recovery.
        journal.state['fault'] = 'person_event_read_requires_review'
        evidence = person_gate.Result(False, 'person_event_unreadable')
    if type(evidence) is not person_gate.Result or type(evidence.confirmed) is not bool:
        journal.state['fault'] = 'person_event_read_requires_review'
        evidence = person_gate.Result(False, 'person_event_unreadable')
    if not evidence.confirmed:
        if evidence.reason in {'person_source_binding_mismatch', 'person_source_unbound', 'person_proof_invalid'}:
            journal.state['fault'] = 'person_event_read_requires_review'
        journal.event(evidence.reason)
        journal.finish(attempt, 'failed_before_play')
        return 'failed_before_play'
    if (not runtime.config(root)['enabled']
            or not automatic_voice.admitted('doorbell-departure', voice_revision)
            or not 0 <= now() - sample.observed_at.timestamp() < person_gate.MAX_WORKER_START_AGE):
        journal.finish(attempt, 'expired_before_play')
        return 'expired_before_play'
    journal.event(evidence.reason)
    identity_preflight.clear(root)
    cached = getattr(reader, 'identity_evidence', None)
    if cached is not None:
        entry = departure.cli.registry(departure.SECURITY_ROOT / 'devices.json')[value['speaker_device']]
        identity_preflight.ticket(root, cached, attempt, expires, entry, departure.SECURITY_ROOT / '.env')
    try:
        runtime.save_json(root / 'voice-admission.json', {'attempt': attempt,
            'expires': expires, 'revision': voice_revision})
    except Exception:
        journal.finish(attempt, 'failed_before_play')
        return 'failed_before_play'
    try:
        outcome = speaker(root, attempt, expires)
    except Exception:
        outcome = 'unknown'
    journal.finish(attempt, outcome)
    return outcome


def transient(exc):
    # Retry only read transport failures, never credentials/identity/schema.
    from kasa.exceptions import _ConnectionError as KasaConnectionError, _RetryableError
    return isinstance(exc, (TimeoutError, ConnectionError, OSError, KasaConnectionError, _RetryableError))


def clear_snapshot(root):
    (root / 'sensor-snapshot.json').unlink(missing_ok=True)
    identity_preflight.clear(root)


def publish_snapshot(root, value, sample):
    """Private dashboard projection, never a source for departure decisions."""
    if (type(sample.motion) is not bool or type(sample.door_open) is not bool
            or not 0 <= sample.read_seconds <= 2):
        clear_snapshot(root)
        return
    runtime.save_json(root / 'sensor-snapshot.json', {
        'version': 1, 'observed_at': sample.observed_at.isoformat(), 'tick': sample.tick,
        'sensors': {value['motion_device']: {'model': 'T100', 'state': sample.motion},
                    value['door_device']: {'model': 'T110', 'state': sample.door_open}}})


def poll_delay(detector):
    # Faster only during an observed qualified open-door session. Reads remain
    # sequential/bounded; never overlap or bypass the shared hub lock.
    return 0.25 if detector.awaiting_close else 2


async def watch(root):
    root = runtime.private_dir(root)
    lock = runtime.singleton(root)
    journal = runtime.Journal(root)
    clear_snapshot(root)
    # Owner-authorized relaxed sequence: both rising edges in one paired read.
    detector = departure.DepartureDetector(allow_simultaneous=True, require_close=True)
    reader = None
    last_pair = None
    busy_reported = False
    read_failures = 0
    voice_revision = None
    try:
        while True:
            value = runtime.config(root)
            if not value['enabled'] or journal.blocked:
                clear_snapshot(root)
                detector.reset()
                if reader is not None:
                    await reader.close()
                    reader = None
                journal.state['health'] = 'fault' if journal.blocked else 'disabled'
                journal.flush()
                await asyncio.sleep(10)
                continue
            reading = True
            try:
                if reader is None:
                    args = departure.parser().parse_args(['observe',
                        '--motion-device', value['motion_device'], '--door-device', value['door_device']])
                    entries = departure.validate_devices(args, departure.cli)
                    devices = departure.cli.registry(args.registry)
                    bell = devices.get(value['speaker_device'])
                    if (not bell or bell.get('model') != 'D235' or not bell.get('host')
                            or bell.get('hub') != entries[0]):
                        raise runtime.TrialError('outdoor_doorbell_required')
                    reader = HubSession(args, entries)
                    await reader.connect()
                    detector.reset()
                    last_pair = None
                    journal.event('connected_baseline_required')
                gate_policy = person_gate.effective_policy(root)
                if (person_gate.permitted(gate_policy) and not gate_policy.get('sensor_only')
                        and reader.person_camera is None):
                    await person_gate.bind(reader)
                sample = await reader.sample()
                reading = False
                read_failures = 0
                publish_snapshot(root, value, sample)
                busy_reported = False
                voice_policy = automatic_voice.current()
                revision = voice_policy.revision if voice_policy else None
                if revision != voice_revision or voice_policy is None or not voice_policy.enabled:
                    detector.reset()  # Never bridge Off/On or reconstruct a suppressed departure.
                voice_revision = revision
                decision = detector.accept(sample)
                if voice_policy is None or not voice_policy.enabled:
                    detector.reset()
                    decision = {'decision': 'suppressed', 'reason': 'automatic_voice_disabled'}
                journal.state['read_count'] += 1
                journal.state['health'] = 'observing' if person_gate.permitted(gate_policy) else 'awaiting_person_verification'
                pair = (sample.motion, sample.door_open)
                # Bounded PRIVATE history of changes, not constant sensor logs.
                if pair != last_pair or decision['decision'] == 'candidate':
                    journal.event(decision['reason'], motion=sample.motion, door_open=sample.door_open)
                    last_pair = pair
                if decision['reason'] == 'qualified_opening_waiting_for_close':
                    await reader.preflight_identity(value)
                if decision['decision'] == 'candidate':
                    journal.state['candidate_count'] += 1
                    await deliver(root, journal, sample, reader=reader, require_close=True,
                                  voice_revision=voice_revision)
                    reader.identity_evidence = None
                    identity_preflight.clear(root)
                    detector.reset()  # No replay of events during speaker work.
                    last_pair = None
                if time.monotonic() - journal.last_save_tick >= 10:
                    journal.flush()
                await asyncio.sleep(poll_delay(detector))
            except Exception as exc:
                clear_snapshot(root)
                detector.reset()
                last_pair = None
                busy = isinstance(exc, departure.cli.ControlError) and str(exc) == 'device_busy'
                # Another hub client can invalidate this session. Reconnect, but
                # do not add the transport-failure 15 s backoff to lock contention.
                # Detector was reset above: never bridge an unobserved sequence.
                if busy:
                    journal.state['health'] = 'waiting'
                    if not busy_reported:
                        journal.event('hub_busy', phase=reader.phase if reader else 'configuration')
                        busy_reported = True
                    journal.flush()
                    if reader is not None:
                        await reader.close()
                        reader = None
                    await asyncio.sleep(0.5)
                    continue
                phase = reader.phase if reader is not None else 'configuration'
                # Only retry reads, never configuration, delivery, or uncertain playback.
                recoverable = (reading and transient(exc) and not journal.blocked and phase in {
                    'discovery', 'identity', 'initial_state', 'paired_read'})
                if recoverable:
                    read_failures += 1
                retry = recoverable and read_failures < 3
                if reader is not None:
                    await reader.close()
                    reader = None
                journal.state['health'] = 'waiting' if retry else 'fault'
                if not retry:
                    journal.state['fault'] = 'sensor_read_requires_review'
                error_type = type(exc).__name__
                allowed = {'TimeoutError', 'ConnectionError', '_ConnectionError', 'AuthenticationError',
                           'OSError', 'ControlError', 'TrialError', 'UnboundLocalError', 'KeyError', 'ValueError', 'AttributeError',
                           'SmartError', 'DeviceError', 'KasaException', '_RetryableError'}
                cause = exc.__cause__
                cause_name = type(cause).__name__ if cause is not None else 'none'
                cause_allowed = {'ClientConnectorError', 'ClientConnectorSSLError', 'ClientOSError',
                                 'ConnectionRefusedError', 'TimeoutError', 'ServerDisconnectedError'}
                os_error = getattr(cause, 'os_error', None)
                errno = getattr(os_error, 'errno', None)
                transport_phase = 'unknown'
                trace = exc.__traceback__
                while trace is not None:
                    name = trace.tb_frame.f_code.co_name
                    if name in {'try_send_handshake1', 'perform_handshake2', 'send_unencrypted',
                                'send_secure_passthrough'}:
                        transport_phase = name
                    trace = trace.tb_next
                from kasa.exceptions import SmartErrorCode
                code = getattr(exc, 'error_code', None)
                # Never log exception messages: they may contain decrypted responses.
                safe_code = code.value if isinstance(code, SmartErrorCode) else None
                journal.event('read_interrupted' if retry else 'sensor_read_requires_review',
                              read_failure_count=read_failures,
                              recovery_exhausted=bool(recoverable and not retry),
                              device_error_code=safe_code,
                              phase=phase, error_type=error_type if error_type in allowed else 'other',
                              cause_type=cause_name if cause_name in cause_allowed else 'other',
                              errno=errno if type(errno) is int else None, transport_phase=transport_phase)
                journal.flush()
                await asyncio.sleep(2 if retry else 15)
    finally:
        clear_snapshot(root)
        if reader is not None:
            await reader.close()
        journal.state['health'] = 'stopped'
        journal.flush()
        os.close(lock)


def main():
    logging.disable(logging.CRITICAL)
    os.umask(0o077)
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    try:
        asyncio.run(watch(runtime.ROOT))
    except KeyboardInterrupt:
        return 0
    except Exception:
        # launchd logs remain fixed/sanitized. Journal failures cannot enable audio.
        print('departure_trial_stopped_requires_review', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
