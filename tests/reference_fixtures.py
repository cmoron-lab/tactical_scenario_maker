# tests/reference_fixtures.py
from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from tsm.domain.profile import ExecutionProfile, load_profile
from tsm.domain.reference import ReferenceScenario, load_reference_scenario, parse_duration
from tsm.domain.scenario import Position
from tsm.execution.autonomy import KinematicWaypointFollower
from tsm.execution.objectives import Objective
from tsm.execution.world import WorldSnapshot


def scenario_with_single_agent(agent: str, mission_task: str) -> ReferenceScenario:
    return ReferenceScenario.from_dict({
        "version": 2, "information_policy": "omniscient",
        "forces": {"bleue": {"agents": [agent]}}, "relations": [],
        "zones": {}, "triggers": [],
        "agents": {agent: {
            "platform": "surface_vessel",
            "position": {"lat": 1.0, "lon": 2.0},
            "mission": {"task": mission_task, "args": [agent]},
            "conditions": {},
        }},
        "end": {"success": [], "failure": [], "timeout": "PT60S"},
    })


def execution_profile(agent: str, capabilities: set[str]) -> ExecutionProfile:
    return ExecutionProfile.from_dict({
        "version": 1, "name": "test",
        "agents": {agent: {
            "fidelity": "kinematic",
            "providers": {"lotusim.waypoint_follower": {"capabilities": sorted(capabilities)}},
            "spawn": {
                "model": "wamv", "linear_velocity": [0.0, 5.0],
                "angular_velocity_max": 0.05, "heading_deg": 0.0,
            },
        }},
    })


def snapshot(sim_time_s: float, positions: Mapping[str, tuple[float, float]],
             destroyed: set[str] | None = None) -> WorldSnapshot:
    return WorldSnapshot(
        revision=int(sim_time_s),
        sim_time_s=sim_time_s,
        positions={name: Position(lat, lon) for name, (lat, lon) in positions.items()},
        destroyed=frozenset(destroyed or set()))


def objective(goal_id: str, agent: str, capability: str,
              parameters: Mapping[str, Any],
              deadline_sim_time_s: float = 60.0) -> Objective:
    return Objective(goal_id, agent, capability, dict(parameters), 0.0,
                     deadline_sim_time_s)


class FakeTransport:
    def __init__(self) -> None:
        self.waypoints: list[tuple[str, float, float]] = []
        self.stopped: list[str] = []

    def set_waypoints(self, agent: str, lat: float, lon: float) -> None:
        self.waypoints.append((agent, lat, lon))

    def stop_vessel(self, agent: str) -> None:
        self.stopped.append(agent)


def kinematic_provider() -> tuple[KinematicWaypointFollower, FakeTransport]:
    transport = FakeTransport()
    return KinematicWaypointFollower(transport), transport


def ormuz_scenario(timeout: str | None = None) -> ReferenceScenario:
    scenario = load_reference_scenario("escorte_ormuz")
    if timeout is None:
        return scenario
    return replace(scenario, end=replace(scenario.end, timeout_s=parse_duration(timeout)))


def ormuz_profile() -> ExecutionProfile:
    return load_profile("kinematic-ormuz")
