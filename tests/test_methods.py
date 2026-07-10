from tsm.planning.methods import _resolve


def _state(agents):
    st = type('State', (), {})()
    st.agents = agents
    return st


def test_resolve_intruder_uses_marked_agent_name():
    state = _state({
        'usv': {'pos': {'lat': 1.0, 'lon': 2.0}},
        'ghost': {'pos': {'lat': 1.1, 'lon': 2.1}, 'is_intruder': True},
    })
    assert _resolve('__intruder__', 'usv', state, {}) == 'ghost'


def test_resolve_base_uses_marked_agent_name():
    state = _state({
        'usv': {'pos': {'lat': 1.0, 'lon': 2.0}},
        'dock': {'pos': {'lat': 1.2, 'lon': 2.2}, 'is_base': True},
    })
    assert _resolve('__base__', 'usv', state, {}) == 'dock'


def test_resolve_any_picks_nearest_other_agent():
    state = _state({
        'agent1': {'pos': {'lat': 1.26, 'lon': 103.75}},
        'far_boat': {'pos': {'lat': 1.40, 'lon': 103.90}},
        'near_boat': {'pos': {'lat': 1.261, 'lon': 103.751}},
    })
    assert _resolve('__any__', 'agent1', state, {}) == 'near_boat'


def test_resolve_token_mapping_from_kb():
    state = _state({
        'usv': {'pos': {'lat': 1.0, 'lon': 2.0}},
        'proie': {'pos': {'lat': 1.1, 'lon': 2.1}},
    })
    # __cible__ -> __any__ (mapping KB) -> agent le plus proche
    assert _resolve('__cible__', 'usv', state, {'__cible__': '__any__'}) == 'proie'
