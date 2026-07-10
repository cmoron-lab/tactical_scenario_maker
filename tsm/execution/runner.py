"""Boucle agent événementielle et logs CSV du run. Aucun import ROS :
le client est reçu en paramètre (duck-typé), la boucle interroge client.ok()."""
from __future__ import annotations

import csv
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
    """poses.csv + waypoints.csv, flushés à chaque ligne — sans flush, un kill
    brutal laissait un gros bloc dans le buffer OS (observé : une plage de NUL
    à la relecture)."""

    def __init__(self, directory: Any = 'logs') -> None:
        d = Path(directory)
        d.mkdir(exist_ok=True)
        self._pose_f = open(d / 'poses.csv', 'w', newline='')
        self._wp_f = open(d / 'waypoints.csv', 'w', newline='')
        self._pose = csv.writer(self._pose_f)
        self._wp = csv.writer(self._wp_f)
        self._wp_lock = threading.Lock()
        self._pose.writerow(['timestamp', 'agent', 'lat', 'lon'])
        self._wp.writerow(['timestamp', 'agent', 'lat', 'lon'])

    def log_pose(self, agent: str, lat: float, lon: float) -> None:
        # appelé depuis le callback du client — sérialisé par le callback group mutuellement exclusif de l'executor, pas par le verrou du client (on_pose est appelé hors verrou)
        self._pose.writerow([_ts(), agent, lat, lon])
        self._pose_f.flush()

    def log_waypoint(self, agent: str, lat: float, lon: float) -> None:
        with self._wp_lock:  # appelé par les commands depuis les threads agents
            self._wp.writerow([_ts(), agent, lat, lon])
            self._wp_f.flush()

    def close(self) -> None:
        self._pose_f.close()
        self._wp_f.close()


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
              client: Any, watched_names: set[str]) -> None:
    """Replanification événementielle : bloque jusqu'à ce qu'une position
    surveillée change réellement, REPLAN_SAFETY_TIMEOUT en filet."""
    wake = threading.Event()
    for watched in watched_names | {name}:
        client.register_watch(watched, wake)
    client.log_info(f'[{name}] surveille : {sorted(watched_names | {name})}')

    while client.ok():
        sync_positions(state, client)
        plan = planner.find_plan(state, task)
        if plan is not False and plan:
            client.log_info(f'[{name}] exécute plan: {[a[0] for a in plan]}')
            planner.run_commands(state, plan)
        wake.wait(timeout=REPLAN_SAFETY_TIMEOUT)
        wake.clear()
