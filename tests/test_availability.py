"""Low-balance routing and bounded fallback across providers."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from agent_hub.cache import Cache
from agent_hub.engine.availability import failure_reason, quota
from agent_hub.engine.profiles import Profiles
from agent_hub.engine.routing import Router
from agent_hub.engine.tasks import TaskStore


class AvailabilityTests(unittest.TestCase):
    def test_recent_low_balance_changes_orchestration_but_never_fixed_assignment(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cache = Cache(root/'index.sqlite')
            self.addCleanup(cache.close)
            profiles = Profiles(cache.conn)
            for ident in ('a', 'b'):
                profiles.register({'id': ident, 'provider': 'fixture', 'adapter': ident, 'command': [sys.executable]})
            task = TaskStore(cache.conn).create({'title': 'fixture', 'objective': 'fixture', 'assignment': {'mode': 'orchestrated'}})
            router = Router(cache.conn)
            path = root/'usage-cache/a.json'
            path.parent.mkdir()
            import time
            payload = {'provider': 'fixture', 'checked_at': time.time(), 'windows': [{'remaining': 5, 'resets': time.time()+3600}]}
            path.write_text(json.dumps(payload))
            result = router.choose(task.id)
            self.assertEqual(result['selected'], 'b')
            self.assertEqual(result['candidates'][1]['reason']['quota']['status'], 'low')
            payload['windows'][0]['remaining'] = 0
            path.write_text(json.dumps(payload))
            self.assertEqual([p['id'] for p in router.candidates(task)], ['b'])
            fixed = TaskStore(cache.conn).create({'title': 'fixed', 'objective': 'fixture', 'assignment': {'mode': 'fixed', 'agent': 'a'}})
            self.assertEqual(router.choose(fixed.id)['selected'], 'a')
            payload['checked_at'] -= 301
            path.write_text(json.dumps(payload))
            self.assertEqual(router.choose(task.id)['selected'], 'a')
            self.assertEqual(quota(profiles.get('a'), root)['status'], 'unknown')

    def test_expired_reset_and_null_are_unknown_not_free_credit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root/'usage-cache/cursor.json'
            path.parent.mkdir()
            path.write_text(json.dumps({'provider': 'cursor', 'checked_at': 100, 'windows': [{'remaining': 0, 'resets': 99}]}))
            self.assertEqual(quota({'provider': 'cursor', 'adapter': 'cursor'}, root, now=101)['status'], 'unknown')
            self.assertEqual(quota({'provider': 'cursor', 'adapter': '../private'}, root, now=101)['status'], 'unknown')

    def test_independent_model_groups_and_provider_failure_normalization(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root/'usage-cache/antigravity.json'
            path.parent.mkdir()
            path.write_text(json.dumps({'provider': 'antigravity', 'checked_at': 100, 'windows': [
                {'label': 'Gemini · Semana', 'remaining': 0}, {'label': 'Claude · Semana', 'remaining': 90}]}))
            self.assertEqual(quota({'provider': 'antigravity', 'adapter': 'antigravity'}, root, now=101)['status'], 'available')
        for message in ('quota exceeded', 'Rate limit reached', 'RESOURCE_EXHAUSTED', 'insufficient credits', 'usage limit reached'):
            self.assertEqual(failure_reason(message), 'quota_exhausted', message)
        self.assertEqual(failure_reason('context length exceeded'), 'token_limit')
        self.assertIsNone(failure_reason('ordinary validation failure'))
