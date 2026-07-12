"""Boucle agent événementielle et logs CSV du run. Aucun import ROS :
le client est reçu en paramètre (duck-typé), la boucle interroge client.ok()."""
from __future__ import annotations

import csv
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Si aucune position surveillée n'a changé après ce délai, on re-vérifie quand
# même — filet de sécurité (une watch ratée, une résolution de token qui a
# changé), pas le rythme normal (c'est l'événement wake-on-change).
REPLAN_SAFETY_TIMEOUT = 5.0
POSITION_HISTORY_LEN = 5


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')


class RunLogs:
    """poses.csv + waypoints.csv + events.jsonl, flushés à chaque ligne —
    sans flush, un kill brutal laissait un gros bloc dans le buffer OS
    (observé : une plage de NUL à la relecture)."""

    def __init__(self, directory: Any = 'logs') -> None:
        d = Path(directory)
        d.mkdir(exist_ok=True)
        self._pose_f = open(d / 'poses.csv', 'w', newline='')
        self._wp_f = open(d / 'waypoints.csv', 'w', newline='')
        self._events_f = open(d / 'events.jsonl', 'w')
        self._pose = csv.writer(self._pose_f)
        self._wp = csv.writer(self._wp_f)
        self._wp_lock = threading.Lock()
        self._events_lock = threading.Lock()
        self._pose.writerow(['timestamp', 'agent', 'lat', 'lon'])
        self._wp.writerow(['timestamp', 'agent', 'lat', 'lon'])

    def log_pose(self, agent: str, lat: float, lon: float,
                 sim_time_s: float | None = None) -> None:
        # appelé depuis le callback du client — sérialisé par le callback group mutuellement exclusif de l'executor, pas par le verrou du client (on_pose est appelé hors verrou)
        # sim_time_s (v3, sur world_store.update_poses) prime sur l'horodatage
        # mur (_ts(), legacy v1 via on_pose) — même colonne, sémantique différente.
        self._pose.writerow([sim_time_s if sim_time_s is not None else _ts(), agent, lat, lon])
        self._pose_f.flush()

    def log_waypoint(self, agent: str, lat: float, lon: float) -> None:
        with self._wp_lock:  # appelé par les commands depuis les threads agents
            self._wp.writerow([_ts(), agent, lat, lon])
            self._wp_f.flush()

    def log_event(self, kind: str, sim_time_s: float | None = None, **fields: Any) -> None:
        # appelé depuis les threads agents ET le thread principal ; sim_time_s
        # est la source de vérité temporelle (temps simulé), 't' ne sert plus
        # qu'à l'affichage mur.
        with self._events_lock:
            event = {'t': _ts(), 'sim_time_s': sim_time_s, 'kind': kind, **fields}
            self._events_f.write(json.dumps(event) + '\n')
            self._events_f.flush()

    def close(self) -> None:
        self._pose_f.close()
        self._wp_f.close()
        self._events_f.close()


def sync_positions(state: Any, client: Any) -> None:
    """Recopie les poses observées dans l'état de planification + historique
    court (les préconditions distance_* calculent tout depuis ces positions)."""
    for name in state.agents:
        pos = client.get_pose(name)
        if pos:
            old = state.agents[name].get('pos')
            if old and (old['lat'] != pos['lat'] or old['lon'] != pos['lon']):
                hist = state.position_history.setdefault(name, [])
                hist.append(old)
                state.position_history[name] = hist[-POSITION_HISTORY_LEN:]
            state.agents[name]['pos'] = pos


def run_agent(name: str, task: tuple[Any, ...], state: Any, planner: Any,
              client: Any, logs: Any, watched_names: set[str]) -> None:
    """Replanification événementielle : bloque jusqu'à ce qu'une position
    surveillée change réellement, REPLAN_SAFETY_TIMEOUT en filet."""
    wake = threading.Event()
    for watched in watched_names | {name}:
        client.register_watch(watched, wake)
    client.log_info(f'[{name}] surveille : {sorted(watched_names | {name})}')

    last_plan = None  # aucun plan encore émis : le premier calcul est toujours un changement
    while client.ok():
        sync_positions(state, client)
        plan = planner.find_plan(state, task)
        plan_repr = repr(plan)
        if plan_repr != last_plan:
            last_plan = plan_repr
            if plan is not False and plan:
                logs.log_event('plan', agent=name, plan=[str(a) for a in plan])
            else:
                logs.log_event('plan', agent=name, plan=[], note='inactif')
        if plan is not False and plan:
            client.log_info(f'[{name}] exécute plan: {[a[0] for a in plan]}')
            planner.run_commands(state, plan)
        wake.wait(timeout=REPLAN_SAFETY_TIMEOUT)
        wake.clear()
