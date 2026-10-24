"""Native quota normalization, truthful unknowns and nonblocking caching."""
from datetime import datetime, timezone
from types import SimpleNamespace
import threading
import unittest
from unittest.mock import patch

from agent_hub.usage import Window, Monitor, antigravity_windows, codex_windows, countdown, fetch, hermes_windows, timestamp


class QuotaTests(unittest.TestCase):
    def test_codex_prefers_all_named_windows_and_never_treats_missing_as_zero(self):
        data = {'rateLimits': {'primary': {'usedPercent': 99}}, 'rateLimitsByLimitId': {
            'codex': {'primary': {'usedPercent': 18, 'windowDurationMins': 300, 'resetsAt': 2000},
                      'secondary': {'usedPercent': 54, 'windowDurationMins': 10080, 'resetsAt': 3000}}}}
        self.assertEqual(codex_windows(data), [Window('5 h', 82, 2000), Window('Semana', 46, 3000)])
        missing = codex_windows({'rateLimits': {'primary': {'usedPercent': None}}})[0]
        self.assertIsNone(missing.remaining)
        self.assertIsNone(missing.resets)
        self.assertEqual(codex_windows({'rateLimits': None}), [])

    def test_antigravity_group_quotas_have_independent_resets(self):
        payload = {'command': {'name': 'usage', 'data': {'groups': [
            {'name': 'Gemini Models', 'buckets': [{'window': 'weekly', 'remaining_fraction': .01, 'reset_time': '2026-10-31T17:26:29Z'}]},
            {'name': 'Claude and GPT models', 'buckets': [{'window': 'weekly', 'remaining_fraction': 1, 'reset_time': '2026-10-31T18:47:56Z'}]}]}}}
        windows = antigravity_windows(payload)
        self.assertEqual([w.remaining for w in windows], [1, 100])
        self.assertNotEqual(windows[0].resets, windows[1].resets)
        self.assertIn('Semana', windows[0].label)
        with self.assertRaises(ValueError):
            antigravity_windows({'response': 'A generated answer is not quota data'})

    def test_hermes_reports_provider_windows_without_claiming_a_monthly_balance(self):
        windows = hermes_windows({'provider': 'openai-codex', 'windows': [{'label': 'Weekly', 'used_percent': 54, 'resets_at': '2026-10-30T19:25:47+00:00'}]})
        self.assertEqual(windows[0].remaining, 46)
        self.assertEqual(windows[0].label, 'Semana')
        self.assertIsNotNone(windows[0].resets)
        self.assertIsNone(hermes_windows({'windows': [{'used_percent': True}]})[0].remaining)
        self.assertIsNone(timestamp('2026-10-30T19:25:47'))

    def test_countdown_handles_elapsed_unknown_and_days_without_inventing_refills(self):
        self.assertIn('2d 3h', countdown(2*86400+3*3600, 0))
        self.assertIn('1h 02m', countdown(3720, 0))
        self.assertIn('pendiente', countdown(99, 100))
        self.assertIn('no informado', countdown(None, 100))
        self.assertIsNone(timestamp(float('inf')))

    def test_monitor_returns_immediately_deduplicates_and_preserves_stale_data(self):
        release = threading.Event()
        started = threading.Event()
        def loader(agent):
            started.set()
            release.wait(3)
            return [Window('Semana', 46, 2000)]
        monitor = Monitor(None, loader)
        self.assertTrue(monitor.refresh())
        self.assertTrue(started.wait(1))
        self.assertFalse(monitor.refresh(force=True))
        self.assertIn('consultando', monitor.lines()[0])
        release.set()
        # Join only this test's deterministic loader, never poll a live provider.
        for thread in threading.enumerate():
            if thread.name == 'agent-hub-usage':
                thread.join(2)
        self.assertIn('46% restante', monitor.lines(now=100)[1])
        self.assertFalse(monitor.refresh())
        monitor.loader = lambda _: (_ for _ in ()).throw(ValueError('private native diagnostic'))
        monitor._load()
        self.assertIn('dato anterior', monitor.lines()[0])
        self.assertNotIn('private', str(monitor.lines()))
        self.assertEqual(monitor.windows[0].remaining, 46)

    def test_native_clients_query_only_usage_and_never_start_a_model_turn(self):
        agent = SimpleNamespace(kind='antigravity', command=['agy'], container='', home='/not-a-home')
        with patch('agent_hub.usage.native_json', return_value={'command': {'name': 'usage', 'data': {}}}) as native:
            fetch(agent)
            argv = native.call_args.args[0]
            self.assertEqual(argv, ['agy', '--print', '/usage', '--output-format', 'json', '--print-timeout', '10s'])
            self.assertNotIn('--dangerously-skip-permissions', argv)
        agent.kind, agent.container = 'hermes', 'fixture'
        with patch('agent_hub.usage.native_json', return_value={'windows': []}) as native:
            fetch(agent)
            self.assertEqual(native.call_args.args[0], ['podman', 'exec', 'fixture', '/usr/local/bin/hermes', 'usage', '--json'])

    def test_codex_reader_is_closed_and_only_account_limits_are_requested(self):
        agent = SimpleNamespace(kind='codex', container='', home='/not-a-home')
        with patch('agent_hub.rpc.CodexReader') as cls:
            reader = cls.return_value
            reader.call.side_effect = [{}, {'rateLimits': None}]
            self.assertEqual(fetch(agent), [])
            self.assertEqual([call.args[0] for call in reader.call.call_args_list], ['initialize', 'account/rateLimits/read'])
            reader.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
