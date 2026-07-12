"""Langage unique de conditions des triggers, de l'end state et de la
doctrine v3 : in_zone, all_in_zone, agent_destroyed. Distance en espace
euclidien degrés (cohérent avec les unités _deg du reste du plan v3), pas
haversine — évalué contre un WorldSnapshot, jamais contre une cible commandée.
"""
from __future__ import annotations

from collections.abc import Mapping
from math import hypot
from typing import Any

from tsm.domain.reference import ReferenceScenario
from tsm.domain.scenario import Position, ScenarioError
from tsm.execution.world import WorldSnapshot


def distance_deg(a: Position, b: Position) -> float:
    """Distance euclidienne en espace degrés (pas haversine), cohérente avec
    les unités _deg du plan v3. Réutilisée par le backend cinématique des
    objectifs (tsm/execution/autonomy.py)."""
    return hypot(a.lat - b.lat, a.lon - b.lon)


def _agent_in_zone(agent: str, zone_name: str, world: WorldSnapshot,
                    scenario: ReferenceScenario) -> bool:
    if agent in world.destroyed:
        return False
    pos = world.positions.get(agent)
    if pos is None:
        return False
    zone = scenario.zones[zone_name]
    return distance_deg(pos, Position(zone.lat, zone.lon)) <= zone.radius_deg


def evaluate(condition: Mapping[str, Any], world: WorldSnapshot,
            scenario: ReferenceScenario) -> bool:
    kind = condition.get('type')
    if kind == 'in_zone':
        return _agent_in_zone(condition['agent'], condition['zone'], world, scenario)
    if kind == 'all_in_zone':
        force = scenario.forces[condition['force']]
        return all(_agent_in_zone(agent, condition['zone'], world, scenario)
                   for agent in force.agents)
    if kind == 'agent_destroyed':
        if 'agent' in condition:
            return condition['agent'] in world.destroyed
        if 'force' in condition:
            force = scenario.forces[condition['force']]
            return any(agent in world.destroyed for agent in force.agents)
        raise ScenarioError("agent_destroyed: clé 'agent' ou 'force' requise")
    raise ScenarioError(f"type de condition inconnu: {kind!r}")
