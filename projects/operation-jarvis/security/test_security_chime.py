"""Offline chime gates, routing, timeout and discovery selection checks."""
from contextlib import nullcontext
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

import security_cli as cli
import security_chime as chime


class ChimeTests(unittest.TestCase):
    def args(self,*args):
        return cli.parser().parse_args(['chime',*args])

    def discovered(self,host='192.0.2.1'):
        return {'meta':{'ip':host},'discovery_response':{'result':{
            'device_model':'D100C(US)','device_type':'SMART.TAPOCHIME',
            'mgt_encrypt_schm':{'encrypt_type':'TPAP','http_port':80},
            'tpap':{'pake':[2],'tls':0}}}}

    def test_no_confirmation_means_no_network_or_credentials(self):
        for operation in ('ring','stop'):
            with patch.object(chime,'discover',new_callable=AsyncMock) as discover, \
                    patch.object(cli,'load_settings') as settings:
                with self.assertRaisesRegex(cli.ControlError,'confirmation_required'):
                    chime.execute_chime(self.args(operation))
                discover.assert_not_awaited();settings.assert_not_called()

    def test_ring_bounds_and_safe_defaults(self):
        args=self.args('ring','--confirm')
        self.assertEqual((args.tone,args.volume,args.seconds),('1',1,1))
        chime.validate(args)
        for key,value in [('volume',4),('seconds',0),('tone','file.mp3')]:
            invalid=self.args('ring','--confirm');setattr(invalid,key,value)
            with self.assertRaisesRegex(cli.ControlError,'invalid_chime_ring'):
                chime.validate(invalid)

    def test_discovery_rejects_ambiguity_and_wrong_protocol(self):
        self.assertEqual(chime.discovery_host([self.discovered(),self.discovered()]),'192.0.2.1')
        wrong=self.discovered();wrong['discovery_response']['result']['tpap']['pake']=[0]
        for rows in ([],[wrong],[self.discovered(),self.discovered('192.0.2.2')]):
            with self.assertRaisesRegex(cli.ControlError,'chime_missing_ambiguous_or_unsupported'):
                chime.discovery_host(rows)

    def test_status_lock_order_and_invoke(self):
        with patch.object(cli,'device_lock',side_effect=lambda _:nullcontext()) as locks, \
                patch.object(chime,'discover',new_callable=AsyncMock,return_value='192.0.2.1'), \
                patch.object(cli,'load_settings',return_value=Mock(username='synthetic',password='synthetic')), \
                patch.object(chime,'invoke',return_value={'result':'read_succeeded'}) as invoke:
            chime.execute_chime(self.args('status'))
        self.assertEqual([c.args[0] for c in locks.call_args_list],['hub','front-doorbell','chime-tpap-probe'])
        invoke.assert_called_once()

    def test_timeout_never_replays_and_is_unknown_for_actions(self):
        with patch.object(chime.shutil,'which',return_value='/bin/node'), \
                patch.object(Path,'is_file',return_value=True), \
                patch.object(chime.subprocess,'run',side_effect=subprocess.TimeoutExpired('node',30)) as run:
            with self.assertRaisesRegex(cli.ControlError,'chime_action_outcome_unknown'):
                chime.invoke(self.args('ring','--confirm'),'192.0.2.1',Mock(username='synthetic',password='synthetic'))
        run.assert_called_once()
        self.assertNotIn('synthetic',' '.join(run.call_args.args[0]))
        self.assertEqual(run.call_args.kwargs['stderr'],subprocess.DEVNULL)

    def test_worker_result_must_match_operation_and_verified_identity(self):
        for response in ({'result':'read_succeeded'},
                         {'result':'chime_ring_acknowledged','model':'D100C','authenticated':True},
                         {'result':'read_succeeded','model':'C230','authenticated':True}):
            with self.subTest(response=response), patch.object(chime.shutil,'which',return_value='/bin/node'), \
                    patch.object(Path,'is_file',return_value=True), \
                    patch.object(chime.subprocess,'run',return_value=Mock(returncode=0,stdout=json.dumps(response))):
                with self.assertRaisesRegex(cli.ControlError,'^chime_read_failed$'):
                    chime.invoke(self.args('status'),'192.0.2.1',Mock(username='synthetic',password='synthetic'))

    def test_raw_worker_error_is_not_exposed(self):
        with patch.object(chime.shutil,'which',return_value='/bin/node'), \
                patch.object(Path,'is_file',return_value=True), \
                patch.object(chime.subprocess,'run',return_value=Mock(returncode=2,stdout=json.dumps({'result':'error','reason':'DO_NOT_PRINT'}))):
            with self.assertRaisesRegex(cli.ControlError,'^chime_read_failed$'):
                chime.invoke(self.args('status'),'192.0.2.1',Mock(username='synthetic',password='synthetic'))

    @unittest.skipUnless(shutil.which('node') and
        (cli.ROOT/'private-notes/chime-tpap-v2/node_modules/@noble/curves/nist.js').is_file(),
        'Isolated chime crypto dependencies required')
    def test_offline_transport_peer_and_guards(self):
        result=subprocess.run([shutil.which('node'),str(cli.ROOT/'test_security_chime_transport.mjs')],
                              capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0)
        report=json.loads(result.stdout)
        self.assertFalse(report['network_access'])
        self.assertGreaterEqual(report['offline_transport_checks'],18)

    @unittest.skipUnless(shutil.which('node'),'Node required for integrity test')
    def test_runtime_integrity_detects_changes_and_rejects_links(self):
        with tempfile.TemporaryDirectory() as name:
            script = '''
import assert from 'node:assert/strict';
import fs from 'node:fs';
const {runtimeDigest}=await import(process.argv[1]);
const root=process.argv[2];
fs.writeFileSync(root+'/library.js','original');
const before=runtimeDigest(root);
assert.equal(before,runtimeDigest(root));
fs.writeFileSync(root+'/library.js','modified');
assert.notEqual(before,runtimeDigest(root));
fs.symlinkSync(root+'/library.js',root+'/linked.js');
assert.throws(()=>runtimeDigest(root),/chime_transport_integrity_failed/);
'''
            result=subprocess.run([shutil.which('node'),'--input-type=module','-e',script,
                (cli.ROOT/'security_chime_integrity.mjs').as_uri(),name],capture_output=True,timeout=3)
            self.assertEqual(result.returncode,0)

    @unittest.skipUnless(shutil.which('node'),'Node required for worker gate test')
    def test_worker_confirmation_gate_before_dependencies(self):
        result=subprocess.run([shutil.which('node'),str(cli.ROOT/'security_chime_worker.mjs')],
            input=json.dumps({'operation':'ring','confirm':False}),text=True,capture_output=True,timeout=3)
        self.assertEqual(json.loads(result.stdout)['reason'],'confirmation_required')
        self.assertEqual(result.returncode,2)


if __name__=='__main__':
    unittest.main()
