"""Assemblage du runtime : client ROS + planner + exécution.

main(scenario_name, profile_name) dispatche vers :
- _main_v1 : legacy, un thread runner par agent (inchangé) ;
- _main_v3 : profil d'exécution donné — boucle de contrôle unique
  (tsm.execution.controller.RunController), pas de thread agent, provenance
  écrite dans logs/<run_id>/ (tsm.web.runs).

Ce module (et lui seul, avec tsm.lotusim.client) touche rclpy — jamais
importé par les tests ni par tsm.web.
"""
from __future__ import annotations

import dataclasses
import json
import threading
import time
from typing import Any

import rclpy

from tsm.domain import doctrine
from tsm.domain.profile import PROFILES_DIR, load_profile
from tsm.domain.reference import compile_authored_graph, load_reference_scenario
from tsm.domain.scenario import load_scenario
from tsm.execution.actions import aller_a, creation_agent, make_commands
from tsm.execution.controller import RunController, RunStartError
from tsm.execution.runner import RunLogs, run_agent
from tsm.execution.white_cell import WhiteCell, WhiteCellEvent
from tsm.execution.world import WorldStore, wait_first_observation
from tsm.lotusim.client import LotusimClient
from tsm.planning import methods
from tsm.planning.planner import Planner, build_state
from tsm.web.runs import REPO_ROOT, create_run_directory, next_run_id, write_report

_TICK_TIMEOUT_S = 0.5  # court : laisse passer le SIGINT sans attente notable


def main(scenario_name: str, profile_name: str | None = None) -> None:
    if profile_name is not None:
        _main_v3(scenario_name, profile_name)
    else:
        _main_v1(scenario_name)


# ── v1 : legacy, un thread par agent (inchangé) ──────────────────────────────

def _main_v1(scenario_name: str) -> None:
    scenario = load_scenario(scenario_name)   # échoue AVANT d'initialiser ROS
    kb = doctrine.load()

    rclpy.init()
    logs = None
    client = None
    try:
        logs = RunLogs()
        client = LotusimClient(on_pose=logs.log_pose)
        logs.log_event('run_start', scenario=scenario_name, agents=list(scenario.agents))
        planner = Planner(kb, actions=(aller_a, creation_agent),
                          commands=make_commands(client, logs))
        state = build_state(scenario)

        client.log_info(f'[HTN] Scénario : {scenario_name}')
        for name, spec in scenario.agents.items():
            plan = planner.find_plan(state, spec.mission.to_htn_task())
            client.log_info(f'[HTN] {name}: {plan}')
            logs.log_event('plan_preview', agent=name, plan=str(plan))

        for name, spec in scenario.agents.items():
            try:
                client.spawn_vessel(name, (spec.position.lat, spec.position.lon),
                                    spec.model, spec.linear_velocity,
                                    spec.angular_velocity_max, heading_deg=spec.heading_deg)
                logs.log_event('spawn', agent=name)
            except Exception as e:
                client.log_error(f"[spawn] échec pour '{name}' (model={spec.model!r}): {e}")
                logs.log_event('spawn_error', agent=name, error=str(e))
            time.sleep(3.0)

        threads = []
        for name, spec in scenario.agents.items():
            # Quelles positions ce mission-thread doit-il surveiller : tous les
            # tokens atteignables depuis sa tâche de mission, résolus sur l'état
            # initial (best-effort — le filet REPLAN_SAFETY_TIMEOUT couvre les
            # changements d'identité de cible en cours de run).
            tokens = methods.collect_watched_tokens(kb, spec.mission.task)
            watched = methods.resolve_watched_agents(state, name, tokens)
            threads.append(threading.Thread(
                target=run_agent,
                args=(name, spec.mission.to_htn_task(), state, planner, client, logs, watched),
                daemon=True,
            ))
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    except KeyboardInterrupt:
        pass
    finally:
        if logs:
            logs.log_event('run_end')
            logs.close()
        if client:
            client.shutdown()
        # Le handler SIGINT de rclpy a pu invalider le contexte avant nous :
        # re-shutdown lèverait RCLError et transformerait un arrêt propre en rc=1.
        if rclpy.ok():
            rclpy.shutdown()


# ── v3 : boucle de contrôle unique, provenance, verdict ──────────────────────

class _LoggingTransport:
    """Enveloppe le client LOTUSim réel avec les mêmes commandes que le
    _Transport de RunController, plus waypoints.csv (rôle inchangé — décision
    6 : la carte live de l'IHM fonctionne aussi pour les runs v3)."""

    def __init__(self, client: LotusimClient, logs: RunLogs) -> None:
        self._client = client
        self._logs = logs

    def spawn_vessel(self, vessel: str, init_pos: tuple[float, float], model: str,
                     linear_velocity: Any, angular_velocity_max: float,
                     heading_deg: float) -> str:
        return self._client.spawn_vessel(vessel, init_pos, model, linear_velocity,
                                         angular_velocity_max, heading_deg=heading_deg)

    def delete_vessel(self, agent: str) -> None:
        self._client.delete_vessel(agent)

    def set_waypoints(self, agent: str, lat: float, lon: float) -> None:
        self._client.set_waypoints(agent, lat, lon)
        self._logs.log_waypoint(agent, lat, lon)

    def stop_vessel(self, agent: str) -> None:
        self._client.stop_vessel(agent)

    def wait_ready(self, agent: str, timeout_s: float) -> None:
        self._client.wait_ready(agent, timeout_s)


def _publish_event_factory(logs: RunLogs, run_result: dict[str, Any]) -> Any:
    """publish_event partagé par RunController et WhiteCell : journalise tout
    dans events.jsonl (temps simulé), et capture le verdict métier terminal
    dès qu'il est publié (le contrôleur ne le rend pas, seul son événement le
    porte — cf. RunController.tick)."""

    def publish_event(event: Any) -> None:
        if isinstance(event, WhiteCellEvent):
            # Le verdict terminal est publié DEUX fois le même tick :
            # WhiteCell._finish (WhiteCellEvent) puis RunController.tick (dict
            # {'type': 'verdict', verdict + reason + sim_time_s} — celui qui
            # alimente run_result). Le dict du contrôleur est canonique : on
            # saute celui-ci pour n'avoir qu'UNE ligne verdict dans events.jsonl.
            if event.kind == 'verdict':
                return
            payload = dataclasses.asdict(event)  # décision 6 : conversion à la frontière
            logs.log_event(payload['kind'], sim_time_s=payload['sim_time_s'], **payload['fields'])
            return
        fields = dict(event)
        kind = fields.pop('type')
        sim_time_s = fields.pop('sim_time_s', None)
        logs.log_event(kind, sim_time_s=sim_time_s, **fields)
        if kind == 'verdict':
            run_result.update(verdict=fields['verdict'], reason=fields.get('reason'),
                              finished_sim_time_s=sim_time_s)

    return publish_event


def _main_v3(scenario_name: str, profile_name: str) -> None:
    scenario = load_reference_scenario(scenario_name)   # échoue AVANT d'initialiser ROS
    profile = load_profile(profile_name)
    kb = doctrine.load()
    with open(PROFILES_DIR / f'{profile_name}.json', encoding='utf-8') as f:
        profile_doc = json.load(f)

    logs_dir = REPO_ROOT / 'logs'
    run_dir = create_run_directory(logs_dir, next_run_id(logs_dir), scenario.to_dict(),
                                   profile_doc, kb)

    rclpy.init()
    logs = None
    client = None
    world_store = WorldStore()
    run_result: dict[str, Any] = {}
    controller: RunController | None = None
    started_sim_time_s = 0.0
    loop_exited_cleanly = False
    try:
        logs = RunLogs(run_dir)
        wake = threading.Event()

        def on_world_update(sim_time_s: float, poses: dict[str, Any]) -> None:
            # Thread executor ROS : décision 5 — ne fait QUE ça (pas de CSV ici,
            # cf. la boucle principale qui journalise poses.csv depuis le snapshot).
            world_store.update_poses(sim_time_s, poses)
            wake.set()

        client = LotusimClient(on_world_update=on_world_update)
        transport = _LoggingTransport(client, logs)
        publish_event = _publish_event_factory(logs, run_result)

        # WhiteCell et RunController se référencent mutuellement (spawn_force/
        # stop → controller, submit_attack → white_cell) : composition par
        # boîte mutable, comme les tests de Task 6 (tests/reference_fixtures.py).
        controller_box: dict[str, RunController] = {}
        white_cell = WhiteCell(
            scenario, profile, world_store,
            spawn_force=lambda force: controller_box['c'].spawn_force(force),
            delete_vessel=transport.delete_vessel,
            publish_event=publish_event,
            stop=lambda reason: controller_box['c'].stop(reason))
        controller = RunController(
            scenario=scenario, graph=compile_authored_graph(scenario), profile=profile,
            world_store=world_store, white_cell=white_cell, transport=transport,
            publish_event=publish_event)
        controller_box['c'] = controller

        logs.log_event('run_start', scenario=scenario_name, profile=profile_name,
                       agents=list(scenario.agents))
        if not wait_first_observation(world_store, wake, timeout_s=3.0):
            # Pas de pose : monde vide-mais-vivant (l'entity manager ne publie
            # rien sans navire — constaté sur monde neuf) OU simulateur absent.
            # Départage par la disponibilité du serveur d'action MASCmd : un
            # monde vide se purge trivialement, un simulateur muet reste un
            # échec explicite avant tout spawn.
            if not client.wait_sim_ready(timeout_s=7.0):
                raise RunStartError(
                    'aucune observation du monde reçue (poses LOTUSim indisponibles)')
        controller.start_initial_forces()
        started_sim_time_s = world_store.snapshot().sim_time_s

        while rclpy.ok() and 'verdict' not in run_result:
            wake.wait(timeout=_TICK_TIMEOUT_S)  # timeout court : laisse passer le SIGINT
            wake.clear()
            snapshot = world_store.snapshot()
            for name, pos in snapshot.positions.items():
                logs.log_pose(name, pos.lat, pos.lon, sim_time_s=snapshot.sim_time_s)
            controller.tick(snapshot)
        loop_exited_cleanly = True
    except KeyboardInterrupt:
        loop_exited_cleanly = True
    finally:
        # Boucle sortie sans verdict métier : soit un SIGINT (rclpy.ok() est
        # devenu faux), soit KeyboardInterrupt — jamais une RunStartError de
        # préflight (loop_exited_cleanly reste False dans ce cas, le verdict
        # reste 'pending', pas de report.json : cf. RunManager.status()).
        if loop_exited_cleanly and controller is not None and 'verdict' not in run_result:
            # Le handler SIGINT de rclpy peut avoir invalidé le contexte : toute
            # annulation transport (stop_vessel → create_client) lèverait RCLError
            # et avorterait ce finally (ni report ni run_end, rc=1). Contexte mort
            # ⇒ pas d'annulation physique — la purge préflight du run suivant
            # ramasse les navires encore en route.
            if rclpy.ok():
                controller.stop('sigint')
            finished = world_store.snapshot().sim_time_s
            run_result.update(verdict='cancelled', reason=None, finished_sim_time_s=finished)
            if logs:
                logs.log_event('verdict', sim_time_s=finished, verdict='cancelled', reason=None)
        if run_result.get('verdict'):
            write_report(run_dir, run_result['verdict'], run_result.get('reason'),
                        started_sim_time_s, run_result.get('finished_sim_time_s'))
        if logs:
            logs.log_event('run_end', sim_time_s=run_result.get('finished_sim_time_s'))
            logs.close()
        if client:
            client.shutdown()
        # Le handler SIGINT de rclpy a pu invalider le contexte avant nous :
        # re-shutdown lèverait RCLError et transformerait un arrêt propre en rc=1.
        if rclpy.ok():
            rclpy.shutdown()
