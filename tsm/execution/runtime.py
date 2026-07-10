"""Assemblage du runtime : client ROS + planner + un thread runner par agent.

Ce module (et lui seul, avec tsm.lotusim.client) touche rclpy — jamais
importé par les tests ni par tsm.web.
"""
from __future__ import annotations

import threading
import time

import rclpy

from tsm.domain import doctrine
from tsm.domain.scenario import load_scenario
from tsm.execution.actions import aller_a, creation_agent, make_commands
from tsm.execution.runner import RunLogs, run_agent
from tsm.lotusim.client import LotusimClient
from tsm.planning import methods
from tsm.planning.planner import Planner, build_state


def main(scenario_name: str) -> None:
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
                                    spec.angular_velocity_max, heading=spec.heading_deg)
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
