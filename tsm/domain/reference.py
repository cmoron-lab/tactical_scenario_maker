"""Schéma canonique du Scenario Request v2 (déclaratif) et compilation en
ExecutionGraph authored.

Un Scenario Request v2 sépare le « quoi » tactique (forces, relations, zones,
missions, déclencheurs, fin de partie) du « comment » d'exécution — fidélité,
provider, spawn — qui vit dans tsm/domain/profile.py. Son identité est son nom
de fichier (sans extension) dans scenarios/, comme pour le schéma v1.
"""
from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, cast

from tsm.domain.scenario import Mission, Position, ScenarioError

SCHEMA_VERSION = 2
SCENARIOS_DIR = Path(__file__).resolve().parents[2] / 'scenarios'
_NAME_RE = re.compile(r'^[A-Za-z0-9_-]+$')

# Champs qui appartiennent au profil d'exécution (ExecutionProfile.spawn) et
# n'ont pas leur place dans un agent tactique du Scenario Request.
_SPAWN_ONLY_FIELDS = ('model', 'linear_velocity', 'angular_velocity_max', 'heading_deg')


def _num(doc: dict[str, Any], key: str, where: str) -> float:
    v = doc.get(key)
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        raise ScenarioError(f'{where}.{key} manquant ou non numérique')
    return float(v)


def parse_duration(value: str) -> float:
    match = re.fullmatch(r"PT(?:(\d+(?:\.\d+)?)M)?(?:(\d+(?:\.\d+)?)S)?", value)
    if not match or match.group(1) is None and match.group(2) is None:
        raise ScenarioError(f"durée ISO-8601 v3 invalide: {value!r}")
    return float(match.group(1) or 0) * 60 + float(match.group(2) or 0)


def format_duration(seconds: float) -> str:
    """Forme canonique PT<secondes>S ; fallback de EndState.to_dict quand la
    forme authored (timeout_raw) ne décrit plus timeout_s."""
    if seconds == int(seconds):
        return f'PT{int(seconds)}S'
    return f'PT{seconds}S'


@dataclass(frozen=True)
class ForceSpec:
    agents: tuple[str, ...]
    spawn: Literal["initial", "deferred"] = "initial"

    @classmethod
    def from_dict(cls, doc: Any, where: str) -> ForceSpec:
        if not isinstance(doc, dict):
            raise ScenarioError(f'{where} doit être un objet')
        agents = doc.get('agents')
        if not isinstance(agents, list) or not all(isinstance(a, str) for a in agents):
            raise ScenarioError(f'{where}.agents doit être une liste de noms')
        spawn_raw = doc.get('spawn', 'initial')
        if spawn_raw not in ('initial', 'deferred'):
            raise ScenarioError(f'{where}.spawn invalide: {spawn_raw!r}')
        return cls(agents=tuple(agents), spawn=cast(Literal["initial", "deferred"], spawn_raw))

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {'agents': list(self.agents)}
        if self.spawn != 'initial':
            out['spawn'] = self.spawn
        return out


@dataclass(frozen=True)
class Zone:
    lat: float
    lon: float
    radius_deg: float

    @classmethod
    def from_dict(cls, doc: Any, where: str) -> Zone:
        if not isinstance(doc, dict):
            raise ScenarioError(f'{where} doit être un objet')
        center = doc.get('center')
        if not isinstance(center, dict):
            raise ScenarioError(f'{where}.center manquant')
        return cls(
            lat=_num(center, 'lat', f'{where}.center'),
            lon=_num(center, 'lon', f'{where}.center'),
            radius_deg=_num(doc, 'radius_deg', where),
        )

    def to_dict(self) -> dict[str, Any]:
        return {'center': {'lat': self.lat, 'lon': self.lon}, 'radius_deg': self.radius_deg}


@dataclass(frozen=True)
class Relation:
    source: str
    targets: tuple[str, ...]
    attitude: Literal["hostile", "neutral", "allied", "protect"]

    @classmethod
    def from_dict(cls, doc: Any, where: str) -> Relation:
        if not isinstance(doc, dict):
            raise ScenarioError(f'{where} doit être un objet')
        source = doc.get('from')
        targets = doc.get('to')
        attitude_raw = doc.get('attitude')
        if not isinstance(source, str) or not source:
            raise ScenarioError(f'{where}.from manquant')
        if not isinstance(targets, list) or not all(isinstance(t, str) for t in targets):
            raise ScenarioError(f'{where}.to doit être une liste de noms')
        if attitude_raw not in ('hostile', 'neutral', 'allied', 'protect'):
            raise ScenarioError(f'{where}.attitude invalide: {attitude_raw!r}')
        attitude = cast(Literal["hostile", "neutral", "allied", "protect"], attitude_raw)
        return cls(source=source, targets=tuple(targets), attitude=attitude)

    def to_dict(self) -> dict[str, Any]:
        return {'from': self.source, 'to': list(self.targets), 'attitude': self.attitude}


@dataclass(frozen=True)
class TacticalAgentSpec:
    platform: str
    position: Position
    mission: Mission
    conditions: Mapping[str, Any]

    @classmethod
    def from_dict(cls, doc: Any, where: str) -> TacticalAgentSpec:
        if not isinstance(doc, dict):
            raise ScenarioError(f'{where} doit être un objet')
        for spawn_field in _SPAWN_ONLY_FIELDS:
            if spawn_field in doc:
                # « execution » volontairement sans accent : le test imposé par le
                # plan vérifie match="profil d.execution" (le « . » couvre l'apostrophe).
                raise ScenarioError(
                    f"{where}.{spawn_field} appartient au profil d'execution "
                    f"(ExecutionProfile.spawn), pas au scénario v2"
                )
        platform = doc.get('platform')
        if not isinstance(platform, str) or not platform:
            raise ScenarioError(f'{where}.platform manquant')
        pos = doc.get('position')
        if not isinstance(pos, dict):
            raise ScenarioError(f'{where}.position manquant')
        mission_doc = doc.get('mission')
        if not isinstance(mission_doc, dict) or not isinstance(mission_doc.get('task'), str):
            raise ScenarioError(f'{where}.mission.task manquant')
        args = mission_doc.get('args', [])
        if not isinstance(args, list):
            raise ScenarioError(f'{where}.mission.args doit être une liste')
        conditions = doc.get('conditions', {})
        if not isinstance(conditions, dict):
            raise ScenarioError(f'{where}.conditions doit être un objet')
        return cls(
            platform=platform,
            position=Position(_num(pos, 'lat', f'{where}.position'),
                              _num(pos, 'lon', f'{where}.position')),
            mission=Mission(task=mission_doc['task'], args=list(args)),
            conditions=conditions,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            'platform': self.platform,
            'position': {'lat': self.position.lat, 'lon': self.position.lon},
            'mission': {'task': self.mission.task, 'args': self.mission.args},
            'conditions': dict(self.conditions),
        }


@dataclass(frozen=True)
class Trigger:
    id: str
    when: Mapping[str, Any]
    actions: tuple[Mapping[str, Any], ...]

    @classmethod
    def from_dict(cls, doc: Any, where: str) -> Trigger:
        if not isinstance(doc, dict):
            raise ScenarioError(f'{where} doit être un objet')
        trigger_id = doc.get('id')
        when = doc.get('when')
        actions = doc.get('do')
        if not isinstance(trigger_id, str) or not trigger_id:
            raise ScenarioError(f'{where}.id manquant')
        if not isinstance(when, dict):
            raise ScenarioError(f'{where}.when manquant')
        if not isinstance(actions, list) or not all(isinstance(a, dict) for a in actions):
            raise ScenarioError(f'{where}.do doit être une liste d\'objets')
        return cls(id=trigger_id, when=when, actions=tuple(actions))

    def to_dict(self) -> dict[str, Any]:
        return {'id': self.id, 'when': dict(self.when), 'do': list(self.actions)}


@dataclass(frozen=True)
class EndState:
    success: tuple[Mapping[str, Any], ...]
    failure: tuple[Mapping[str, Any], ...]
    timeout_s: float
    # Forme ISO telle qu'authored ("PT30M"…) pour un roundtrip exact ;
    # "" = pas de forme brute, to_dict émet la forme canonique en secondes.
    timeout_raw: str = field(default='', compare=False)

    @classmethod
    def from_dict(cls, doc: Any, where: str) -> EndState:
        if not isinstance(doc, dict):
            raise ScenarioError(f'{where} doit être un objet')
        success = doc.get('success')
        failure = doc.get('failure')
        timeout = doc.get('timeout')
        if not isinstance(success, list) or not all(isinstance(s, dict) for s in success):
            raise ScenarioError(f'{where}.success doit être une liste d\'objets')
        if not isinstance(failure, list) or not all(isinstance(f, dict) for f in failure):
            raise ScenarioError(f'{where}.failure doit être une liste d\'objets')
        if not isinstance(timeout, str):
            raise ScenarioError(f'{where}.timeout manquant')
        return cls(success=tuple(success), failure=tuple(failure),
                   timeout_s=parse_duration(timeout), timeout_raw=timeout)

    def to_dict(self) -> dict[str, Any]:
        # La forme authored est réémise tant qu'elle décrit encore timeout_s ;
        # après un replace(timeout_s=...), retour à la forme canonique.
        if self.timeout_raw and parse_duration(self.timeout_raw) == self.timeout_s:
            timeout = self.timeout_raw
        else:
            timeout = format_duration(self.timeout_s)
        return {
            'success': list(self.success),
            'failure': list(self.failure),
            'timeout': timeout,
        }


@dataclass(frozen=True)
class ReferenceScenario:
    forces: Mapping[str, ForceSpec]
    relations: tuple[Relation, ...]
    zones: Mapping[str, Zone]
    agents: Mapping[str, TacticalAgentSpec]
    triggers: tuple[Trigger, ...]
    end: EndState
    information_policy: Literal["omniscient", "force_scoped"]

    @classmethod
    def from_dict(cls, doc: Any) -> ReferenceScenario:
        if not isinstance(doc, dict):
            raise ScenarioError('le document doit être un objet JSON')
        if doc.get('version') != SCHEMA_VERSION:
            raise ScenarioError(
                f'version inconnue: {doc.get("version")!r} (attendu {SCHEMA_VERSION})')
        policy_raw = doc.get('information_policy')
        if policy_raw not in ('omniscient', 'force_scoped'):
            raise ScenarioError(f'information_policy invalide: {policy_raw!r}')
        forces_doc = doc.get('forces')
        if not isinstance(forces_doc, dict):
            raise ScenarioError('forces manquant ou invalide')
        zones_doc = doc.get('zones')
        if not isinstance(zones_doc, dict):
            raise ScenarioError('zones manquant ou invalide')
        agents_doc = doc.get('agents')
        if not isinstance(agents_doc, dict):
            raise ScenarioError('agents manquant ou invalide')
        relations_doc = doc.get('relations')
        if not isinstance(relations_doc, list):
            raise ScenarioError('relations manquant ou invalide')
        triggers_doc = doc.get('triggers')
        if not isinstance(triggers_doc, list):
            raise ScenarioError('triggers manquant ou invalide')

        for collection, keys in (('forces', forces_doc), ('zones', zones_doc), ('agents', agents_doc)):
            for key in keys:
                if not _NAME_RE.match(key):
                    raise ScenarioError(
                        f'{collection}.{key!r}: nom invalide (identifiant attendu : lettres, chiffres, _ ou -)')

        return cls(
            forces={name: ForceSpec.from_dict(f, where=f'forces.{name}')
                    for name, f in forces_doc.items()},
            relations=tuple(Relation.from_dict(r, where=f'relations[{i}]')
                            for i, r in enumerate(relations_doc)),
            zones={name: Zone.from_dict(z, where=f'zones.{name}')
                   for name, z in zones_doc.items()},
            agents={name: TacticalAgentSpec.from_dict(a, where=f'agents.{name}')
                    for name, a in agents_doc.items()},
            triggers=tuple(Trigger.from_dict(t, where=f'triggers[{i}]')
                          for i, t in enumerate(triggers_doc)),
            end=EndState.from_dict(doc.get('end'), where='end'),
            information_policy=cast(Literal["omniscient", "force_scoped"], policy_raw),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            'version': SCHEMA_VERSION,
            'information_policy': self.information_policy,
            'forces': {name: f.to_dict() for name, f in self.forces.items()},
            'relations': [r.to_dict() for r in self.relations],
            'zones': {name: z.to_dict() for name, z in self.zones.items()},
            'agents': {name: a.to_dict() for name, a in self.agents.items()},
            'triggers': [t.to_dict() for t in self.triggers],
            'end': self.end.to_dict(),
        }


@dataclass(frozen=True)
class ExecutionGraph:
    """Missions par force telles qu'authored dans le Scenario Request. Ce
    n'est pas une sortie du planner HDDL (niveaux 5-6 du plan v3) : c'est le
    graphe d'exécution niveau 1, affecté explicitement par le rédacteur."""
    by_force: Mapping[str, Mapping[str, Mission]]


def compile_authored_graph(scenario: ReferenceScenario) -> ExecutionGraph:
    return ExecutionGraph({
        force: {agent: scenario.agents[agent].mission
                for agent in spec.agents}
        for force, spec in scenario.forces.items()
    })


# ── Store fichiers ────────────────────────────────────────────────────────────

def _path(name: str, directory: Path) -> Path:
    if not _NAME_RE.match(name):
        raise ScenarioError(f'nom de scénario invalide: {name!r}')
    return directory / f'{name}.json'


def load_reference_scenario(name: str, directory: Path = SCENARIOS_DIR) -> ReferenceScenario:
    path = _path(name, directory)
    if not path.exists():
        raise ScenarioError(f'scénario introuvable: {name}')
    with open(path, encoding='utf-8') as f:
        return ReferenceScenario.from_dict(json.load(f))


def save_reference_scenario(name: str, scenario: ReferenceScenario,
                            directory: Path | None = None) -> None:
    path = _path(name, directory if directory is not None else SCENARIOS_DIR)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(scenario.to_dict(), f, ensure_ascii=False, indent=2)
        f.write('\n')
