"""Cellule blanche v3 : l'unique « vue de dieu » légitime du run.

Elle observe la vérité terrain (WorldStore / WorldSnapshot) et en dérive trois
décisions que les forces n'ont pas le droit de prendre elles-mêmes :

- les injections (triggers) : chaque déclencheur du scénario, identifié par id,
  s'arme au plus une fois quand sa condition devient vraie et applique ses
  actions (aujourd'hui : spawn d'une force différée via le callback du
  contrôleur) ;
- l'adjudication des engagements : submit_attack accepte ou refuse une attaque
  selon la relation déclarée, la portée du profil et l'état de la cible, puis,
  après duration_s de temps SIMULÉ, supprime et marque la cible détruite ;
- le verdict de fin de partie : success avant failure puis timeout, évalué à
  chaque snapshot tant qu'il est PENDING, figé dès qu'il devient terminal.

Aucun import ROS : world_store et les callbacks (spawn_force, delete_vessel,
publish_event, stop) sont fournis à la composition par le contrôleur. Temps
simulé partout — jamais datetime.now().
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable

from tsm.domain.conditions import distance_deg, evaluate
from tsm.domain.profile import ExecutionProfile
from tsm.domain.reference import ReferenceScenario, parse_duration
from tsm.domain.scenario import ScenarioError
from tsm.execution.objectives import Objective, ObjectiveStatus, ObjectiveUpdate
from tsm.execution.world import WorldSnapshot, WorldStore


class Verdict(str, Enum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class WhiteCellEvent:
    kind: str
    sim_time_s: float
    fields: Mapping[str, Any]


@dataclass(frozen=True)
class _PendingAttack:
    objective: Objective
    target: str
    completion_sim_time_s: float


class WhiteCell:
    def __init__(self, scenario: ReferenceScenario, profile: ExecutionProfile,
                 world_store: WorldStore,
                 spawn_force: Callable[[str], None],
                 delete_vessel: Callable[[str], None],
                 publish_event: Callable[[WhiteCellEvent], None],
                 stop: Callable[[str], None]) -> None:
        self._scenario = scenario
        self._profile = profile
        self._world_store = world_store
        self._spawn_force = spawn_force
        self._delete_vessel = delete_vessel
        self._publish_event = publish_event
        self._stop = stop
        self._verdict = Verdict.PENDING
        self._started_sim_time_s: float | None = None
        self._fired_triggers: set[str] = set()
        self._pending_attacks: dict[str, _PendingAttack] = {}
        self._attack_updates: list[ObjectiveUpdate] = []

    # ── Boucle de verdict ────────────────────────────────────────────────────

    def tick(self, world: WorldSnapshot) -> Verdict:
        if self._verdict is not Verdict.PENDING:
            return self._verdict  # figé : on ne réévalue plus rien
        if self._started_sim_time_s is None:
            self._started_sim_time_s = world.sim_time_s
        self._fire_due_triggers(world)
        self._complete_due_attacks(world)
        if self._verdict is not Verdict.PENDING:
            return self._verdict  # une injection ratée a déjà tranché (FAILED)
        end = self._scenario.end
        # Le garde `end.success and` évite l'auto-succès d'un all() sur liste
        # vide : « au moins une condition de succès » est requise (décision 7).
        if end.success and all(evaluate(c, world, self._scenario) for c in end.success):
            self._finish(Verdict.SUCCEEDED, world)
        elif any(evaluate(c, world, self._scenario) for c in end.failure):
            self._finish(Verdict.FAILED, world)
        elif world.sim_time_s >= self._started_sim_time_s + end.timeout_s:
            self._finish(Verdict.TIMED_OUT, world)
        return self._verdict

    def _finish(self, verdict: Verdict, world: WorldSnapshot,
                reason: str | None = None) -> None:
        if self._verdict is not Verdict.PENDING:
            return
        self._verdict = verdict
        self._publish_event(WhiteCellEvent(
            "verdict", world.sim_time_s,
            {"verdict": verdict.value, "reason": reason}))
        self._stop(f"verdict:{verdict.value}")

    # ── Injections (triggers) ────────────────────────────────────────────────

    def _fire_due_triggers(self, world: WorldSnapshot) -> None:
        for trigger in self._scenario.triggers:
            if trigger.id in self._fired_triggers:
                continue
            if not evaluate(trigger.when, world, self._scenario):
                continue
            self._fired_triggers.add(trigger.id)
            self._publish_event(WhiteCellEvent(
                "trigger_fired", world.sim_time_s, {"trigger": trigger.id}))
            for action in trigger.actions:
                self._apply_action(action, world)
                if self._verdict is not Verdict.PENDING:
                    return  # un spawn indisponible a tranché : stop d'appliquer

    def _apply_action(self, action: Mapping[str, Any], world: WorldSnapshot) -> None:
        kind = action.get("type")
        if kind == "spawn_force":
            self._spawn_injection(str(action["force"]), world)
            return
        raise ScenarioError(f"type d'action de trigger inconnu: {kind!r}")

    def _spawn_injection(self, force: str, world: WorldSnapshot) -> None:
        # Import différé : casse le cycle white_cell ↔ controller (controller
        # importe Verdict). spawn_force EST controller.spawn_force en composition.
        from tsm.execution.controller import RunStartError
        try:
            self._spawn_force(force)
        except RunStartError:
            self._finish(Verdict.FAILED, world, reason="spawn_unavailable")

    # ── Adjudication des engagements ─────────────────────────────────────────

    def submit_attack(self, objective: Objective, world: WorldSnapshot) -> ObjectiveUpdate:
        attacker = objective.agent
        target = str(objective.parameters["target_agent"])
        if target in world.destroyed:
            return self._reject(objective, world, "target_destroyed")
        attacker_pos = world.positions.get(attacker)
        target_pos = world.positions.get(target)
        if attacker_pos is None or target_pos is None:
            return self._reject(objective, world, "missing_pose")
        if not self._engagement_authorized(attacker, target):
            return self._reject(objective, world, "relation_not_hostile")
        range_deg, duration_s = self._adjudication_params(attacker)
        if distance_deg(attacker_pos, target_pos) > range_deg:
            return self._reject(objective, world, "out_of_range")
        self._pending_attacks[objective.id] = _PendingAttack(
            objective, target, world.sim_time_s + duration_s)
        self._publish_event(WhiteCellEvent(
            "engagement_accepted", world.sim_time_s,
            {"objective_id": objective.id, "attacker": attacker, "target": target}))
        return ObjectiveUpdate(objective.id, ObjectiveStatus.ACCEPTED, world.sim_time_s)

    def cancel_attack(self, objective_id: str, world: WorldSnapshot) -> ObjectiveUpdate:
        self._pending_attacks.pop(objective_id, None)  # désarme l'adjudication
        return ObjectiveUpdate(objective_id, ObjectiveStatus.CANCELLED, world.sim_time_s)

    def drain_attack_updates(self) -> list[ObjectiveUpdate]:
        drained = self._attack_updates
        self._attack_updates = []
        return drained

    def _complete_due_attacks(self, world: WorldSnapshot) -> None:
        for obj_id, pending in list(self._pending_attacks.items()):
            if world.sim_time_s < pending.completion_sim_time_s:
                continue
            self._delete_vessel(pending.target)
            self._world_store.mark_destroyed(pending.target)
            self._publish_event(WhiteCellEvent(
                "adjudication", world.sim_time_s,
                {"objective_id": obj_id, "attacker": pending.objective.agent,
                 "target": pending.target}))
            self._attack_updates.append(ObjectiveUpdate(
                obj_id, ObjectiveStatus.SUCCEEDED, world.sim_time_s))
            del self._pending_attacks[obj_id]

    def _reject(self, objective: Objective, world: WorldSnapshot,
                reason: str) -> ObjectiveUpdate:
        self._publish_event(WhiteCellEvent(
            "engagement_rejected", world.sim_time_s,
            {"objective_id": objective.id, "reason": reason}))
        return ObjectiveUpdate(objective.id, ObjectiveStatus.FAILED,
                               world.sim_time_s, reason=reason)

    def _adjudication_params(self, attacker: str) -> tuple[float, float]:
        for config in self._profile.agents[attacker].providers.values():
            if "engage.attack_target" not in config.get("capabilities", []):
                continue
            range_deg = config.get("range_deg")
            duration = config.get("duration")
            if range_deg is None or duration is None:
                raise ScenarioError(
                    f"provider arbitré de {attacker!r} sans range_deg/duration")
            return float(range_deg), parse_duration(str(duration))
        raise ScenarioError(f"{attacker!r} sans provider d'engagement arbitré")

    # ── Relations (directionnelles) ──────────────────────────────────────────

    def _engagement_authorized(self, attacker: str, target: str) -> bool:
        attacker_force = self._force_of(attacker)
        target_force = self._force_of(target)
        if attacker_force is None or target_force is None:
            return False
        if self._is_hostile(attacker_force, target_force):
            return True
        # « protect déclenché » : la force de la cible est hostile envers une
        # force que la force de l'attaquant protège.
        for protege in self._protected_by(attacker_force):
            if self._is_hostile(target_force, protege):
                return True
        return False

    def _force_of(self, agent: str) -> str | None:
        for name, spec in self._scenario.forces.items():
            if agent in spec.agents:
                return name
        return None

    def _is_hostile(self, source: str, target: str) -> bool:
        return any(r.attitude == "hostile" and r.source == source and target in r.targets
                   for r in self._scenario.relations)

    def _protected_by(self, force: str) -> list[str]:
        protege: list[str] = []
        for r in self._scenario.relations:
            if r.attitude == "protect" and r.source == force:
                protege.extend(r.targets)
        return protege
