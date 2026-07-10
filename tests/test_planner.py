from tsm.domain.scenario import Scenario
from tsm.execution.actions import aller_a, creation_agent
from tsm.planning.planner import Planner, build_state

KB = {
    'resolve_tokens': {},
    'tasks': {
        'patrouille': {'methods': [{
            'name': 'aller au point',
            'preconditions': [],
            'subtasks': [{'task': 'aller_a_position', 'args': ['__self__', [1.25, 103.75]]}],
        }]},
    },
}

DOC = {'version': 1, 'agents': {'usv': {
    'position': {'lat': 1.26, 'lon': 103.75}, 'heading_deg': 0.0, 'model': 'wamv',
    'velocity': {'linear': [0.0, 5.0], 'angular_max': 0.05},
    'conditions': {'role': 'patrol', 'actif': 'true'},
    'mission': {'task': 'patrouille', 'args': ['usv']},
}}}


def _planner():
    return Planner(KB, actions=(aller_a, creation_agent))


def test_build_state_coerces_bool_strings():
    st = build_state(Scenario.from_dict(DOC))
    assert st.agents['usv']['actif'] is True
    assert st.agents['usv']['pos'] == {'lat': 1.26, 'lon': 103.75}
    assert st.position_history == {}


def test_find_plan_decomposes_kb_task():
    p = _planner()
    st = build_state(Scenario.from_dict(DOC))
    plan = p.find_plan(st, ('patrouille', 'usv'))
    assert plan == [('aller_a', 'usv', [1.25, 103.75])]


def test_find_plan_idempotency_guard_returns_empty_plan():
    p = _planner()
    st = build_state(Scenario.from_dict(DOC))
    st.agents['usv']['last_waypoint'] = (1.25, 103.75)  # déjà en route
    assert p.find_plan(st, ('patrouille', 'usv')) == []


def test_two_planners_do_not_share_methods():
    # NB : find_plan sur une tâche inconnue LÈVE dans gtpyhop (il ne retourne
    # pas False) — l'isolation se vérifie sur les domaines eux-mêmes.
    p1 = _planner()
    p2 = Planner({'resolve_tokens': {}, 'tasks': {}}, actions=(aller_a,))
    assert 'patrouille' in p1._domain._task_method_dict
    assert 'patrouille' not in p2._domain._task_method_dict
    st = build_state(Scenario.from_dict(DOC))
    assert p1.find_plan(st, ('patrouille', 'usv')) == [('aller_a', 'usv', [1.25, 103.75])]


def test_reload_kb_replaces_methods_without_accumulation():
    p = _planner()
    st = build_state(Scenario.from_dict(DOC))
    for _ in range(3):
        p.reload_kb(KB)
    task_methods = p._domain._task_method_dict['patrouille']
    assert len(task_methods) == 1  # pas d'empilement de doublons
    assert p.find_plan(st, ('patrouille', 'usv')) == [('aller_a', 'usv', [1.25, 103.75])]


def test_run_commands_applies_pure_action_fallback():
    p = _planner()
    st = build_state(Scenario.from_dict(DOC))
    p.run_commands(st, [('aller_a', 'usv', (1.30, 103.80))])
    assert st.agents['usv']['pos'] == {'lat': 1.30, 'lon': 103.80}
