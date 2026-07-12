"""Schéma canonique des scénarios (v1) et accès fichiers.

Un scénario est un document JSON {"version": 1, "agents": {...}} ; son
identité est son nom de fichier (sans extension) dans scenarios/.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
SCENARIOS_DIR = Path(__file__).resolve().parents[2] / 'scenarios'
_NAME_RE = re.compile(r'^[A-Za-z0-9_-]+$')


class ScenarioError(ValueError):
    """Document de scénario invalide."""


def _num(doc: dict[str, Any], key: str, where: str) -> float:
    v = doc.get(key)
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        raise ScenarioError(f'{where}.{key} manquant ou non numérique')
    return float(v)


@dataclass
class Position:
    lat: float
    lon: float


@dataclass
class Mission:
    task: str
    args: list[Any] = field(default_factory=list)

    def to_htn_task(self) -> tuple[Any, ...]:
        """Tuple de tâche GTPyhop ; les args [lat, lon] deviennent des tuples."""
        return (self.task, *[tuple(a) if isinstance(a, list) else a for a in self.args])


@dataclass
class AgentSpec:
    position: Position
    heading_deg: float
    model: str
    linear_velocity: tuple[float, float]
    angular_velocity_max: float
    conditions: dict[str, Any]
    mission: Mission

    @classmethod
    def from_dict(cls, doc: dict[str, Any], where: str) -> AgentSpec:
        if not isinstance(doc, dict):
            raise ScenarioError(f'{where} doit être un objet')
        pos = doc.get('position')
        if not isinstance(pos, dict):
            raise ScenarioError(f'{where}.position manquant')
        vel = doc.get('velocity')
        if not isinstance(vel, dict):
            raise ScenarioError(f'{where}.velocity manquant')
        lin = vel.get('linear')
        if not (isinstance(lin, list) and len(lin) == 2
                and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in lin)):
            raise ScenarioError(f'{where}.velocity.linear doit être [min, max] numériques')
        mission = doc.get('mission')
        if not isinstance(mission, dict) or not isinstance(mission.get('task'), str):
            raise ScenarioError(f'{where}.mission.task manquant')
        args = mission.get('args', [])
        if not isinstance(args, list):
            raise ScenarioError(f'{where}.mission.args doit être une liste')
        model = doc.get('model')
        if not isinstance(model, str) or not model:
            raise ScenarioError(f'{where}.model manquant')
        conditions = doc.get('conditions', {})
        if not isinstance(conditions, dict):
            raise ScenarioError(f'{where}.conditions doit être un objet')
        return cls(
            position=Position(_num(pos, 'lat', f'{where}.position'),
                              _num(pos, 'lon', f'{where}.position')),
            heading_deg=_num(doc, 'heading_deg', where) if 'heading_deg' in doc else 0.0,
            model=model,
            linear_velocity=(float(lin[0]), float(lin[1])),
            angular_velocity_max=_num(vel, 'angular_max', f'{where}.velocity'),
            conditions=conditions,
            mission=Mission(task=mission['task'], args=list(args)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            'position': {'lat': self.position.lat, 'lon': self.position.lon},
            'heading_deg': self.heading_deg,
            'model': self.model,
            'velocity': {'linear': [self.linear_velocity[0], self.linear_velocity[1]],
                         'angular_max': self.angular_velocity_max},
            'conditions': self.conditions,
            'mission': {'task': self.mission.task, 'args': self.mission.args},
        }


@dataclass
class Scenario:
    agents: dict[str, AgentSpec]

    @classmethod
    def from_dict(cls, doc: dict[str, Any]) -> Scenario:
        if not isinstance(doc, dict):
            raise ScenarioError('le document doit être un objet JSON')
        if doc.get('version') != SCHEMA_VERSION:
            raise ScenarioError(f'version inconnue: {doc.get("version")!r} (attendu {SCHEMA_VERSION})')
        agents_doc = doc.get('agents')
        if not isinstance(agents_doc, dict):
            raise ScenarioError('agents manquant ou invalide')
        return cls(agents={
            name: AgentSpec.from_dict(a, where=f'agents.{name}')
            for name, a in agents_doc.items()
        })

    def to_dict(self) -> dict[str, Any]:
        return {'version': SCHEMA_VERSION,
                'agents': {name: a.to_dict() for name, a in self.agents.items()}}


# ── Store fichiers ────────────────────────────────────────────────────────────

def _path(name: str, directory: Path) -> Path:
    if not _NAME_RE.match(name):
        raise ScenarioError(f'nom de scénario invalide: {name!r}')
    return directory / f'{name}.json'


def list_scenarios(directory: Path = SCENARIOS_DIR) -> list[str]:
    return sorted(p.stem for p in directory.glob('*.json'))


def load_scenario(name: str, directory: Path = SCENARIOS_DIR) -> Scenario:
    path = _path(name, directory)
    if not path.exists():
        raise ScenarioError(f'scénario introuvable: {name}')
    with open(path, encoding='utf-8') as f:
        return Scenario.from_dict(json.load(f))


def save_scenario(name: str, scenario: Scenario, directory: Path = SCENARIOS_DIR) -> None:
    with open(_path(name, directory), 'w', encoding='utf-8') as f:
        json.dump(scenario.to_dict(), f, indent=2, ensure_ascii=False)
        f.write('\n')


def delete_scenario(name: str, directory: Path = SCENARIOS_DIR) -> None:
    path = _path(name, directory)
    if path.exists():
        path.unlink()


def peek_version(name: str, directory: Path = SCENARIOS_DIR) -> Any:
    """Lit juste le champ 'version' d'un document de scénario, sans le valider
    contre un schéma précis — sert à choisir entre le loader v1 (ce module) et
    le loader v2 (tsm.domain.reference) avant de parser pour de bon."""
    path = _path(name, directory)
    if not path.exists():
        raise ScenarioError(f'scénario introuvable: {name}')
    with open(path, encoding='utf-8') as f:
        doc = json.load(f)
    return doc.get('version') if isinstance(doc, dict) else None
