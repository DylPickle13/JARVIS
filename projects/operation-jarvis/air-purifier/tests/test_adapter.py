import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch
p=Path(__file__).resolve().parents[2]/'jarvis.py'
spec=importlib.util.spec_from_file_location('purifier_adapter_under_test',p)
adapter=importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)

class AdapterTests(unittest.TestCase):
    def test_collection_routing(self):
        for action,command in [('purifier-list','list'),('purifier-status-all','status-all')]:
            args=adapter.build_parser().parse_args([action])
            with patch.object(adapter,'run_air_purifier_command',return_value={'data':{}}) as run:
                result=args.func(args)
                self.assertEqual(result['action'],action)
                self.assertEqual(run.call_args.args[0],[command])

    def test_single_read_recovery(self):
        args=adapter.build_parser().parse_args(['purifier-status','--purifier','bran','--retry-cooldown'])
        with patch.object(adapter,'run_air_purifier_command',return_value={'data':{}}) as run:
            args.func(args)
            self.assertEqual(run.call_args.args[0],['--retry-cooldown','status','bran'])

    def test_batch_recovery(self):
        args=adapter.build_parser().parse_args(['purifier-status-all','--retry-cooldown'])
        with patch.object(adapter,'run_air_purifier_command',return_value={'data':{}}) as run:
            args.func(args)
            self.assertEqual(run.call_args.args[0],['--retry-cooldown','status-all'])

    def test_discovery_and_writes_reject_recovery(self):
        for command in [['purifier-list'],['purifier-set','power','on']]:
            with self.assertRaises(SystemExit):
                adapter.build_parser().parse_args(command+['--retry-cooldown'])

    def test_partial_failure_exposed(self):
        args=adapter.build_parser().parse_args(['purifier-status-all'])
        devices={'a':{'ok':False,'name':'First','error':'failed'},'b':{'ok':True,'status':{'name':'Second','pm25':1}}}
        with patch.object(adapter,'run_air_purifier_command',return_value={'data':devices}):
            result=args.func(args)
            self.assertEqual(result['purifiers'],devices)
            self.assertIn('refresh failed',result['summary'])
            self.assertIn('Second',result['summary'])
