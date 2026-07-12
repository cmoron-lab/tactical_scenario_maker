# tests/reference_fixtures.py
import json
from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from tsm.domain.profile import PROFILES_DIR, ExecutionProfile, load_profile
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
from tsm.execution.white_cell import Verdict, WhiteCell
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


# ── Task 8 : harnais e2e en mémoire (chaîne complète, sans ROS) ───────────────

class InMemoryRuntimeHarness:
    """Fake transport ET pilote e2e : compose WorldStore, WhiteCell et
    RunController exactement comme tsm.execution.runtime._main_v3, mais fait
    avancer le monde par snapshots injectés — aucune navigation physique, aucun
    import ROS. Il EST le transport (spawn/delete/set_waypoints/stop) donné au
    contrôleur, ce qui rend spawns, deletes et waypoints directement lisibles."""

    def __init__(self, scenario: ReferenceScenario, profile: ExecutionProfile) -> None:
        self.spawned_agents: list[str] = []
        self.deleted: list[str] = []
        self.spawned_forces: list[str] = []
        self.waypoints: list[tuple[str, float, float]] = []
        self.stopped: list[str] = []
        self._world_store = WorldStore()
        self._white_cell = WhiteCell(
            scenario, profile, self._world_store,
            spawn_force=self._spawn_force,
            delete_vessel=self.delete_vessel,
            publish_event=lambda _e: None,
            stop=lambda reason: self._controller.stop(reason))
        self._controller = RunController(
            scenario=scenario, graph=compile_authored_graph(scenario),
            profile=profile, world_store=self._world_store,
            white_cell=self._white_cell, transport=self,
            publish_event=lambda _e: None)

    # ── Surface transport (identique à LotusimClient) ────────────────────────

    def spawn_vessel(self, vessel: str, init_pos: tuple[float, float], model: str,
                     linear_velocity: Any, angular_velocity_max: float,
                     heading_deg: float) -> str:
        self.spawned_agents.append(vessel)
        return vessel

    def delete_vessel(self, agent: str) -> None:
        self.deleted.append(agent)

    def set_waypoints(self, agent: str, lat: float, lon: float) -> None:
        self.waypoints.append((agent, lat, lon))

    def stop_vessel(self, agent: str) -> None:
        self.stopped.append(agent)

    # ── Callback d'injection de la cellule blanche ───────────────────────────

    def _spawn_force(self, force: str) -> None:
        self.spawned_forces.append(force)
        self._controller.spawn_force(force)

    # ── Pilotage e2e ─────────────────────────────────────────────────────────

    def start(self) -> None:
        # Préflight + spawn des forces initiales : une RunStartError remonte ici,
        # AVANT tout spawn (le test de profil incompatible en dépend).
        self._controller.start_initial_forces()
        # Arme l'horloge de la cellule blanche à t=0 (started_sim_time_s) : sans
        # ce tick, le premier tick réel fixerait started au sim_time observé et
        # le timeout serait faussé (test_ormuz_times_out_without_progress).
        self._controller.tick(self._world_store.snapshot())

    def snapshot(self, sim_time_s: float,
                 positions: Mapping[str, tuple[float, float]]
                 ) -> tuple[float, Mapping[str, tuple[float, float]]]:
        return sim_time_s, positions

    def tick(self, snap: tuple[float, Mapping[str, tuple[float, float]]]) -> None:
        sim_time_s, positions = snap
        # Passe par le WorldStore (décision 3) : `destroyed` reste monotone et la
        # cellule blanche observe le même monde que le contrôleur.
        self._world_store.update_poses(
            sim_time_s,
            {name: Position(lat, lon) for name, (lat, lon) in positions.items()})
        self._controller.tick(self._world_store.snapshot())

    def destroy(self, agent: str) -> None:
        self._world_store.mark_destroyed(agent)

    @property
    def verdict(self) -> Verdict:
        return self._white_cell._verdict


def in_memory_runtime(name: str, profile: str,
                      remove_capability: tuple[str, str] | None = None
                      ) -> tuple[InMemoryRuntimeHarness, InMemoryRuntimeHarness]:
    """(harness, harness) : même objet joué deux fois (pilote + double de vue),
    pour un dépaquetage `runtime, fake = ...` symétrique. remove_capability
    retire une capacité du profil avant construction, pour exercer le refus de
    préflight sans profil fixture dédié."""
    scenario = load_reference_scenario(name)
    if remove_capability is None:
        profile_obj = load_profile(profile)
    else:
        agent, capability = remove_capability
        with open(PROFILES_DIR / f'{profile}.json', encoding='utf-8') as f:
            doc = json.load(f)
        for provider_config in doc['agents'][agent]['providers'].values():
            caps = provider_config.get('capabilities')
            if caps and capability in caps:
                provider_config['capabilities'] = [c for c in caps if c != capability]
        profile_obj = ExecutionProfile.from_dict(doc)
    harness = InMemoryRuntimeHarness(scenario, profile_obj)
    return harness, harness
