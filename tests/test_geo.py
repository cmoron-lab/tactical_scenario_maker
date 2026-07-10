from tsm.domain import doctrine
from tsm.domain.geo import agent_conditions, check_condition, distance_deg, in_zone


def test_distance_and_zone():
    a, b = {'lat': 1.0, 'lon': 2.0}, {'lat': 1.0, 'lon': 2.0003}
    assert abs(distance_deg(a, b) - 0.0003) < 1e-12
    assert in_zone(a, b, 0.001) and not in_zone(a, b, 0.0001)


def test_agent_conditions_prefers_conditions_over_legacy():
    assert agent_conditions({'conditions': {'role': 'x'}}) == {'role': 'x'}
    assert agent_conditions({'equipement': {'drone': 1}}) == {'drone_available': True}


def test_check_condition_state_equals_bool_coercion():
    assert check_condition({'type': 'state_equals', 'variable': 'v', 'value': 'true'}, {'v': True})
    assert check_condition({'type': 'distance_below'}, {}) is None  # cross-agent → au caller


def test_doctrine_loads_real_kb():
    kb = doctrine.load()
    assert 'tasks' in kb and 'resolve_tokens' in kb
