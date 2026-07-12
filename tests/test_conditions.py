# tests/test_conditions.py
from dataclasses import replace

import pytest

from tests.reference_fixtures import scenario_with_single_agent, snapshot
from tsm.domain.conditions import evaluate
from tsm.domain.reference import ForceSpec, Zone
from tsm.domain.scenario import Position, ScenarioError
from tsm.execution.world import WorldSnapshot


def test_all_in_zone_and_agent_destroyed_share_one_evaluator():
    scenario = scenario_with_single_agent("cargo", "transiter")
    scenario = replace(scenario, forces={"verte": ForceSpec(("cargo",))},
                       zones={"sortie": Zone(1.0, 2.0, 0.001)})
    world = WorldSnapshot(1, 12.0, {"cargo": Position(1.0, 2.0)},
                          frozenset({"vedette"}))
    assert evaluate({"type": "all_in_zone", "force": "verte", "zone": "sortie"},
                    world, scenario)
    assert evaluate({"type": "agent_destroyed", "agent": "vedette"},
                    world, scenario)


def test_in_zone_true_inside_radius_false_outside():
    scenario = scenario_with_single_agent("cargo", "transiter")
    scenario = replace(scenario, zones={"sortie": Zone(1.0, 2.0, 0.001)})
    inside = snapshot(1.0, {"cargo": (1.0, 2.0005)})
    outside = snapshot(1.0, {"cargo": (1.0, 2.01)})
    condition = {"type": "in_zone", "agent": "cargo", "zone": "sortie"}
    assert evaluate(condition, inside, scenario)
    assert not evaluate(condition, outside, scenario)


def test_in_zone_false_when_agent_destroyed_or_pose_missing():
    scenario = scenario_with_single_agent("cargo", "transiter")
    scenario = replace(scenario, zones={"sortie": Zone(1.0, 2.0, 0.001)})
    condition = {"type": "in_zone", "agent": "cargo", "zone": "sortie"}
    destroyed = snapshot(1.0, {"cargo": (1.0, 2.0)}, destroyed={"cargo"})
    unseen = snapshot(1.0, {})
    assert not evaluate(condition, destroyed, scenario)
    assert not evaluate(condition, unseen, scenario)


def test_agent_destroyed_accepts_force_key_for_any_member():
    scenario = scenario_with_single_agent("cargo", "transiter")
    scenario = replace(scenario, forces={"verte": ForceSpec(("cargo", "vedette"))})
    world = snapshot(1.0, {}, destroyed={"vedette"})
    assert evaluate({"type": "agent_destroyed", "force": "verte"}, world, scenario)
    assert not evaluate({"type": "agent_destroyed", "force": "verte"},
                        snapshot(1.0, {}), scenario)


def test_unknown_condition_type_raises_scenario_error():
    scenario = scenario_with_single_agent("cargo", "transiter")
    world = snapshot(1.0, {})
    with pytest.raises(ScenarioError, match="inconnu"):
        evaluate({"type": "bogus"}, world, scenario)
