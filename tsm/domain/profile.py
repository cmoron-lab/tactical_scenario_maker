"""Schéma du profil d'exécution (le « comment ») : fidélité, providers, spawn
et capacités par agent, et validation statique contre les missions déclarées
dans le Scenario Request.

Un profil est un document JSON {"version": 1, "name": ..., "agents": {...}}.
Son identité est son nom de fichier (sans extension) dans profiles/. Il est
distinct du Scenario Request v2 (tsm/domain/reference.py) : un même scénario
peut être exécuté avec des profils différents.
"""
from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from tsm.domain.reference import ReferenceScenario

PROFILE_SCHEMA_VERSION = 1
PROFILES_DIR = Path(__file__).resolve().parents[2] / 'profiles'
_NAME_RE = re.compile(r'^[A-Za-z0-9_-]+$')

_KINEMATIC_PROVIDER = 'lotusim.waypoint_follower'
_KINEMATIC_CAPABILITIES = frozenset({'navigation.goto', 'navigation.follow_target'})
_ADJUDICATED_PROVIDER = 'adjudicated'
_ADJUDICATED_CAPABILITIES = frozenset({'engage.attack_target'})
_PROVIDER_CAPABILITY_LIMITS = {
    _KINEMATIC_PROVIDER: _KINEMATIC_CAPABILITIES,
    _ADJUDICATED_PROVIDER: _ADJUDICATED_CAPABILITIES,
}


class ProfileError(ValueError):
    """Profil d'exécution invalide, incomplet ou incompatible avec le scénario."""


@dataclass(frozen=True)
class AgentExecutionSpec:
    fidelity: Literal["kinematic", "scripted", "dynamic"]
    providers: Mapping[str, Mapping[str, Any]]
    spawn: Mapping[str, Any]

    @property
    def capabilities(self) -> frozenset[str]:
        """Union des capacités déclarées par tous les providers de l'agent."""
        caps: set[str] = set()
        for provider_config in self.providers.values():
            caps.update(provider_config.get('capabilities', []))
        return frozenset(caps)

    @classmethod
    def from_dict(cls, doc: Any, where: str) -> AgentExecutionSpec:
        if not isinstance(doc, dict):
            raise ProfileError(f'{where} doit être un objet')
        fidelity_raw = doc.get('fidelity')
        if fidelity_raw not in ('kinematic', 'scripted', 'dynamic'):
            raise ProfileError(f'{where}.fidelity invalide: {fidelity_raw!r}')
        providers = doc.get('providers')
        if not isinstance(providers, dict) or not providers:
            raise ProfileError(f'{where}.providers manquant ou vide')
        for provider_name, provider_config in providers.items():
            capabilities = (provider_config.get('capabilities')
                             if isinstance(provider_config, dict) else None)
            if not isinstance(capabilities, list) or not all(
                    isinstance(c, str) for c in capabilities):
                raise ProfileError(
                    f'{where}.providers.{provider_name}.capabilities manquant ou invalide')
        spawn = doc.get('spawn')
        if not isinstance(spawn, dict):
            raise ProfileError(f'{where}.spawn manquant')
        for spawn_field in ('model', 'linear_velocity', 'angular_velocity_max', 'heading_deg'):
            if spawn_field not in spawn:
                raise ProfileError(f'{where}.spawn.{spawn_field} manquant')
        return cls(fidelity=cast(Literal["kinematic", "scripted", "dynamic"], fidelity_raw),
                   providers=providers, spawn=spawn)


@dataclass(frozen=True)
class ExecutionProfile:
    name: str
    agents: Mapping[str, AgentExecutionSpec]

    @classmethod
    def from_dict(cls, doc: Any) -> ExecutionProfile:
        if not isinstance(doc, dict):
            raise ProfileError('le document doit être un objet JSON')
        if doc.get('version') != PROFILE_SCHEMA_VERSION:
            raise ProfileError(
                f'version inconnue: {doc.get("version")!r} (attendu {PROFILE_SCHEMA_VERSION})')
        name = doc.get('name')
        if not isinstance(name, str) or not name:
            raise ProfileError('name manquant')
        agents_doc = doc.get('agents')
        if not isinstance(agents_doc, dict):
            raise ProfileError('agents manquant ou invalide')
        return cls(
            name=name,
            agents={agent: AgentExecutionSpec.from_dict(a, where=f'agents.{agent}')
                    for agent, a in agents_doc.items()},
        )


def validate_profile(scenario: ReferenceScenario, profile: ExecutionProfile,
                      required_capabilities: Mapping[str, set[str]]) -> None:
    """Validation statique du couple (scénario, profil) : couverture des
    agents, capacités permises par provider et capacités requises par les
    missions assignées. Une dégradation de fidélité est interdite : toute
    incompatibilité bloque avant l'exécution."""
    for agent in scenario.agents:
        if agent not in profile.agents:
            raise ProfileError(f"agent {agent!r} sans profil d'exécution")

    for agent, spec in profile.agents.items():
        for provider_name, provider_config in spec.providers.items():
            allowed = _PROVIDER_CAPABILITY_LIMITS.get(provider_name)
            if allowed is None:
                continue
            declared = set(provider_config.get('capabilities', []))
            extra = declared - allowed
            if extra:
                raise ProfileError(
                    f'agents.{agent}.providers.{provider_name} déclare des capacités '
                    f'non permises: {sorted(extra)}')

    for agent, required in required_capabilities.items():
        assigned_spec = profile.agents.get(agent)
        if assigned_spec is None:
            raise ProfileError(f"agent {agent!r} sans profil d'exécution")
        missing = set(required) - assigned_spec.capabilities
        if missing:
            raise ProfileError(
                f'{agent}: capacité(s) manquante(s) pour la mission assignée: {sorted(missing)}')


# ── Store fichiers ────────────────────────────────────────────────────────────

def _path(name: str, directory: Path) -> Path:
    if not _NAME_RE.match(name):
        raise ProfileError(f'nom de profil invalide: {name!r}')
    return directory / f'{name}.json'


def load_profile(name: str, directory: Path = PROFILES_DIR) -> ExecutionProfile:
    path = _path(name, directory)
    if not path.exists():
        raise ProfileError(f'profil introuvable: {name}')
    with open(path, encoding='utf-8') as f:
        return ExecutionProfile.from_dict(json.load(f))
