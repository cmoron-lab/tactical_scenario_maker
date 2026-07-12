"""Backend cinématique des objectifs — KinematicWaypointFollower.

Traduit navigation.goto et navigation.follow_target en waypoints envoyés à un
transport, et rapporte le résultat depuis la pose OBSERVÉE dans un
WorldSnapshot — jamais depuis l'acquittement du transport. Le transport est un
Protocol structurel (set_waypoints/stop_vessel) : le client LOTUSim réel
(paramètre timeout_s en plus, avec valeur par défaut) et le double de test
FakeTransport (tests/reference_fixtures.py) le satisfont tous deux, sans
import ROS ici.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from tsm.domain.conditions import distance_deg
from tsm.domain.scenario import Position
from tsm.execution.objectives import Objective, ObjectiveStatus, ObjectiveUpdate
from tsm.execution.world import WorldSnapshot


class _Transport(Protocol):
    def set_waypoints(self, agent: str, lat: float, lon: float) -> None: ...
    def stop_vessel(self, agent: str) -> None: ...


@dataclass
class _ActiveGoal:
    objective: Objective
    last_target: Position


class KinematicWaypointFollower:
    """Une capacité signifie « peut tenter et rapporter un résultat », jamais
    « réussit » : submit/tick/cancel suivent submitted -> accepted ->
    in_progress -> succeeded|failed|cancelled|timed_out, observé sur
    WorldSnapshot."""

    capabilities = frozenset({"navigation.goto", "navigation.follow_target"})

    def __init__(self, transport: _Transport) -> None:
        self._transport = transport
        self._active: dict[str, _ActiveGoal] = {}

    def submit(self, objective: Objective, world: WorldSnapshot) -> ObjectiveUpdate:
        if objective.capability not in self.capabilities:
            return ObjectiveUpdate(objective.id, ObjectiveStatus.FAILED, world.sim_time_s,
                                    reason="unsupported_capability")
        if objective.capability == "navigation.goto":
            lat, lon = objective.parameters["target"]
            target = Position(lat, lon)
        else:
            target_pos = world.positions.get(objective.parameters["target_agent"])
            if target_pos is None:
                return ObjectiveUpdate(objective.id, ObjectiveStatus.FAILED, world.sim_time_s,
                                        reason="missing_pose")
            target = target_pos
        self._transport.set_waypoints(objective.agent, target.lat, target.lon)
        self._active[objective.id] = _ActiveGoal(objective, target)
        return ObjectiveUpdate(objective.id, ObjectiveStatus.ACCEPTED, world.sim_time_s)

    def tick(self, world: WorldSnapshot) -> list[ObjectiveUpdate]:
        updates = []
        for goal_id, active in list(self._active.items()):
            update = self._tick_one(active, world)
            updates.append(update)
            if update.status != ObjectiveStatus.IN_PROGRESS:
                del self._active[goal_id]
        return updates

    def cancel(self, objective_id: str, world: WorldSnapshot) -> ObjectiveUpdate:
        active = self._active.pop(objective_id)  # KeyError : id inconnu ou déjà terminal
        self._transport.stop_vessel(active.objective.agent)
        return ObjectiveUpdate(objective_id, ObjectiveStatus.CANCELLED, world.sim_time_s)

    def _tick_one(self, active: _ActiveGoal, world: WorldSnapshot) -> ObjectiveUpdate:
        objective = active.objective
        if world.sim_time_s >= objective.deadline_sim_time_s:
            return ObjectiveUpdate(objective.id, ObjectiveStatus.TIMED_OUT, world.sim_time_s)
        if objective.capability == "navigation.goto":
            return self._tick_goto(active, world)
        return self._tick_follow(active, world)

    def _tick_goto(self, active: _ActiveGoal, world: WorldSnapshot) -> ObjectiveUpdate:
        objective = active.objective
        agent = objective.agent
        if agent in world.destroyed:
            return ObjectiveUpdate(objective.id, ObjectiveStatus.FAILED, world.sim_time_s,
                                    reason="target_destroyed")
        pos = world.positions.get(agent)
        if pos is None:
            return ObjectiveUpdate(objective.id, ObjectiveStatus.FAILED, world.sim_time_s,
                                    reason="missing_pose")
        arrival_radius_deg = objective.parameters["arrival_radius_deg"]
        if distance_deg(pos, active.last_target) <= arrival_radius_deg:
            return ObjectiveUpdate(objective.id, ObjectiveStatus.SUCCEEDED, world.sim_time_s)
        return ObjectiveUpdate(objective.id, ObjectiveStatus.IN_PROGRESS, world.sim_time_s)

    def _tick_follow(self, active: _ActiveGoal, world: WorldSnapshot) -> ObjectiveUpdate:
        objective = active.objective
        agent = objective.agent
        target_agent = objective.parameters["target_agent"]
        if target_agent in world.destroyed:
            return ObjectiveUpdate(objective.id, ObjectiveStatus.FAILED, world.sim_time_s,
                                    reason="target_destroyed")
        target_pos = world.positions.get(target_agent)
        if target_pos is None:
            return ObjectiveUpdate(objective.id, ObjectiveStatus.FAILED, world.sim_time_s,
                                    reason="missing_pose")
        threshold_deg = objective.parameters["update_threshold_deg"]
        if distance_deg(target_pos, active.last_target) >= threshold_deg:
            self._transport.set_waypoints(agent, target_pos.lat, target_pos.lon)
            active.last_target = target_pos
        stop_distance_deg = objective.parameters.get("stop_distance_deg")
        if stop_distance_deg is not None:
            own_pos = world.positions.get(agent)
            if own_pos is None:
                return ObjectiveUpdate(objective.id, ObjectiveStatus.FAILED, world.sim_time_s,
                                        reason="missing_pose")
            if distance_deg(own_pos, target_pos) <= stop_distance_deg:
                return ObjectiveUpdate(objective.id, ObjectiveStatus.SUCCEEDED, world.sim_time_s)
        return ObjectiveUpdate(objective.id, ObjectiveStatus.IN_PROGRESS, world.sim_time_s)
