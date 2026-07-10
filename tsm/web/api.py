"""Handlers de l'API locale — parlent le schéma canonique, aucun import ROS."""
from __future__ import annotations

from typing import Any

from tsm.domain import doctrine
from tsm.domain.scenario import (Scenario, delete_scenario, list_scenarios,
                                 load_scenario, save_scenario)
from tsm.execution.actions import aller_a, creation_agent
from tsm.planning.planner import Planner, build_state
from tsm.web.runs import RunManager


class Api:
    def __init__(self, run_manager: RunManager | None = None) -> None:
        self._planner = Planner(doctrine.load(), actions=(aller_a, creation_agent))
        self._runs = run_manager or RunManager()

    def scenarios(self) -> list[str]:
        return list_scenarios()

    def get_kb(self) -> dict[str, Any]:
        return doctrine.load()

    def save_kb(self, kb: dict[str, Any]) -> dict[str, Any]:
        doctrine.save(kb)
        self._planner.reload_kb(kb)
        return {'ok': True}

    def get_scenario(self, name: str) -> dict[str, Any]:
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

    def launch(self, name: str) -> dict[str, Any]:
        load_scenario(name)  # refus propre (400) avant de lancer quoi que ce soit
        pid = self._runs.launch(name)  # RunBusyError (409) si un run est déjà vivant
        return {'ok': True, 'pid': pid}

    def run_status(self) -> dict[str, Any]:
        return self._runs.status()

    def run_events(self, since: int) -> dict[str, Any]:
        return self._runs.events_since(since)

    def run_poses(self) -> dict[str, Any]:
        return self._runs.poses()

    def run_stop(self) -> dict[str, Any]:
        return {'ok': self._runs.stop()}
