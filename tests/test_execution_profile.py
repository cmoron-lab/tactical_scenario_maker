# tests/test_execution_profile.py
import pytest

from tsm.domain.profile import ExecutionProfile, ProfileError, validate_profile

from tests.reference_fixtures import execution_profile, scenario_with_single_agent


def test_profile_rejects_missing_capability_for_assigned_mission():
    scenario = scenario_with_single_agent(
        agent="escorte", mission_task="escorter_convoi")
    profile = execution_profile(
        agent="escorte", capabilities={"navigation.goto"})
    with pytest.raises(ProfileError, match="engage.attack_target"):
        validate_profile(scenario, profile,
                         {"escorte": {"navigation.follow_target", "engage.attack_target"}})


def test_validate_profile_requires_profile_entry_for_every_scenario_agent():
    scenario = scenario_with_single_agent(agent="escorte", mission_task="transiter")
    profile = ExecutionProfile.from_dict({"version": 1, "name": "vide", "agents": {}})
    with pytest.raises(ProfileError, match="escorte"):
        validate_profile(scenario, profile, {})


def test_validate_profile_rejects_kinematic_provider_declaring_engagement_capability():
    scenario = scenario_with_single_agent(agent="escorte", mission_task="transiter")
    profile = ExecutionProfile.from_dict({
        "version": 1, "name": "test",
        "agents": {"escorte": {
            "fidelity": "kinematic",
            "providers": {"lotusim.waypoint_follower": {
                "capabilities": ["navigation.goto", "engage.attack_target"]}},
            "spawn": {"model": "wamv", "linear_velocity": [0.0, 5.0],
                      "angular_velocity_max": 0.05, "heading_deg": 0.0},
        }},
    })
    with pytest.raises(ProfileError, match="engage.attack_target"):
        validate_profile(scenario, profile, {})


def test_agent_execution_spec_capabilities_union_across_providers():
    profile = ExecutionProfile.from_dict({
        "version": 1, "name": "test",
        "agents": {"escorte": {
            "fidelity": "kinematic",
            "providers": {
                "lotusim.waypoint_follower": {
                    "capabilities": ["navigation.goto", "navigation.follow_target"]},
                "adjudicated": {"capabilities": ["engage.attack_target"]},
            },
            "spawn": {"model": "wamv", "linear_velocity": [0.0, 5.0],
                      "angular_velocity_max": 0.05, "heading_deg": 0.0},
        }},
    })
    assert profile.agents["escorte"].capabilities == frozenset(
        {"navigation.goto", "navigation.follow_target", "engage.attack_target"})
