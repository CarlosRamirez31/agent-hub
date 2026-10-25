"""Shared skill filtering preserves explicit requests and private boundaries."""
import json
import unittest
from agent_hub.cache import Cache
from agent_hub.engine.skills import BUNDLED, Skills
from agent_hub.engine.tasks import TaskStore


class SkillSelectionTests(unittest.TestCase):
    def setUp(self):
        self.cache = Cache(':memory:')
        self.addCleanup(self.cache.close)
        self.skills = Skills(self.cache.conn)
        for ident in BUNDLED:
            self.skills.register(ident, 'Instructions for ' + ident)
        self.skills.register('personal-rules', 'Keep custom global policy.')
        self.profile = {'id': 'worker', 'skills': []}

    def selected(self, **contract):
        task = TaskStore(self.cache.conn).create(dict(title='Fixture', objective='Test selection', **contract))
        return {item['id'] for item in self.skills.for_task(task, self.profile)}

    def test_local_write_omits_scaffold_and_preserves_safety_and_custom_rules(self):
        self.assertEqual(self.selected(complexity='small', permissions={'filesystem': 'write'}),
                         set(BUNDLED) - {'repo-scaffold', 'software-architect', 'context-efficiency'} | {'personal-rules'})

    def test_read_analysis_keeps_architecture_without_optional_efficiency_guide(self):
        self.assertEqual(self.selected(), {'software-architect', 'personal-rules'})
        self.assertIn('appsec-guardrail', self.selected(domain='security'))
        self.assertIn('appsec-guardrail', self.selected(permissions={'network': True}))

    def test_efficiency_is_only_loaded_when_explicitly_requested(self):
        self.assertNotIn('context-efficiency', self.selected())
        self.assertIn('context-efficiency', self.selected(skills=['context-efficiency']))
        self.profile['skills'] = ['context-efficiency']
        self.assertIn('context-efficiency', self.selected())

    def test_structural_write_and_explicit_scaffold(self):
        selected = self.selected(complexity='complex', permissions={'filesystem': 'write'}, skills=['repo-scaffold'])
        self.assertIn('repo-scaffold', selected)
        self.assertNotIn('surgical-edits', selected)
        self.assertIn('appsec-guardrail', selected)

    def test_explicit_profile_and_task_requests_keep_scope_checks(self):
        self.profile['skills'] = ['surgical-edits']
        self.assertIn('surgical-edits', self.selected(skills=['repo-scaffold']))
        self.skills.register('private-skill', 'Private.', 'agent', 'other')
        with self.assertRaisesRegex(ValueError, 'otro agente'):
            self.selected(skills=['private-skill'])
        owner = json.dumps({'agent': 'directory', 'id': '/different'})
        self.skills.register('project-skill', 'Project.', 'project', owner)
        with self.assertRaisesRegex(ValueError, 'otro proyecto'):
            self.selected(skills=['project-skill'])


if __name__ == '__main__':
    unittest.main()
