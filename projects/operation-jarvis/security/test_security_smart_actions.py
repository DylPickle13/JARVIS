"""Offline Smart Actions tests. No live cloud calls or device actions."""
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock

import security_cli as cli
import security_smart_actions as s


def rule(manual=False, enabled=False):
    return {'id': 'test0001', 'name': 'Offline rule', 'enabled': enabled,
            'triggerSetting': {'isManual': manual, 'things': [{'opaque': 'preserve-me'}]},
            'actionSetting': {'things': [{'thingName': 'fake-device', 'stateDesired': {'on': True}}]},
            'futureField': {'keep': [1, 2, 3]}}


def request(op, before=None, **kwargs):
    before = before or rule()
    return dict(operation=op, confirm=True, ref=s.reference(before), revision=s.revision(before), **kwargs)


class FakeCloud:
    def __init__(self, rules):
        self.rules = copy.deepcopy(rules)
        self.writes = []
        self.fail_write = False
        self.fail_readback = False
        self.mismatch = False

    def listing(self):
        if self.writes and self.fail_readback:
            raise OSError('SENSITIVE URL TOKEN')
        return copy.deepcopy(self.rules)

    def api(self, method, path, body=None):
        self.writes.append((method, path, copy.deepcopy(body)))
        if self.fail_write:
            raise OSError('SENSITIVE URL TOKEN')
        if method == 'PUT':
            self.rules = [r for r in self.rules if r['id'] != body['id']] + [copy.deepcopy(body)]
            if self.mismatch:
                self.rules[-1]['futureField'] = 'changed unexpectedly'
        elif method == 'DELETE':
            self.rules = [r for r in self.rules if r['id'] != path.rsplit('/', 1)[-1]]
        return {}


class SmartTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.patches = [patch.object(s, 'STORAGE', self.root / 'private'),
                        patch.object(cli, 'ROOT', self.root)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.temp.cleanup()

    def test_list_sanitizes_device_details_and_returns_revision(self):
        r = s.run({'operation': 'list'}, FakeCloud([rule()]))
        text = json.dumps(r)
        self.assertNotIn('fake-device', text)
        self.assertNotIn('test0001', text)
        self.assertEqual(r['rules'][0]['revision'], s.revision(rule()))

    def test_show_is_private_exact_editable_rule(self):
        r = s.run(request('show'), FakeCloud([rule()]))
        p = self.root / r['private_file']
        self.assertEqual(json.loads(p.read_text()), rule())
        self.assertEqual(p.stat().st_mode & 0o777, 0o600)
        self.assertEqual(p.parent.stat().st_mode & 0o777, 0o700)

    def test_rename_preserves_all_other_fields(self):
        cloud = FakeCloud([rule()])
        r = s.run(request('rename', name='New name'), cloud)
        self.assertEqual(r['result'], 'write_verified')
        expected = rule(); expected['name'] = 'New name'
        self.assertEqual(cloud.rules, [expected])
        self.assertEqual(len(cloud.writes), 1)
        backup = json.loads((self.root / r['private_backup']).read_text())
        self.assertEqual(backup['before'], rule())

    def test_create_generates_id_and_checks_disabled_by_default_policy(self):
        value = rule(); del value['id']
        cloud = FakeCloud([])
        r = s.run({'operation': 'create', 'confirm': True, 'rule': value}, cloud)
        self.assertEqual(r['result'], 'write_verified')
        self.assertRegex(cloud.rules[0]['id'], r'^[A-Za-z0-9]{8}$')
        self.assertFalse(cloud.rules[0]['enabled'])
        value['enabled'] = True
        with self.assertRaisesRegex(s.SmartError, 'active_rule_confirmation_required'):
            s.run({'operation': 'create', 'confirm': True, 'rule': value}, FakeCloud([]))

    def test_create_rejects_existing_id(self):
        with self.assertRaisesRegex(s.SmartError, 'omit_id'):
            s.run({'operation': 'create', 'confirm': True, 'rule': rule()}, FakeCloud([]))

    def test_update_full_rules_and_unknown_fields(self):
        value = rule(); value['actionSetting'] = {'things': []}; value['futureField']['keep'].append(4)
        cloud = FakeCloud([rule()])
        r = s.run(request('update', rule=value), cloud)
        self.assertEqual(r['result'], 'write_verified')
        self.assertEqual(cloud.rules, [value])

    def test_update_refuses_id_change_and_unapproved_active_edit(self):
        value = rule(); value['id'] = 'other'
        with self.assertRaisesRegex(s.SmartError, 'id_change'):
            s.run(request('update', rule=value), FakeCloud([rule()]))
        active = rule(enabled=True)
        with self.assertRaisesRegex(s.SmartError, 'active_rule_confirmation'):
            s.run(request('update', before=active, rule=rule()), FakeCloud([active]))

    def test_rename_active_requires_extra_approval(self):
        active = rule(enabled=True)
        with self.assertRaisesRegex(s.SmartError, 'active_rule_confirmation'):
            s.run(request('rename', before=active, name='New'), FakeCloud([active]))
        cloud = FakeCloud([active])
        r = s.run(request('rename', before=active, name='New', allow_active=True), cloud)
        self.assertEqual(r['result'], 'write_verified')

    def test_enable_disable(self):
        cloud = FakeCloud([rule()])
        r = s.run(request('enable'), cloud)
        self.assertEqual(r['result'], 'write_verified')
        self.assertTrue(cloud.rules[0]['enabled'])
        before = copy.deepcopy(cloud.rules[0])
        r = s.run(request('disable', before=before), cloud)
        self.assertEqual(r['result'], 'write_verified')
        self.assertFalse(cloud.rules[0]['enabled'])

    def test_delete_backed_up_and_verified(self):
        cloud = FakeCloud([rule()])
        r = s.run(request('delete'), cloud)
        self.assertEqual(r['result'], 'write_verified')
        self.assertEqual(cloud.rules, [])
        self.assertEqual(cloud.writes[0][0], 'DELETE')

    def test_execute_requires_separate_approval_and_shortcut(self):
        shortcut = rule(manual=True)
        with self.assertRaisesRegex(s.SmartError, 'physical_actions'):
            s.run(request('execute', before=shortcut), FakeCloud([shortcut]))
        with self.assertRaisesRegex(s.SmartError, 'requires_shortcut'):
            s.run(request('execute', allow_actions=True), FakeCloud([rule()]))
        cloud = FakeCloud([shortcut])
        r = s.run(request('execute', before=shortcut, allow_actions=True), cloud)
        self.assertEqual(r['result'], 'execution_acknowledged')
        self.assertEqual(r['physical_outcome'], 'not_verified')
        self.assertTrue(cloud.writes[0][1].endswith('/exec'))

    def test_confirmation_before_network_or_backup(self):
        for op in s.WRITES:
            cloud = FakeCloud([rule()])
            with self.assertRaisesRegex(s.SmartError, 'confirmation_required'):
                s.run(dict(operation=op), cloud)
            self.assertEqual(cloud.writes, [])
        self.assertFalse((self.root / 'private').exists())

    def test_revision_conflict_has_no_writes(self):
        req = request('rename', name='Updated'); req['revision'] = '0' * 64
        cloud = FakeCloud([rule()])
        with self.assertRaisesRegex(s.SmartError, 'revision_conflict'):
            s.run(req, cloud)
        self.assertEqual(cloud.writes, [])

    def test_noop_does_not_write(self):
        cloud = FakeCloud([rule()])
        self.assertEqual(s.run(request('disable'), cloud)['result'], 'unchanged')
        self.assertEqual(cloud.writes, [])

    def test_ambiguous_write_and_readback_no_retry_no_exception_leaks(self):
        for kind in ('fail_write', 'fail_readback', 'mismatch'):
            cloud = FakeCloud([rule()]); setattr(cloud, kind, True)
            r = s.run(request('rename', name='Updated'), cloud)
            self.assertEqual(r['outcome'], 'unknown')
            self.assertEqual(len(cloud.writes), 1)
            self.assertNotIn('SENSITIVE', json.dumps(r))

    def test_other_rule_changes_are_not_reported_verified(self):
        cloud = FakeCloud([rule()])
        orig = cloud.api
        def write(*args):
            orig(*args)
            another = rule(); another['id'] = 'test0002'; cloud.rules.append(another)
        cloud.api = write
        self.assertEqual(s.run(request('rename', name='New'), cloud)['outcome'], 'unknown')

    def test_schema_and_name_checks(self):
        for name in ('', 'x\n', 'x\x1b', 'x'*65):
            with self.assertRaises(s.SmartError): s.valid_name(name)
        for field, val in [('enabled', 1), ('triggerSetting', {'isManual': 1}), ('actionSetting', [])]:
            r = rule(); r[field] = val
            with self.assertRaises(s.SmartError): s.validate_rule(r)
        for text in ('{"x":1,"x":2}', '{"x":NaN}'):
            with self.assertRaises(s.SmartError): s.parse_json(text)

    def test_ids_reject_url_path_traversal(self):
        for value in ('..', '../other', '%2fother', 'x/y', 'x?delete=true'):
            r = rule(); r['id'] = value
            with self.assertRaises(s.SmartError):s.validate_rule(r)

    def test_parent_timeout_returns_unknown_without_retry(self):
        args = cli.parser().parse_args(['smart-actions', 'delete', s.reference(rule()),
            '--revision', s.revision(rule()), '--confirm'])
        adapter = Mock()
        adapter.device_lock.return_value = contextlib.nullcontext()
        adapter.load_settings.return_value.password = 'fake-password'
        with patch.object(s, 'private_read', return_value=b'{"username":"fake@example.invalid"}'), \
                patch.object(s.subprocess, 'run', side_effect=s.subprocess.TimeoutExpired('worker', 110)) as invoke:
            r = s.execute_smart_actions(args, adapter)
        self.assertEqual(r['outcome'], 'unknown')
        self.assertEqual(invoke.call_count, 1)
        self.assertNotIn('fake-password', json.dumps(r))

    def test_error_and_unknown_exit_codes(self):
        for response, expected in (({'result': 'error', 'reason': 'cloud_mfa_required'}, 2),
                                   ({'result': 'write_outcome_unknown', 'outcome': 'unknown'}, 3)):
            with patch.object(s, 'execute_smart_actions', return_value=response), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cli.control_main(['--json', 'smart-actions', 'list']), expected)

    def test_private_files_symlinks_modes_and_limits(self):
        p = self.root/'rule.json'; p.write_text('{}'); p.chmod(0o644)
        with self.assertRaises(s.SmartError):s.private_read(p)
        p.chmod(0o600)
        self.assertEqual(s.private_read(p), b'{}')
        with self.assertRaises(s.SmartError):s.private_read(p, 1)
        link = self.root/'link'; link.symlink_to(p)
        with self.assertRaises(OSError):s.private_read(link)

    def test_backup_storage_refuses_symlink(self):
        target = self.root/'other'; target.mkdir()
        (self.root/'private').symlink_to(target)
        with self.assertRaises(s.SmartError):s.snapshot(rule(), 'rule')

    def test_parser_all_commands_and_confirmation_precedes_credentials(self):
        for op in s.OPERATIONS:
            argv = ['smart-actions', op]
            if op not in ('list', 'create'):argv += [s.reference(rule())]
            if op in s.WRITES - {'create'}:argv += ['--revision', s.revision(rule())]
            if op in ('create', 'update'):argv += ['--file', 'does-not-exist']
            if op == 'rename':argv += ['--name', 'New']
            args = cli.parser().parse_args(argv)
            self.assertEqual(args.smart_operation, op)
            if op in s.WRITES:
                with patch.object(s, 'private_read', side_effect=AssertionError('credentials read')):
                    with self.assertRaisesRegex(cli.ControlError, 'confirmation_required'):
                        s.execute_smart_actions(args)

    def test_cloud_error_codes_strings_nested(self):
        self.assertEqual(s.cloud_code({'error_code': 0, 'result': {'errorCode': '-20601'}}), -20601)
        self.assertEqual(s.cloud_code({}), 0)
        with self.assertRaises(s.SmartError):s.cloud_code({'error_code': 'oops'})

    def test_cloud_host_allowlist(self):
        for url in ('http://a.tplinknbu.com', 'https://evil.test', 'https://a.tplinknbu.com@evil.test',
                    'https://a.tplinknbu.com/path', 'https://a.tplinknbu.com:444', 'https://a.tplinknbu.com?x=y'):
            with self.assertRaises(s.SmartError):s.Cloud.base(url, 'tplinknbu.com')
        self.assertEqual(s.Cloud.base('https://a.tplinknbu.com/', 'tplinknbu.com'), 'https://a.tplinknbu.com')

    def test_transport_one_write_only_and_endpoint_allowlist(self):
        c = s.Cloud.__new__(s.Cloud); c.token = 'fake'; c.endpoint = 'https://fake.tplinknbu.com'
        c.term = 'fake'; c.write_started = False; c.send = Mock(return_value={})
        with self.assertRaises(s.SmartError):c.api('POST', '/v1/other')
        c.api('PUT', '/v1/smarts', rule())
        with self.assertRaisesRegex(s.SmartError, 'second_write'):
            c.api('PUT', '/v1/smarts', rule())
        c.api('GET', '/v1/smarts?page=0&pageSize=20')
        self.assertEqual(c.send.call_count, 2)

    def test_listing_bounds_duplicates_and_page_consistency(self):
        c = s.Cloud.__new__(s.Cloud)
        for payload in ({'page': 0, 'total': 101, 'data': []},
                        {'page': 0, 'total': 2, 'data': [rule(), rule()]},
                        {'page': 1, 'total': 1, 'data': [rule()]},
                        {'page': 0, 'total': 2, 'data': []}):
            c.api = Mock(return_value=payload)
            with self.assertRaises(s.SmartError):c.listing()
        c.api = Mock(return_value={'page': 0, 'total': 1, 'data': [rule()]})
        self.assertEqual(c.listing(), [rule()])

    def test_rpc_signs_exact_bytes_and_does_not_log_password(self):
        c = s.Cloud.__new__(s.Cloud); c.keys = {'TAPO_SECRET_KEY': 'fake', 'TAPO_ACCESS_KEY': 'fake'}
        c.term = 'fake'; c.send = Mock(return_value={})
        c.rpc('/api/v2/account/login', {'cloudPassword': 'not-a-real-password'})
        args = c.send.call_args.args
        self.assertEqual(args[0], 'POST')
        self.assertNotIn('not-a-real-password', args[1])
        self.assertIn('X-Authorization', args[2])
        with self.assertRaises(s.SmartError):c.rpc('/', {'method': 'deleteAccount'})


if __name__ == '__main__':
    unittest.main()
