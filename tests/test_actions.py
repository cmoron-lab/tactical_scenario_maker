from tsm.execution.actions import aller_a, creation_agent, make_commands


def _state():
    st = type('State', (), {})()
    st.agents = {'usv': {'pos': {'lat': 1.0, 'lon': 2.0}, 'last_waypoint': None},
                 'dr1': {}}
    return st


def test_aller_a_updates_state():
    st = aller_a(_state(), 'usv', (1.5, 2.5))
    assert st.agents['usv']['pos'] == {'lat': 1.5, 'lon': 2.5}
    assert st.agents['usv']['last_waypoint'] == (1.5, 2.5)


def test_creation_agent_marks_both():
    st = creation_agent(_state(), 'usv', 'dr1')
    assert st.agents['usv']['deployed_drone'] == 'dr1'
    assert st.agents['dr1']['drone_deployed'] is True


def test_make_commands_c_aller_a_uses_client_and_logs():
    calls = []
    client = type('C', (), {'set_waypoints': lambda self, a, lat, lon: calls.append(('wp', a, lat, lon))})()
    logs = type('L', (), {'log_waypoint': lambda self, a, lat, lon: calls.append(('log', a, lat, lon))})()
    (c_aller_a,) = make_commands(client, logs)
    assert c_aller_a.__name__ == 'c_aller_a'  # requis par le lookup 'c_' + action
    st = c_aller_a(_state(), 'usv', (1.5, 2.5))
    assert ('wp', 'usv', 1.5, 2.5) in calls and ('log', 'usv', 1.5, 2.5) in calls
    assert st.agents['usv']['last_waypoint'] == (1.5, 2.5)
