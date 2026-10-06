"""Informational service expectations: fixtures only; no process/device writes."""
import copy
import json
from pathlib import Path
import unittest

from jarvisd_core import system_health as health
from test_service_health import jarvisd
from test_system_history import BASE, snapshot


class InformationalServiceTests(unittest.TestCase):
    def test_only_an_explicit_optional_policy_is_informational(self):
        self.assertEqual(jarvisd._service_metadata({})['healthPolicy'], 'monitored')
        self.assertEqual(jarvisd._service_metadata({
            'critical': False, 'healthPolicy': 'informational'})['healthPolicy'], 'informational')
        for policy in (None, False, [], 'INFORMATIONAL', 'unknown'):
            self.assertEqual(jarvisd._service_metadata({
                'critical': False, 'healthPolicy': policy})['healthPolicy'], 'monitored')
        for critical in (True, None, 0):
            self.assertEqual(jarvisd._service_metadata({
                'critical': critical, 'healthPolicy': 'informational'})['healthPolicy'], 'monitored')

    def test_informational_bot_never_changes_overall_health_or_its_observation(self):
        states = [
            {'ok': True, 'running': False, 'ready': None},
            {'ok': True, 'running': True, 'ready': False, 'readinessReason': 'bot_disconnected'},
            {'ok': True, 'running': True, 'ready': False, 'readinessReason': 'bot_quarantined'},
            {'ok': True, 'running': True, 'ready': None, 'readinessReason': 'health_unavailable'},
            {'ok': False, 'running': None, 'error': 'Service observation unavailable.'},
            {'ok': True, 'running': True, 'ready': True},
        ]
        for state in states:
            with self.subTest(state=state):
                value = snapshot()
                bot = {'critical': False, 'healthPolicy': 'informational', **state}
                value['subsystems']['services']['services']['minecraft-jarvis-bot'] = bot
                before = copy.deepcopy(value)
                rows = health.project(value, BASE)
                self.assertEqual(rows['service:minecraft-jarvis-bot']['state'], 'inactive')
                self.assertEqual(rows['service:minecraft-jarvis-bot']['reason'], 'optional_inactive')
                self.assertEqual(rows['services']['state'], 'healthy')
                self.assertEqual(rows['overall']['state'], 'healthy')
                self.assertEqual(value, before, 'Do not rewrite running/readiness to manufacture health')

    def test_required_and_default_services_keep_their_failure_semantics(self):
        for data in (
            {'critical': True, 'healthPolicy': 'informational'},
            {'critical': False},
            {'critical': False, 'healthPolicy': 'unknown'},
        ):
            self.assertEqual(health._service({**data, 'ok': True, 'running': True,
                'ready': False})['state'], 'degraded')

    def test_informational_bot_cannot_hide_an_unrelated_failure(self):
        value = snapshot()
        value['subsystems']['services']['services'].update({
            'minecraft-jarvis-bot': {'critical': False, 'healthPolicy': 'informational',
                'ok': False, 'running': None},
            'minecraft-server': {'critical': False, 'ok': True, 'running': True, 'ready': False},
        })
        self.assertEqual(health.project(value, BASE)['overall']['state'], 'degraded')
        security = health.observation('unavailable', 'sensor_read_failed')
        self.assertEqual(health.project(snapshot(), BASE, security=security)['overall']['state'], 'unavailable')

    def test_registry_exempts_only_the_bot_and_grants_no_control(self):
        services = json.loads((Path(__file__).resolve().parents[1] / 'services.json').read_text())['services']
        self.assertEqual([key for key, row in services.items()
            if row.get('healthPolicy') == 'informational'], ['minecraft-jarvis-bot'])
        self.assertIs(services['minecraft-jarvis-bot']['critical'], False)
        self.assertEqual(services['minecraft-jarvis-bot']['allowedActions'], [])


if __name__ == '__main__':
    unittest.main()
