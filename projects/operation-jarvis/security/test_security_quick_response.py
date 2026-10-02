"""Offline only: synthetic fixtures, muted file conversion, optional loopback peer.

Never load household credentials, discover devices, invoke a real worker upload,
start Tapo/go2rtc, or play sound. Loopback tests use an ephemeral localhost port.
"""
import argparse
import asyncio
from contextlib import nullcontext
from copy import deepcopy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch, call
import wave

import security_cli as cli
import security_quick_response as q
import security_quick_response_transport as transport
import security_quick_response_upload as worker


def capability(**updates):
    value = {'usr_def_audio_support': '1', 'usr_def_audio_max_num': '3',
             'usr_def_audio_max_duration': '15', 'audio_type': 'fixture'}
    value.update(updates)
    return {'quick_response': {'capability': value}}


def audio_capability(**updates):
    return {'audio_capability': {'device_sourcefile': {
        'encode_type': ['G722'], 'sampling_rate': ['16'], **updates}}}


def row(id='1', name='Preset', custom=False, index='0', duration='1000', **extra):
    return dict(id=id, name=name, index=index, duration=duration,
                read_only='0' if custom else '1', **extra)


def listing(*rows):
    return {'quick_response': {'quick_resp_audio': [{f'file_{i}': r} for i, r in enumerate(rows)]}}


def reply(seq, **params):
    return {'type': 'response', 'seq': seq, 'params': {'error_code': 0, **params}}


class MetadataTests(unittest.TestCase):
    def test_native_capabilities_are_bounded_and_explicit(self):
        cap = q.limits(capability())
        self.assertTrue(cap.supported)
        self.assertEqual((cap.max_custom, cap.max_seconds), (3, 15))
        self.assertEqual(cap.public()['uploader_codec'], 'G722')
        self.assertFalse(q.limits(capability(usr_def_audio_support='0')).supported)
        for key, value in [('usr_def_audio_support', True), ('usr_def_audio_support', 'on'),
                           ('usr_def_audio_max_num', True), ('usr_def_audio_max_num', '999'),
                           ('usr_def_audio_max_duration', '-1'), ('usr_def_audio_max_duration', None)]:
            with self.subTest(key=key, value=value), self.assertRaises(cli.ControlError):
                q.limits(capability(**{key: value}))

    def test_explicit_module_and_flat_sdk_shapes(self):
        item = row()
        self.assertEqual(q.entries(listing(item)), [item])
        self.assertEqual(q.entries(listing(item)['quick_response']), [item])
        self.assertEqual(q.limits(capability()['quick_response']).max_seconds, 15)

    def test_malformed_list_rejected_not_guessed(self):
        for value in ({}, {'quick_response': {'quick_resp_audio': {}}},
                      {'quick_resp_audio': [row()]}, {'quick_resp_audio': [None]},
                      listing(row(id='secret\r\nheader')), listing(row(read_only_override='unused', duration=True)),
                      listing(row(), row()), listing(row(name='bad\x00name')),
                      listing(row(index='999')), listing(row(duration='-1'))):
            with self.subTest(value=value), self.assertRaises(cli.ControlError):
                q.entries(value)
        bad = row()
        bad['read_only'] = 'unknown'
        with self.assertRaises(cli.ControlError):
            q.entries(listing(bad))

    def test_capability_errors_identify_only_fixed_field_names(self):
        cases = [({}, 'shape'),
                 ({'capability': []}, 'shape'),
                 (capability(usr_def_audio_support='DO_NOT_PRINT'), 'usr_def_audio_support'),
                 (capability(usr_def_audio_max_num=True), 'usr_def_audio_max_num'),
                 (capability(usr_def_audio_max_duration=None), 'usr_def_audio_max_duration')]
        for value, field in cases:
            with self.subTest(field=field), self.assertRaises(q.MetadataError) as caught:
                q.limits(value)
            self.assertEqual(str(caught.exception), 'invalid_quick_response_metadata')
            details = q.metadata_details(caught.exception)
            self.assertEqual(details, {'metadata_section': 'capability', 'metadata_field': field})
            self.assertNotIn('DO_NOT_PRINT', json.dumps(details))

    def test_list_errors_identify_only_fixed_field_names(self):
        cases = [({}, 'shape'),
                 ({'quick_resp_audio': [{1: row()}]}, 'entry_shape'),
                 (listing(row(name='DO_NOT_PRINT\x00')), 'name'),
                 (listing({**row(), 'read_only': 'DO_NOT_PRINT'}), 'read_only'),
                 (listing(row(id='DO_NOT_PRINT\r\n')), 'id'),
                 (listing(row(index=True)), 'index'),
                 (listing(row(duration=None)), 'duration'),
                 (listing(row(), row()), 'duplicate_id')]
        for value, field in cases:
            with self.subTest(field=field), self.assertRaises(q.MetadataError) as caught:
                q.entries(value)
            details = q.metadata_details(caught.exception)
            self.assertEqual(details, {'metadata_section': 'quick_resp_audio', 'metadata_field': field})
            self.assertNotIn('DO_NOT_PRINT', json.dumps(details))

    def test_file_audio_capabilities_require_exact_g722_16khz_profile(self):
        q.check_audio_capability(audio_capability())
        for value in ({}, None, {'audio_capability': {'device_sourcefile': []}},
                      audio_capability(encode_type=['G711alaw']),
                      audio_capability(encode_type=['OPUS']),
                      audio_capability(encode_type='G722'),
                      audio_capability(encode_type=['G722', True]),
                      audio_capability(sampling_rate=['8']),
                      audio_capability(sampling_rate=[16]),
                      audio_capability(sampling_rate=['16'] * 17)):
            with self.subTest(value=value), self.assertRaisesRegex(cli.ControlError, 'audio_profile_unavailable'):
                q.check_audio_capability(value)

    def test_integer_file_ids_are_accepted_without_mutating_inventory(self):
        rows = [row(id=0), row(id=1, name='Second', extra='UNCHANGED')]
        self.assertEqual(q.entries(listing(*rows)), rows)
        self.assertIs(type(q.entries(listing(*rows))[0]['id']), int)
        self.assertEqual(q.file_identifier(0), '0')
        self.assertEqual(q.file_identifier('opaque_ID'), 'opaque_ID')
        with self.assertRaises(cli.ControlError):
            q.identifier(0)  # Session/header IDs remain string-only.

    def test_invalid_numeric_ids_and_canonical_duplicates_fail_closed(self):
        for value in (True, False, -1, 1.5, q.MAX_FILE_ID + 1, None):
            with self.subTest(value=value), self.assertRaises(q.MetadataError) as caught:
                q.entries(listing(row(id=value)))
            self.assertEqual(caught.exception.metadata_field, 'id')
        with self.assertRaises(q.MetadataError) as caught:
            q.entries(listing(row(id=1), row(id='1', name='Duplicate')))
        self.assertEqual(caught.exception.metadata_field, 'duplicate_id')

    def test_numeric_readback_uses_canonical_keys_but_preserves_raw_field_types(self):
        before = [row(id=1, extra=1)]
        added = row(id=2, name='JARVIS Parcel', custom=True)
        q.verify_added(before, [*before, added], 'JARVIS Parcel', '2')
        q.verify_added(before, [*before, added], 'JARVIS Parcel', 2)
        for mutation in ({**before[0], 'id': '1'}, {**before[0], 'extra': True}):
            with self.subTest(mutation=mutation), self.assertRaises(cli.ControlError):
                q.verify_added(before, [mutation, added], 'JARVIS Parcel', '2')

    def test_metadata_projection_rejects_unapproved_diagnostic_coordinates(self):
        self.assertEqual(q.metadata_details(RuntimeError('DO_NOT_PRINT')), {})
        self.assertEqual(q.metadata_details(cli.ControlError('invalid_quick_response_metadata')), {})
        for section, field in [('capability', 'DO_NOT_PRINT'), ('DO_NOT_PRINT', 'shape'),
                               ('capability', 'id'), ([], 'shape'), ('capability', {})]:
            with self.subTest(section=section, field=field):
                self.assertEqual(q.metadata_details(q.MetadataError(section, field)), {})

    def test_new_only_checks_name_capacity_and_duration(self):
        cap = q.limits(capability())
        q.check_new('JARVIS Parcel', 2, cap, [row()])
        for name, seconds, limits, before in [
                ('Preset', 2, cap, [row()]), ('preset', 2, cap, [row()]),
                ('New', 16, cap, []), ('New', 0, cap, []),
                ('New', 2, q.Limits(False, 3, 15), []),
                ('New', 2, cap, [row(str(i), custom=True) for i in range(3)]),
                ('../bad', 2, cap, []), ('New\nHeader', 2, cap, []),
                (' New', 2, cap, []), ('X' * 33, 2, cap, [])]:
            with self.subTest(name=name, seconds=seconds), self.assertRaises(cli.ControlError):
                q.check_new(name, seconds, limits, before)

    def test_existing_rows_must_remain_identical_and_one_new_id(self):
        before = [row(extra='DO_NOT_PRINT')]
        added = row('2', 'JARVIS Parcel', True, '1', '2000')
        q.verify_added(before, [*before, added], 'JARVIS Parcel', '2')
        mutated = deepcopy(before)
        mutated[0]['index'] = '1'
        for after, id in [([added], '2'), ([*mutated, added], '2'),
                          ([*before, added, row('3')], '2'), ([*before, added], '1'),
                          ([*before, row('2', 'Wrong', True)], '2'),
                          ([*before, row('2', 'JARVIS Parcel')], '2')]:
            with self.subTest(after=after), self.assertRaises(cli.ControlError):
                q.verify_added(before, after, 'JARVIS Parcel', id)


class JournalTests(unittest.TestCase):
    def test_pending_survives_a_new_instance_and_verified_unblocks(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'upload.json'
            journal = q.Journal(path)
            self.assertFalse(journal.blocked())
            journal.write({'phase': 'pending', 'name': 'Fixture'})
            self.assertTrue(q.Journal(path).blocked())
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            journal.write({'phase': 'unknown'})
            self.assertTrue(journal.blocked())
            journal.write({'phase': 'verified'})
            self.assertFalse(journal.blocked())
            self.assertEqual(list(Path(d).glob('.journal-*')), [])

    def test_corruption_symlink_or_world_readable_never_unblocks(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'upload.json'
            for data in ('bad JSON', '{}', '{"phase":"arbitrary"}', ' ' * 16385):
                path.write_text(data)
                path.chmod(0o600)
                with self.assertRaises(cli.ControlError):
                    q.Journal(path).blocked()
            path.write_text('{"phase":"verified"}')
            path.chmod(0o644)
            with self.assertRaises(cli.ControlError):
                q.Journal(path).blocked()
            link = Path(d) / 'link.json'
            link.symlink_to(path)
            with self.assertRaises((cli.ControlError, OSError)):
                q.Journal(link).blocked()


class MPEGTests(unittest.TestCase):
    def test_crc_standard_check_vector(self):
        self.assertEqual(transport.crc32_mpeg(b'123456789').hex(), '0376e6e7')

    @staticmethod
    def packets(data, pid):
        pieces = []
        for pos in range(0, len(data), 188):
            block = data[pos:pos + 188]
            assert len(block) == 188 and block[0] == 0x47
            if ((block[1] & 31) << 8) | block[2] != pid:
                continue
            offset = 4 + (1 + block[4] if block[3] & 0x20 else 0)
            pieces.append(block[offset:])
        return b''.join(pieces)

    def test_payload_pts_pcr_tables_and_continuity(self):
        mux = transport.PCMATS()
        raw = bytes(range(256)) * 4
        first, second = mux.encode(raw), mux.encode(b'\xd5' * 17)
        for data, expected, timestamp in [(first, raw, 0), (second, b'\xd5' * 17, 11520)]:
            self.assertEqual(len(data) % 188, 0)
            pes = self.packets(data, mux.AUDIO_PID)
            self.assertEqual(pes[:4], b'\x00\x00\x01\xc0')
            self.assertEqual(struct.unpack('>H', pes[4:6])[0], len(expected) + 8)
            self.assertEqual(pes[9:14], transport.pts(timestamp))
            self.assertEqual(pes[14:], expected)
            # Independent CRC remainder check on declared PSI sections.
            for pid in (0, mux.PMT_PID):
                psi = self.packets(data, pid)
                section_length = ((psi[2] & 15) << 8) | psi[3]
                section = psi[1:4 + section_length]
                self.assertEqual(transport.crc32_mpeg(section), b'\x00' * 4)
            pmt = self.packets(data, mux.PMT_PID)
            self.assertEqual(pmt[13], 0x93)
            self.assertEqual(pmt[16:18], b'\x80\x00')  # Tapo sample-rate index 8, no ES descriptors.
        all_data = first + second
        counts = [all_data[p + 3] & 15 for p in range(0, len(all_data), 188)
                  if ((all_data[p + 1] & 31) << 8) | all_data[p + 2] == mux.AUDIO_PID]
        self.assertEqual(counts, list(range(len(counts))))

    def test_all_short_final_packet_sizes(self):
        for size in (1, 17, 161, 162, 169, 170, 175, 176, 177, 183, 184, 185, 1024):
            with self.subTest(size=size):
                mux = transport.PCMATS()
                raw = b'\xd5' * size
                encoded = mux.encode(raw)
                self.assertEqual(len(encoded) % 188, 0)
                self.assertEqual(self.packets(encoded, mux.AUDIO_PID)[14:], raw)
        for value in (b'', b'X' * 1025, 'not bytes'):
            with self.assertRaises(cli.ControlError):
                transport.PCMATS().encode(value)

    def test_g722_timestamp_clock_is_not_pcm_sample_rate(self):
        mux = transport.PCMATS()
        for _ in range(8):
            mux.encode(b'\x00' * 1000)
        pes = self.packets(mux.encode(b'\x00' * 100), mux.AUDIO_PID)
        self.assertEqual(pes[9:14], transport.pts(90000))  # Exactly one second.


class PreparationTests(unittest.TestCase):
    @staticmethod
    def args(**changes):
        value = dict(name='JARVIS Fixture', file=None, text=None, text_file=None, gain=100)
        value.update(changes)
        return argparse.Namespace(**value)

    def test_no_urls_empty_files_or_fifos(self):
        with tempfile.TemporaryDirectory() as d:
            empty = Path(d) / 'empty'
            empty.touch()
            fifo = Path(d) / 'fifo'
            os.mkfifo(fifo)
            for value in (empty, fifo, 'https://example.invalid/message.wav'):
                with self.assertRaises(cli.ControlError):
                    q.read_source(value, 100)

    @unittest.skipUnless(shutil.which('ffmpeg'), 'FFmpeg optional offline conversion test')
    def test_actual_g722_conversion_decodes_to_16khz_mono_without_padding(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            source = root / 'synthetic.wav'
            with wave.open(str(source), 'wb') as output:
                output.setparams((2, 2, 16000, 0, 'NONE', 'not compressed'))
                output.writeframes(b'\x00\x00' * 2 * 16000)
            path, count, digest = q.prepare(self.args(file=str(source)), root)
            self.assertEqual(count, 8000)
            decoded = root / 'decoded.wav'
            subprocess.run([shutil.which('ffmpeg'), '-nostdin', '-v', 'error',
                            '-f', 'g722', '-i', str(path), '-c:a', 'pcm_s16le', str(decoded)],
                           check=True, timeout=10, capture_output=True)
            with wave.open(str(decoded), 'rb') as wav:
                self.assertEqual((wav.getnchannels(), wav.getframerate(), wav.getnframes()),
                                 (1, 16000, 16000))
            mux = transport.PCMATS()
            recovered = b''.join(MPEGTests.packets(mux.encode(path.read_bytes()[i:i+1024]),
                                                  mux.AUDIO_PID)[14:]
                                 for i in range(0, count, 1024))
            self.assertEqual(recovered, path.read_bytes())
            self.assertEqual(digest, hashlib.sha256(path.read_bytes()).hexdigest())

    def test_restricted_conversion_and_overlong_clips_fail_not_truncate(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            source = root / 'synthetic.mp3'
            source.write_bytes(b'fixture')
            seen = []
            def convert(command, deadline):
                seen.append(command)
                Path(command[-1]).write_bytes(b'\xd5' * (61 * 8000))
            with patch.object(q, 'run_local', convert), self.assertRaisesRegex(cli.ControlError, 'duration_limit'):
                q.prepare(self.args(file=str(source)), root)
            self.assertIn('file,pipe', seen[0])
            self.assertIn('-format_whitelist', seen[0])
            self.assertEqual(seen[0][seen[0].index('-c:a') + 1], 'g722')
            self.assertEqual(seen[0][seen[0].index('-f') + 1], 'g722')
            self.assertEqual(seen[0][seen[0].index('-ar') + 1], '16000')
            self.assertEqual(seen[0][seen[0].index('-b:a') + 1], '64k')
            self.assertNotIn('adelay', ' '.join(seen[0]))

    def test_speech_bounds_before_synthesis(self):
        with tempfile.TemporaryDirectory() as d, patch.object(q, 'run_local') as runner:
            for text in ('', '   ', 'bad\x00text', 'X' * 2049):
                with self.assertRaises(cli.ControlError):
                    q.prepare(self.args(text=text), Path(d))
            runner.assert_not_called()

    def test_tts_uses_only_existing_jarvis_worker(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            commands = []
            def run(command, deadline):
                commands.append(command)
                Path(command[-1]).write_bytes(b'\xd5' * 8000)
            with patch.object(q, 'run_local', run), patch.object(Path, 'is_file', return_value=True):
                _, count, _ = q.prepare(self.args(text='Synthetic speech fixture.'), root)
            self.assertEqual(count, 8000)
            self.assertTrue(commands[0][1].endswith('security_tts.py'))
            self.assertNotIn('say', commands[0])
            self.assertEqual((root / 'speech.txt').read_text(), 'Synthetic speech fixture.')


class ParentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.addCleanup(patch.stopall)
        patch.object(q, 'ROOT', self.root).start()
        self.adapter = Mock()
        self.adapter.ControlError = cli.ControlError
        self.adapter.registry.return_value = {'bell': {'model': 'D235', 'host': '192.0.2.10', 'hub': 'hub'}}
        self.adapter.device_lock.side_effect = lambda *args: nullcontext()

    def args(self, *words):
        return cli.parser().parse_args(['quick-response', *words])

    def mock_prepare(self, args, root):
        path = root / 'response.g722'
        path.write_bytes(b'\xd5' * 8000)
        return path, 8000, hashlib.sha256(path.read_bytes()).hexdigest()

    def test_confirmation_and_opt_in_before_registry_or_source(self):
        for extra, reason in [([], 'confirmation_required'), (['--confirm'], 'experimental_confirmation_required')]:
            with self.assertRaisesRegex(cli.ControlError, reason):
                q.execute_quick_response(self.args('add', 'bell', '--name', 'Test', '--text', 'Fixture', *extra), self.adapter)
        self.adapter.registry.assert_not_called()

    def test_prepare_never_calls_worker_or_locks_and_cleans_media(self):
        with patch.object(q, 'prepare', side_effect=self.mock_prepare), patch.object(q, 'launch_worker', new_callable=AsyncMock) as launch:
            result = q.execute_quick_response(self.args('prepare', 'bell', '--name', 'Test', '--text', 'Fixture'), self.adapter)
        self.assertEqual(result['result'], 'quick_response_prepared')
        launch.assert_not_called()
        self.adapter.device_lock.assert_not_called()
        self.assertEqual(list((self.root / '.quick-response-runtime/bell').glob('prepare-*')), [])

    def test_upload_routes_one_worker_with_hub_first_locks_no_raw_text(self):
        with patch.object(q, 'prepare', side_effect=self.mock_prepare), patch.object(q, 'launch_worker', new_callable=AsyncMock) as launch:
            launch.return_value = {'result': 'quick_response_added'}
            result = q.execute_quick_response(self.args('add', 'bell', '--name', 'Test', '--text', 'DO_NOT_PRINT', '--confirm', '--experimental'), self.adapter)
        self.assertEqual(result['device'], 'bell')
        self.assertEqual(self.adapter.device_lock.call_args_list, [call('hub'), call('bell')])
        self.assertNotIn('DO_NOT_PRINT', json.dumps(launch.call_args.args[0]))
        self.assertEqual(list((self.root / '.quick-response-runtime/bell').glob('prepare-*')), [])

    def test_pending_journal_no_longer_blocks_new_add(self):
        path = self.root / '.quick-response-runtime/bell'
        path.mkdir(parents=True, mode=0o700)
        path.parent.chmod(0o700)
        q.Journal(path / 'upload.json').write({'phase': 'pending'})
        with patch.object(q, 'prepare', side_effect=self.mock_prepare), patch.object(q, 'launch_worker', new_callable=AsyncMock) as launch:
            launch.return_value = {'result': 'quick_response_added'}
            result = q.execute_quick_response(self.args('add', 'bell', '--name', 'Test', '--file', 'missing', '--confirm', '--experimental'), self.adapter)
        self.assertEqual(result['result'], 'quick_response_added')
        launch.assert_called_once()

    def test_launcher_error_type_translation(self):
        class OtherControlError(Exception):
            pass
        self.adapter.ControlError = OtherControlError
        with self.assertRaisesRegex(OtherControlError, 'confirmation_required'):
            q.execute_quick_response(self.args('add', 'bell', '--name', 'Test', '--text', 'Fixture'), self.adapter)


class FakeSession:
    def __init__(self, id='2', fail=None, journal=None):
        self.id = id
        self.fail = fail
        self.events = []
        self.journal = journal
    async def start(self):
        self.events.append('start')
        if self.fail == 'start': raise RuntimeError('DO_NOT_PRINT')
    async def open_new(self, name):
        self.events.append(('open', name))
        assert self.journal is None or self.journal.blocked()
        if self.fail == 'open': raise RuntimeError('DO_NOT_PRINT')
        return self.id
    async def send_audio(self, data):
        self.events.append(('audio', data))
        if self.fail == 'audio': raise RuntimeError('DO_NOT_PRINT')
        if self.fail == 'cancel': raise asyncio.CancelledError()
    async def finish(self):
        self.events.append('finish')
        if self.fail == 'finish': raise TimeoutError('DO_NOT_PRINT')
    async def close(self):
        self.events.append('close')


class UploadTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.journal = q.Journal(Path(self.temp.name) / 'upload.json')
        self.before = [row(extra='UNCHANGED')]
        self.client = Mock()
        self.client.getEncryptionMethod.return_value = 'sha256'
        self.client.executeFunction.return_value = listing(*self.before, row('2', 'JARVIS Fixture', True, '1'))
        self.entry = {'host': '192.0.2.10', 'model': 'D235', 'hub': 'hub'}
        self.settings = cli.Settings(username='synthetic', password='synthetic')

    async def perform(self, session):
        return await worker.upload(self.client, self.settings, self.entry, 'JARVIS Fixture',
                                   b'\xd5' * 8000, self.before, self.journal,
                                   factory=lambda *args: session, sleep=AsyncMock())

    async def test_one_create_finish_and_readback_no_playback_or_settings(self):
        session = FakeSession(journal=self.journal)
        result = await self.perform(session)
        self.assertEqual(result['result'], 'quick_response_added')
        self.assertEqual(result['playback'], 'not_requested')
        self.assertEqual(result['physical_verification'], 'not_assessed')
        self.assertEqual(self.journal.read()['phase'], 'verified')
        self.assertEqual(sum(isinstance(e, tuple) and e[0] == 'open' for e in session.events), 1)
        self.assertEqual(session.events.count('finish'), 1)
        self.assertEqual(session.events[-1], 'close')
        self.client.executeFunction.assert_called_once_with('getQuickRespList', q.LIST_REQUEST)
        self.assertNotIn('new_file_id', result)

    async def test_integer_inventory_and_reservation_ids_verify_without_replacement(self):
        self.before = [row(id=1, extra='UNCHANGED')]
        self.client.executeFunction.return_value = listing(*self.before, row(id=2, name='JARVIS Fixture', custom=True))
        result = await self.perform(FakeSession(id=2, journal=self.journal))
        self.assertEqual(result['result'], 'quick_response_added')
        self.assertEqual(self.journal.read()['new_file_id'], '2')
        self.assertEqual(self.before[0]['id'], 1)

    async def test_string_reservation_collision_with_integer_inventory_stops_before_audio(self):
        self.before = [row(id=1)]
        session = FakeSession(id='1', journal=self.journal)
        result = await self.perform(session)
        self.assertEqual(result['outcome'], 'unknown')
        self.assertTrue(self.journal.blocked())
        self.assertEqual(session.events, ['start', ('open', 'JARVIS Fixture'), 'close'])

    async def test_all_post_reservation_failures_are_unknown_and_never_retried(self):
        for phase in ('open', 'audio', 'finish', 'cancel'):
            with self.subTest(phase=phase):
                self.journal.path.unlink(missing_ok=True)
                session = FakeSession(fail=phase, journal=self.journal)
                result = await self.perform(session)
                self.assertEqual(result['outcome'], 'unknown')
                self.assertFalse(result['automatic_retry'])
                self.assertNotIn('DO_NOT_PRINT', json.dumps(result))
                self.assertTrue(self.journal.blocked())
                self.assertEqual(sum(isinstance(e, tuple) and e[0] == 'open' for e in session.events), 1)
                self.assertEqual(session.events[-1], 'close')

    def test_upload_diagnostics_only_emit_fixed_coordinates(self):
        cases = [(cli.ControlError('native_upload_rejected'), 'native_upload_rejected'),
                 (cli.ControlError('DO_NOT_PRINT'), 'unexpected_failure'),
                 (RuntimeError('DO_NOT_PRINT'), 'unexpected_failure'),
                 (TimeoutError('DO_NOT_PRINT'), 'timeout'),
                 (asyncio.CancelledError('DO_NOT_PRINT'), 'cancelled'),
                 (ConnectionResetError('DO_NOT_PRINT'), 'connection_closed'),
                 (asyncio.IncompleteReadError(b'DO_NOT_PRINT', 100), 'connection_closed'),
                 (OSError('DO_NOT_PRINT'), 'io_failure'),
                 (ValueError('DO_NOT_PRINT'), 'invalid_data')]
        for error, reason in cases:
            with self.subTest(reason=reason):
                result = worker.upload_failure_details('reservation', error)
                self.assertEqual(result, {'failure_stage': 'reservation', 'failure_reason': reason})
                self.assertNotIn('DO_NOT_PRINT', json.dumps(result))
        for stage in ('DO_NOT_PRINT', None, []):
            self.assertEqual(worker.upload_failure_details(stage, RuntimeError()), {})

    async def test_failure_stages_are_journaled_without_exception_text(self):
        for phase, stage, reason in (
                ('open', 'reservation', 'unexpected_failure'),
                ('audio', 'audio_transfer', 'unexpected_failure'),
                ('finish', 'finish_acknowledgement', 'timeout'),
                ('cancel', 'audio_transfer', 'cancelled')):
            with self.subTest(phase=phase):
                # Synthetic journal only; never clear a real unresolved guard.
                self.journal.path.unlink(missing_ok=True)
                result = await self.perform(FakeSession(fail=phase, journal=self.journal))
                record = self.journal.read()
                self.assertEqual(result['failure_stage'], stage)
                self.assertEqual(result['failure_reason'], reason)
                self.assertEqual(record['failure_stage'], stage)
                self.assertEqual(record['failure_reason'], reason)
                self.assertEqual(record['phase'], 'unknown')
                self.assertNotIn('DO_NOT_PRINT', json.dumps(record))
                self.assertTrue(self.journal.blocked())
                self.client.executeFunction.assert_not_called()

    async def test_reservation_rejection_keeps_unknown_outcome(self):
        session = FakeSession(journal=self.journal)
        session.open_new = AsyncMock(side_effect=cli.ControlError('native_upload_rejected'))
        result = await self.perform(session)
        self.assertEqual(result['result'], 'write_outcome_unknown')
        self.assertEqual(result['failure_stage'], 'reservation')
        self.assertEqual(result['failure_reason'], 'native_upload_rejected')
        self.assertFalse(result['automatic_retry'])
        self.assertTrue(self.journal.blocked())
        session.open_new.assert_awaited_once()
        self.assertEqual(session.events, ['start', 'close'])

    async def test_diagnostic_journal_failure_leaves_prior_pending_guard(self):
        write = self.journal.write
        def write_pending_only(record):
            if record['phase'] == 'unknown':
                raise OSError('DO_NOT_PRINT')
            write(record)
        with patch.object(self.journal, 'write', side_effect=write_pending_only):
            result = await self.perform(FakeSession(fail='open', journal=self.journal))
        self.assertEqual(result['failure_stage'], 'reservation')
        self.assertEqual(self.journal.read()['phase'], 'pending')
        self.assertTrue(self.journal.blocked())

    async def test_journal_write_failure_stages_never_allow_more_audio(self):
        for target, expected_stage, audio_sent in (
                (2, 'reservation_journal', False), (3, 'verification_journal', True)):
            with self.subTest(target=target):
                self.journal.path.unlink(missing_ok=True)
                write = self.journal.write
                count = 0
                def fail_once(record):
                    nonlocal count
                    count += 1
                    if count == target:
                        raise OSError('DO_NOT_PRINT')
                    write(record)
                session = FakeSession(journal=self.journal)
                with patch.object(self.journal, 'write', side_effect=fail_once):
                    result = await self.perform(session)
                self.assertEqual(result['failure_stage'], expected_stage)
                self.assertEqual(result['failure_reason'], 'io_failure')
                self.assertEqual(self.journal.read()['phase'], 'unknown')
                self.assertTrue(self.journal.blocked())
                self.assertEqual(any(isinstance(e, tuple) and e[0] == 'audio'
                                     for e in session.events), audio_sent)
                self.assertEqual(session.events[-1], 'close')

    async def test_auth_failure_before_reservation_does_not_mark_write(self):
        session = FakeSession(fail='start')
        with self.assertRaises(RuntimeError):
            await self.perform(session)
        self.assertFalse(self.journal.path.exists())
        self.assertEqual(session.events, ['start', 'close'])

    async def test_native_returned_existing_id_stops_without_audio_or_finish(self):
        session = FakeSession(id='1', journal=self.journal)
        result = await self.perform(session)
        self.assertEqual(result['outcome'], 'unknown')
        self.assertEqual(session.events, ['start', ('open', 'JARVIS Fixture'), 'close'])
        self.assertEqual(result['failure_stage'], 'reservation_identity')
        self.assertEqual(result['failure_reason'], 'native_upload_returned_existing_id')

    async def test_missing_or_changed_readback_remains_unknown(self):
        for value in (listing(*self.before), listing(row(extra='CHANGED'), row('2', 'JARVIS Fixture', True, '1'))):
            self.journal.path.unlink(missing_ok=True)
            self.client.executeFunction.return_value = value
            result = await self.perform(FakeSession(journal=self.journal))
            self.assertEqual(result['outcome'], 'unknown')
            self.assertTrue(self.journal.blocked())
            self.assertEqual(result['failure_stage'], 'preservation_readback')
            self.assertEqual(result['failure_reason'], 'response_readback_mismatch')


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.addCleanup(patch.stopall)
        patch.object(worker, 'ROOT', self.root).start()
        self.entry = {'model': 'D235', 'host': '192.0.2.10', 'hub': 'hub'}
        patch.object(worker, 'registry', return_value={'bell': self.entry}).start()
        patch.object(worker, 'load_settings', return_value=cli.Settings(username='synthetic', password='synthetic')).start()
        self.client = Mock()
        self.client.basicInfo = {'device_info': {'basic_info': {'device_model': 'D235', 'device_type': 'SMART.TAPODOORBELL'}}}
        self.client.executeFunction.side_effect = [capability(), listing(row(id='DO_NOT_PRINT')), audio_capability()]
        import security_doorbell_direct as d
        self.make = patch.object(d, 'make_client', return_value=self.client).start()
        self.request = {'alias': 'bell', 'registry': 'synthetic', 'entry_hash': q.fingerprint(self.entry),
                        'command': 'status', 'confirm': False, 'experimental': False}

    def add_request(self):
        directory = self.root / '.quick-response-runtime/bell/prepare-fixture'
        directory.mkdir(parents=True, mode=0o700)
        for path in (directory, directory.parent, directory.parent.parent): path.chmod(0o700)
        path = directory / 'response.g722'
        raw = b'\xd5' * 8000
        path.write_bytes(raw)
        path.chmod(0o600)
        return {**self.request, 'command': 'add', 'confirm': True, 'experimental': True,
                'name': 'JARVIS Fixture', 'media_path': str(path), 'media_bytes': len(raw),
                'media_sha256': hashlib.sha256(raw).hexdigest()}

    def test_status_fixed_reads_and_private_projection(self):
        result = worker.run(self.request, 'synthetic')
        self.assertEqual(self.client.executeFunction.call_args_list, [
            call('getQuickRespCapability', q.CAPABILITY_REQUEST), call('getQuickRespList', q.LIST_REQUEST),
            call('getAudioConfig', q.AUDIO_CAPABILITY_REQUEST)])
        self.assertNotIn('DO_NOT_PRINT', json.dumps(result))
        self.assertEqual(result['responses'][0]['name'], 'Preset')
        self.client.close.assert_called_once()

    def test_identity_mismatch_before_auxiliary_reads(self):
        self.client.basicInfo['device_info']['basic_info']['device_model'] = 'C230'
        with self.assertRaisesRegex(cli.ControlError, 'device_identity_mismatch'):
            worker.run(self.request, 'synthetic')
        self.client.executeFunction.assert_not_called()
        self.client.close.assert_called_once()

    def test_request_gates_and_no_arbitrary_rpc_or_override_fields(self):
        request = self.add_request()
        for value in ({**request, 'confirm': 1}, {**request, 'experimental': False},
                      {**request, 'host': '127.0.0.1'}, {**request, 'method': 'playQuickResp'},
                      {**request, 'audio_file_id': '1'}, {**request, 'entry_hash': 'wrong'}):
            with self.subTest(value=value), self.assertRaises(cli.ControlError):
                worker.run(value, 'synthetic')
        self.make.assert_not_called()

    def test_input_digest_and_path_rechecked_before_network(self):
        request = self.add_request()
        for value in ({**request, 'media_sha256': 'wrong'}, {**request, 'media_bytes': True},
                      {**request, 'media_path': '/tmp/outside.alaw'}):
            with self.subTest(value=value), self.assertRaises(cli.ControlError):
                worker.run(value, 'synthetic')
        self.make.assert_not_called()

    def test_native_preflight_rejects_before_media_session(self):
        request = self.add_request()
        self.client.executeFunction.side_effect = [capability(), listing(row(name='JARVIS Fixture')), audio_capability()]
        with patch.object(worker, 'upload', new_callable=AsyncMock) as upload:
            with self.assertRaisesRegex(cli.ControlError, 'name_already_exists'):
                worker.run(request, 'synthetic')
        upload.assert_not_called()

    def test_wrong_file_audio_profile_blocks_before_reservation(self):
        request = self.add_request()
        self.client.executeFunction.side_effect = [capability(), listing(row()),
                                                   audio_capability(encode_type=['OPUS'])]
        with patch.object(worker, 'upload', new_callable=AsyncMock) as upload:
            with self.assertRaisesRegex(cli.ControlError, 'audio_profile_unavailable'):
                worker.run(request, 'synthetic')
        upload.assert_not_called()
        self.assertFalse((self.root / '.quick-response-runtime/bell/upload.json').exists())

    def test_legacy_alaw_file_is_rejected_before_network(self):
        request = self.add_request()
        original = Path(request['media_path'])
        legacy = original.with_suffix('.alaw')
        original.rename(legacy)
        request['media_path'] = str(legacy)
        with self.assertRaisesRegex(cli.ControlError, 'invalid_native_audio_input'):
            worker.run(request, 'synthetic')
        self.make.assert_not_called()

    def test_metadata_failure_precedes_upload_and_pending_journal(self):
        request = self.add_request()
        cases = [([capability(usr_def_audio_support='DO_NOT_PRINT')], 'capability'),
                 ([capability(), listing(row(id='DO_NOT_PRINT\r\n'))], 'quick_resp_audio')]
        for replies, section in cases:
            self.client.executeFunction.side_effect = replies
            with self.subTest(section=section), \
                 patch.object(worker, 'upload', new_callable=AsyncMock) as upload:
                with self.assertRaises(q.MetadataError) as caught:
                    worker.run(request, 'synthetic')
                self.assertEqual(caught.exception.metadata_section, section)
                upload.assert_not_called()
                self.assertFalse((self.root / '.quick-response-runtime/bell/upload.json').exists())

    def test_pending_journal_no_longer_blocks_new_add(self):
        request = self.add_request()
        q.Journal(self.root / '.quick-response-runtime/bell/upload.json').write({'phase': 'pending'})
        with patch.object(worker, 'upload', new_callable=AsyncMock) as upload:
            upload.return_value = {'result': 'quick_response_added', 'name': 'JARVIS Fixture'}
            result = worker.run(request, 'synthetic')
        self.assertEqual(result['result'], 'quick_response_added')
        worker.load_settings.assert_called()
        upload.assert_called_once()

    def test_worker_main_reports_sanitized_metadata_coordinates(self):
        error = q.MetadataError('quick_resp_audio', 'duration')
        with patch.object(worker.sys, 'argv', ['worker', 'synthetic']), \
             patch.object(worker.sys, 'stdin', io.StringIO(json.dumps(self.request))), \
             patch.object(worker, 'run', side_effect=error), \
             patch('sys.stdout', new_callable=io.StringIO) as out:
            code = worker.main()
        result = json.loads(out.getvalue())
        self.assertEqual(code, 2)
        self.assertEqual(result, {'result': 'error', 'reason': 'invalid_quick_response_metadata',
                                 'automatic_retry': False, 'metadata_section': 'quick_resp_audio',
                                 'metadata_field': 'duration'})

    def test_worker_main_sanitizes_unexpected_errors(self):
        with patch.object(sys_module := worker.sys, 'argv', ['worker', 'synthetic']), \
             patch.object(sys_module, 'stdin', io.StringIO(json.dumps(self.request))), \
             patch.object(worker, 'run', side_effect=RuntimeError('DO_NOT_PRINT password host')), \
             patch('sys.stdout', new_callable=io.StringIO) as out:
            code = worker.main()
        self.assertEqual(code, 2)
        self.assertNotIn('DO_NOT_PRINT', out.getvalue())


class DummyAES:
    def encrypt(self, raw): return b'ENC' + raw
    def decrypt(self, raw): return raw[3:]


class DummyTransport:
    def __init__(self):
        self._started = False
        self._key_exchange = 'username="admin" nonce="synthetic" encrypt_type="3"'
        self._aes = DummyAES()
        self._device_boundary = b'--device-stream-boundary--'
        self.client_boundary = b'--client-stream-boundary--'
        self._writer = Mock()
        self._writer.drain = AsyncMock()
        self._writer.wait_closed = AsyncMock()
        self._send_http_request = AsyncMock()
        self._response_handler_task = None
    async def start(self):
        self._started = True
        self._response_handler_task = asyncio.create_task(asyncio.sleep(100))
    async def close(self):
        self._started = False
        if self._response_handler_task:
            self._response_handler_task.cancel()
            await asyncio.gather(self._response_handler_task, return_exceptions=True)


class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.base = DummyTransport()
        self.session = transport.NativeUploadSession(self.base)
        await self.session.start()
        self.addAsyncCleanup(self.session.close)

    async def test_exact_new_and_finish_payloads_and_session_headers(self):
        self.session.next_message = AsyncMock(side_effect=[
            reply(1, session_id='fixture-session', audio_file_id='2', index='0'), reply(2)])
        await self.session.open_new('JARVIS Fixture')
        await self.session.send_audio(transport.PCMATS().encode(b'\xd5' * 100))
        await self.session.finish()
        writes = [c.args[0] for c in self.base._writer.write.call_args_list]
        self.assertEqual(json.loads(writes[0]), {'type': 'request', 'seq': 1, 'params': {
            'method': 'get', 'usr_def_audio': {'name': 'JARVIS Fixture', 'type': 'quick_response',
                                            'audio_config': {'sample_rate': '16', 'encode_type': 'G722'}}}})
        self.assertEqual(json.loads(writes[-1]), {'type': 'request', 'seq': 2, 'params': {'method': 'do', 'finish': 'null'}})
        header = self.base._send_http_request.call_args_list[1].args[1]
        self.assertEqual(header[b'Content-Type'], b'audio/mp2t')
        self.assertEqual(header[b'X-If-Encrypt'], b'1')
        self.assertEqual(header[b'X-Session-Id'], b'fixture-session')
        self.assertTrue(writes[1].startswith(b'ENC'))
        self.assertNotIn('audio_file_id', json.dumps(json.loads(writes[0])))
        self.assertTrue(self.session.finished)

    async def test_integer_file_ids_in_create_progress_and_finish_acknowledgements(self):
        self.session.next_message = AsyncMock(side_effect=[
            reply(1, session_id='fixture-session', audio_file_id=2, index=0),
            reply(2, audio_file_id=2)])
        self.assertEqual(await self.session.open_new('JARVIS Fixture'), '2')
        self.session.notification({'type': 'notification', 'params': {
            'event_type': 'stream_sequence', 'audio_file_id': 2, 'processed_len': 100}})
        await self.session.finish()
        self.assertTrue(self.session.finished)
        self.assertEqual(self.session.processed, 100)

    async def test_integer_file_ids_do_not_weaken_session_id_or_numeric_validation(self):
        values = [reply(1, session_id=2, audio_file_id=2, index=0)]
        values += [reply(1, session_id='fixture-session', audio_file_id=value, index=0)
                   for value in (True, -1, 1.5, q.MAX_FILE_ID + 1)]
        for value in values:
            session = transport.NativeUploadSession(self.base)
            session.next_message = AsyncMock(return_value=value)
            with self.subTest(value=value), self.assertRaises(cli.ControlError):
                await session.open_new('Fixture')

    async def test_rejected_mismatched_or_malformed_create_response(self):
        for value in (reply(999), {'type': 'response', 'seq': 1, 'params': {'error_code': False}},
                      reply(1, session_id='bad\r\nheader'), {'type': 'error', 'message': 'DO_NOT_PRINT'},
                      {'type': 'response', 'seq': 1, 'params': {'error_code': -1}}):
            session = transport.NativeUploadSession(self.base)
            session.next_message = AsyncMock(return_value=value)
            with self.assertRaises(cli.ControlError):
                await session.open_new('Fixture')

    async def test_arbitrary_rpc_and_replacement_never_sent(self):
        for params in ({'method': 'get', 'talk': {}}, {'method': 'do', 'stop': 'null'},
                       {'method': 'get', 'usr_def_audio': {'name': 'Fixture', 'type': 'quick_response', 'audio_file_id': '1'}}):
            with self.assertRaises(cli.ControlError):
                await self.session.request(params)
        self.base._writer.write.assert_not_called()

    async def test_audio_profile_cannot_be_overridden_or_omitted(self):
        for config in (None, {'sample_rate': '8', 'encode_type': 'G711alaw'},
                       {'sample_rate': 16, 'encode_type': 'G722'},
                       {'sample_rate': '16', 'encode_type': 'G722', 'extra': True}):
            audio = {'name': 'Fixture', 'type': 'quick_response'}
            if config is not None:
                audio['audio_config'] = config
            with self.assertRaisesRegex(cli.ControlError, 'unapproved_native_upload_method'):
                await self.session.request({'method': 'get', 'usr_def_audio': audio})
        self.base._writer.write.assert_not_called()

    async def test_finished_notification_not_accepted_as_commit(self):
        with self.assertRaisesRegex(cli.ControlError, 'unexpected_completion'):
            self.session.notification({'type': 'notification', 'params': {'event_type': 'stream_finish'}})

    async def test_valid_progress_and_rejected_unrelated_or_regressing_progress(self):
        self.session.file_id = '2'
        self.session.notification({'type': 'notification', 'params': {'event_type': 'stream_sequence', 'audio_file_id': '2', 'processed_len': 100}})
        self.assertEqual(self.session.processed, 100)
        for id, count in [('1', 101), ('2', 99), ('2', True)]:
            with self.assertRaises(cli.ControlError):
                self.session.notification({'type': 'notification', 'params': {'event_type': 'stream_sequence', 'audio_file_id': id, 'processed_len': count}})

    async def test_missing_or_unknown_encryption_rejected_before_native_request(self):
        for exchange in ('username="none" nonce="synthetic"', 'username="admin" encrypt_type="4"'):
            base = DummyTransport()
            base._key_exchange = exchange
            session = transport.NativeUploadSession(base)
            try:
                with self.assertRaises(cli.ControlError): await session.start()
                base._writer.write.assert_not_called()
            finally:
                await session.close()

    def test_headers_are_bounded_json_only_and_no_hmac_downgrade(self):
        good = b'Content-Type: application/json\r\nContent-Length: 12\r\nX-If-Encrypt: 0\r\n\r\n'
        self.assertEqual(transport.headers(good)[1:], (12, False))
        for value in (good.replace(b'12', b'-1'), good.replace(b'12', b'999999999'),
                      good.replace(b'application/json', b'video/mp2t'),
                      good + b'X-Data-Hmac: fixture\r\n', good + b'Content-Length: 12\r\n',
                      b'X' * 16385):
            with self.subTest(value=value[:80]), self.assertRaises(cli.ControlError):
                transport.headers(value)


@unittest.skipUnless(importlib.util.find_spec('pytapo'), 'isolated archive SDK only')
class LoopbackHandshakeTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_pinned_digest_aes_and_native_messages_against_local_fake_peer(self):
        from pytapo.media_stream.session import HttpMediaSession
        from pytapo.media_stream.crypto import AESHelper
        from pytapo.const import EncryptionMethod
        password = b'synthetic-local-test-password'
        exchange = b'username="admin" nonce="1234567890123456" encrypt_type="3"'
        aes = AESHelper.from_keyexchange_and_password(exchange, password, b'', EncryptionMethod.SHA256)
        observed = []
        failure = []
        completed = asyncio.Event()
        async def read_part(reader):
            await reader.readuntil(b'--client-stream-boundary--')
            block = await reader.readuntil(b'\r\n\r\n')
            fields = dict(line.split(':', 1) for line in block.decode().strip().split('\r\n'))
            fields = {k.lower(): v.strip() for k, v in fields.items()}
            body = await reader.readexactly(int(fields['content-length']))
            if fields.get('x-if-encrypt') == '1': body = aes.decrypt(body)
            return fields, body
        async def send(writer, value):
            data = aes.encrypt(json.dumps(value).encode())
            writer.write(b'----device-stream-boundary--\r\nContent-Type: application/json\r\n'
                         + f'Content-Length: {len(data)}\r\nX-If-Encrypt: 1\r\n\r\n'.encode() + data + b'\r\n')
            await writer.drain()
        async def peer(reader, writer):
            try:
                await reader.readuntil(b'\r\n\r\n')
                writer.write(b'HTTP/1.1 401 Unauthorized\r\nWWW-Authenticate: Digest realm="fixture",nonce="nonce",opaque="opaque"\r\n\r\n')
                await writer.drain()
                request = (await reader.readuntil(b'\r\n\r\n')).decode()
                # Parse the real SDK digest, independently recompute its response.
                auth = {k: quoted or bare for k, quoted, bare in re.findall(r'(\w+)=(?:"([^"]*)"|([^,\s]+))', request)}
                hashed = hashlib.sha256(password).hexdigest().upper()
                ha1 = hashlib.md5(f'admin:fixture:{hashed}'.encode()).hexdigest()
                ha2 = hashlib.md5(b'POST:/stream').hexdigest()
                expected = hashlib.md5(f'{ha1}:nonce:00000001:{auth["cnonce"]}:auth:{ha2}'.encode()).hexdigest()
                self.assertEqual(auth['response'], expected)
                writer.write(b'HTTP/1.1 200 OK\r\nContent-Type: multipart/mixed;boundary=--device-stream-boundary--\r\nKey-Exchange: ' + exchange + b'\r\n\r\n')
                await writer.drain()
                fields, body = await read_part(reader)
                create = json.loads(body)
                observed.append(create)
                self.assertEqual(create['params'], {'method': 'get', 'usr_def_audio': {
                    'name': 'JARVIS Fixture', 'type': 'quick_response',
                    'audio_config': {'sample_rate': '16', 'encode_type': 'G722'}}})
                await send(writer, reply(create['seq'], session_id='fixture-session', audio_file_id='2', index='1'))
                fields, body = await read_part(reader)
                self.assertEqual(fields['content-type'], 'audio/mp2t')
                self.assertEqual(fields['x-if-encrypt'], '1')
                self.assertEqual(fields['x-session-id'], 'fixture-session')
                self.assertEqual(MPEGTests.packets(body, transport.PCMATS.AUDIO_PID)[14:], b'\xd5' * 100)
                fields, body = await read_part(reader)
                finish = json.loads(body)
                observed.append(finish)
                self.assertEqual(finish['params'], {'method': 'do', 'finish': 'null'})
                self.assertEqual(fields['x-session-id'], 'fixture-session')
                await send(writer, reply(finish['seq']))
            except BaseException as exc:
                failure.append(exc)
            finally:
                writer.close()
                await writer.wait_closed()
                completed.set()
        server = await asyncio.start_server(peer, '127.0.0.1', 0)
        port = server.sockets[0].getsockname()[1]
        base = HttpMediaSession('127.0.0.1', password.decode(), '', EncryptionMethod.SHA256, port=port, query_params={})
        session = transport.NativeUploadSession(base)
        try:
            async with asyncio.timeout(10):
                await session.start()
                await session.open_new('JARVIS Fixture')
                await session.send_audio(transport.PCMATS().encode(b'\xd5' * 100))
                await session.finish()
                await completed.wait()
            self.assertEqual(failure, [])
            self.assertEqual(len(observed), 2)
            self.assertTrue(session.finished)
        finally:
            await session.close()
            server.close()
            await server.wait_closed()


if __name__ == '__main__':
    unittest.main()
