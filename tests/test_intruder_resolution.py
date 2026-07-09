import unittest

import gtpyhop

gtpyhop.Domain('test_domain')
from bdd import tasks_methods


class IntruderResolutionTests(unittest.TestCase):
    def test_resolve_intruder_uses_marked_agent_name(self):
        state = type('State', (), {})()
        state.agents = {
            'usv': {'pos': {'lat': 1.0, 'lon': 2.0}},
            'ghost': {'pos': {'lat': 1.1, 'lon': 2.1}, 'is_intruder': True},
        }

        resolved = tasks_methods._resolve('__intruder__', 'usv', state)

        self.assertEqual(resolved, 'ghost')

    def test_resolve_base_uses_marked_agent_name(self):
        state = type('State', (), {})()
        state.agents = {
            'usv': {'pos': {'lat': 1.0, 'lon': 2.0}},
            'dock': {'pos': {'lat': 1.2, 'lon': 2.2}, 'is_base': True},
        }

        resolved = tasks_methods._resolve('__base__', 'usv', state)

        self.assertEqual(resolved, 'dock')

    def test_resolve_any_picks_nearest_other_agent(self):
        state = type('State', (), {})()
        state.agents = {
            'agent1':   {'pos': {'lat': 1.26, 'lon': 103.75}},
            'far_boat': {'pos': {'lat': 1.40, 'lon': 103.90}},
            'near_boat':{'pos': {'lat': 1.261, 'lon': 103.751}},
        }

        resolved = tasks_methods._resolve('__any__', 'agent1', state)

        self.assertEqual(resolved, 'near_boat')


if __name__ == '__main__':
    unittest.main()
