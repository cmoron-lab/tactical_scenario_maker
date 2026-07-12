"""Types de données du cycle de vie des objectifs (le « quoi »).

Une capacité signifie « peut tenter et rapporter un résultat », jamais
« réussit ». Tout objectif traverse submitted -> accepted -> in_progress ->
succeeded|failed|cancelled|timed_out. Aucune logique de contrôleur ici — voir
tsm/execution/autonomy.py pour le backend cinématique.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any


class ObjectiveStatus(str, Enum):
    SUBMITTED = "submitted"
    ACCEPTED = "accepted"
    IN_PROGRESS = "in_progress"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


@dataclass(frozen=True)
class Objective:
    id: str
    agent: str
    capability: str
    parameters: Mapping[str, Any]
    submitted_sim_time_s: float
    deadline_sim_time_s: float


@dataclass(frozen=True)
class ObjectiveUpdate:
    objective_id: str
    status: ObjectiveStatus
    sim_time_s: float
    reason: str | None = None


class ObjectiveFactory:
    """Compteur déterministe des identifiants d'objectif — pas d'uuid."""

    def __init__(self) -> None:
        self._next = 1

    def create(self, agent: str, capability: str, parameters: Mapping[str, Any],
               sim_time_s: float, timeout_s: float) -> Objective:
        objective = Objective(
            id=f"g-{self._next:06d}",
            agent=agent, capability=capability, parameters=dict(parameters),
            submitted_sim_time_s=sim_time_s,
            deadline_sim_time_s=sim_time_s + timeout_s,
        )
        self._next += 1
        return objective
