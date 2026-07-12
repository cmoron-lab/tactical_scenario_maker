"""Handlers de l'API locale — parlent le schéma canonique, aucun import ROS."""
from __future__ import annotations

from typing import Any

from tsm.domain import doctrine
from tsm.domain.profile import list_profiles
from tsm.domain.reference import SCHEMA_VERSION as SCENARIO_V2_VERSION
from tsm.domain.reference import load_reference_scenario
from tsm.domain.scenario import (Scenario, ScenarioError, delete_scenario,
                                 list_scenarios, load_scenario, peek_version,
                                 save_scenario)
from tsm.execution.actions import aller_a, creation_agent
from tsm.planning.planner import Planner, build_state
from tsm.web.runs import REPO_ROOT, RunManager


class Api:
    def __init__(self, run_manager: RunManager | None = None) -> None:
        self._planner = Planner(doctrine.load(), actions=(aller_a, creation_agent))
        # logs_dir ancré au repo : le serveur peut être lancé d'ailleurs que la racine,
        # le runtime écrit toujours dans REPO_ROOT/logs (cwd du Popen).
        self._runs = run_manager or RunManager(logs_dir=REPO_ROOT / 'logs')

    def scenarios(self) -> list[str]:
        return list_scenarios()

    def profiles(self) -> list[str]:
        return list_profiles()

    def get_kb(self) -> dict[str, Any]:
        return doctrine.load()

    def save_kb(self, kb: dict[str, Any]) -> dict[str, Any]:
        doctrine.save(kb)
        self._planner.reload_kb(kb)
        return {'ok': True}

    def get_scenario(self, name: str) -> dict[str, Any]:
        if peek_version(name) == SCENARIO_V2_VERSION:
            return load_reference_scenario(name).to_dict()
        return load_scenario(name).to_dict()

    def save_scenario(self, name: str, doc: dict[str, Any]) -> dict[str, Any]:
        save_scenario(name, Scenario.from_dict(doc))
        return {'ok': True}

    def delete_scenario(self, name: str) -> dict[str, Any]:
        delete_scenario(name)
        return {'ok': True}

    def plan(self, name: str) -> dict[str, str]:
        scenario = load_scenario(name)
        state = build_state(scenario)
        results = {}
        for aname, spec in scenario.agents.items():
            try:
                plan = self._planner.find_plan(state, spec.mission.to_htn_task())
                if plan is False:
                    results[aname] = 'Aucun plan applicable (préconditions non satisfaites)'
                elif not plan:
                    results[aname] = '[] — inactif (drone géré par agent dédié)'
                else:
                    results[aname] = str(plan)
            except Exception as e:  # préview best-effort : l'erreur est LE résultat affiché
                results[aname] = f'Erreur: {e}'
        return results

    def launch(self, name: str, profile: str | None = None) -> dict[str, Any]:
        # refus propre (400) avant de lancer quoi que ce soit : schéma du
        # scénario ET cohérence version/profil (v2 exige un profil, v1 le refuse).
        if peek_version(name) == SCENARIO_V2_VERSION:
            load_reference_scenario(name)
            if profile is None:
                raise ScenarioError(
                    f"le scénario {name!r} (v2) nécessite un profil d'exécution")
            if profile not in list_profiles():
                # sinon le sous-processus mourrait avant create_run_directory :
                # run failed sans run_id ni verdict — refus AVANT le spawn.
                raise ScenarioError(f'profil inconnu: {profile!r}')
        else:
            load_scenario(name)
            if profile is not None:
                raise ScenarioError(f"le scénario {name!r} (v1) ne prend pas de profil")
        pid = self._runs.launch(name, profile)  # RunBusyError (409) si un run est déjà vivant
        return {'ok': True, 'pid': pid}

    def run_status(self) -> dict[str, Any]:
        return self._runs.status()

    def run_events(self, since: int) -> dict[str, Any]:
        return self._runs.events_since(since)

    def run_poses(self) -> dict[str, Any]:
        return self._runs.poses()

    def run_stop(self) -> dict[str, Any]:
        return {'ok': self._runs.stop()}

    def run_artifact(self, run_id: str, kind: str) -> dict[str, Any]:
        return self._runs.read_artifact(run_id, kind)
