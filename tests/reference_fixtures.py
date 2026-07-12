# tests/reference_fixtures.py
from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from tsm.domain.profile import ExecutionProfile, load_profile
from tsm.domain.reference import (
    ReferenceScenario,
    compile_authored_graph,
    load_reference_scenario,
    parse_duration,
)
from tsm.domain.scenario import Position
from tsm.execution.autonomy import KinematicWaypointFollower
from tsm.execution.controller import ForceView, RunController
from tsm.execution.objectives import Objective, ObjectiveStatus, ObjectiveUpdate
from tsm.execution.world import WorldSnapshot, WorldStore


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
        self.spawned: list[str] = []
        self.deleted: list[str] = []

    def set_waypoints(self, agent: str, lat: float, lon: float) -> None:
        self.waypoints.append((agent, lat, lon))

    def stop_vessel(self, agent: str) -> None:
        self.stopped.append(agent)

    def spawn_vessel(self, vessel: str, init_pos: tuple[float, float], model: str,
                     linear_velocity: Any, angular_velocity_max: float,
                     heading_deg: float) -> str:
        self.spawned.append(vessel)
        return vessel

    def delete_vessel(self, agent: str) -> None:
        self.deleted.append(agent)


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


# ── Task 5 : supervision par force et par agent ──────────────────────────────

class FakeProvider:
    def __init__(self) -> None:
        self.submitted: list[Objective] = []

    def submit(self, objective: Objective, world: WorldSnapshot) -> ObjectiveUpdate:
        self.submitted.append(objective)
        return ObjectiveUpdate(objective.id, ObjectiveStatus.ACCEPTED, world.sim_time_s)

    def tick(self, world: WorldSnapshot) -> list[ObjectiveUpdate]:
        return []

class StaticPlanner:
    def __init__(self, plan: list[tuple[Any, ...]]) -> None:
        self._plan = plan

    def find_plan(self, state: Any, task: tuple[Any, ...]) -> list[tuple[Any, ...]]:
        return list(self._plan)

def scenario_forces(policy: str, forces: Mapping[str, tuple[str, ...]]) -> ReferenceScenario:
    agents = {
        agent: {
            "platform": "surface_vessel",
            "position": {"lat": 1.0, "lon": 2.0},
            "mission": {"task": "transiter_vers_zone", "args": [agent, "sortie"]},
            "conditions": {},
        }
        for members in forces.values() for agent in members
    }
    return ReferenceScenario.from_dict({
        "version": 2, "information_policy": policy,
        "forces": {name: {"agents": list(members)} for name, members in forces.items()},
        "relations": [], "zones": {"sortie": {"center": {"lat": 1.2, "lon": 2.0},
                                             "radius_deg": 0.001}},
        "agents": agents, "triggers": [],
        "end": {"success": [], "failure": [], "timeout": "PT60S"},
    })

def view(force: str, world: WorldSnapshot) -> ForceView:
    return ForceView(force, world)

class NoopWhiteCell:
    def tick(self, world: WorldSnapshot) -> None:
        return None

def profile_for_scenario(scenario: ReferenceScenario) -> ExecutionProfile:
    return ExecutionProfile.from_dict({
        "version": 1, "name": "controller-test",
        "agents": {
            agent: {
                "fidelity": "kinematic",
                "providers": {
                    "lotusim.waypoint_follower": {
                        "capabilities": ["navigation.goto", "navigation.follow_target"]},
                    "adjudicated": {"capabilities": ["engage.attack_target"]},
                },
                "spawn": {
                    "model": "wamv", "linear_velocity": [0.0, 5.0],
                    "angular_velocity_max": 0.05, "heading_deg": 0.0,
                },
            }
            for agent in scenario.agents
        },
    })

def controller_with(scenario: ReferenceScenario) -> RunController:
    return RunController(
        scenario=scenario,
        graph=compile_authored_graph(scenario),
        profile=profile_for_scenario(scenario),
        world_store=WorldStore(),
        white_cell=NoopWhiteCell(),
        transport=FakeTransport(),
        publish_event=lambda _: None)
