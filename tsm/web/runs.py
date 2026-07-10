"""RunManager : cycle de vie du sous-processus runtime (main.py <scenario>,
processus rclpy séparé) et lecture des logs qu'il écrit (events.jsonl,
poses.csv, waypoints.csv). Aucun import ROS : ce module ne fait que piloter
le sous-processus et lire ses fichiers."""
from __future__ import annotations

import csv
import json
import signal
import subprocess
import sys
import threading
from collections import deque
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import IO, Any

REPO_ROOT = Path(__file__).resolve().parents[2]

STOP_TIMEOUT = 8.0  # délai avant kill -9 si le SIGINT n'a pas suffi
TRAIL_LEN = 120
_HEADER = ['timestamp', 'agent', 'lat', 'lon']


class RunBusyError(Exception):
    """Un run est déjà vivant — pas de double launch."""


def _default_cmd(name: str) -> list[str]:
    return [sys.executable, 'main.py', name]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')


class RunManager:
    """Détient le sous-processus runtime, expose état/événements/poses au
    serveur web. Le serveur HTTP est mono-threadé (requêtes sérialisées) :
    seul le threading.Timer de stop() tourne en dehors, et il ne touche que
    proc.kill() — sûr sans verrou."""

    def __init__(self, cmd: Callable[[str], list[str]] | None = None,
                 logs_dir: str | Path = 'logs') -> None:
        self._cmd = cmd or _default_cmd
        self._logs_dir = Path(logs_dir)
        self._proc: subprocess.Popen[bytes] | None = None
        self._log_f: IO[bytes] | None = None
        self._scenario: str | None = None
        self._started_at: str | None = None
        self._stop_requested = False
        self._pose_offset = 0
        self._wp_offset = 0
        self._agents: dict[str, dict[str, Any]] = {}

    # -- cycle de vie -----------------------------------------------------

    def launch(self, name: str) -> int:
        if self._proc is not None and self._proc.poll() is None:
            raise RunBusyError('run déjà en cours')
        if self._log_f is not None:
            self._log_f.close()
        self._logs_dir.mkdir(parents=True, exist_ok=True)
        self._log_f = open(self._logs_dir / 'run.log', 'wb')
        self._proc = subprocess.Popen(self._cmd(name), cwd=REPO_ROOT,
                                       stdout=self._log_f, stderr=subprocess.STDOUT)
        self._scenario = name
        self._started_at = _now_iso()
        self._stop_requested = False
        self._pose_offset = 0
        self._wp_offset = 0
        self._agents = {}
        return self._proc.pid

    def stop(self) -> bool:
        if self._proc is None or self._proc.poll() is not None:
            return False
        self._proc.send_signal(signal.SIGINT)
        self._stop_requested = True
        timer = threading.Timer(STOP_TIMEOUT, self._kill_if_alive)
        timer.daemon = True
        timer.start()
        return True

    def _kill_if_alive(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            self._proc.kill()

    def status(self) -> dict[str, Any]:
        if self._proc is None:
            return {'state': 'idle', 'scenario': None, 'pid': None,
                     'started_at': None, 'returncode': None, 'stop_requested': False}
        rc = self._proc.poll()
        if rc is None:
            state = 'running'
        elif rc == 0:
            state = 'finished'
        else:
            state = 'failed'
        return {'state': state, 'scenario': self._scenario, 'pid': self._proc.pid,
                 'started_at': self._started_at, 'returncode': rc,
                 'stop_requested': self._stop_requested}

    # -- lecture des logs ---------------------------------------------------

    def events_since(self, since: int) -> dict[str, Any]:
        path = self._logs_dir / 'events.jsonl'
        if not path.exists():
            return {'events': [], 'next': 0}
        events = []
        for line in path.read_text().splitlines():
            try:
                events.append(json.loads(line))
            except ValueError:
                continue  # ligne invalide (écriture en cours, ou ailleurs) : ignorée, non comptée
        return {'events': events[since:], 'next': len(events)}

    def poses(self) -> dict[str, Any]:
        self._consume_pose_file(self._logs_dir / 'poses.csv', is_waypoint=False)
        self._consume_pose_file(self._logs_dir / 'waypoints.csv', is_waypoint=True)
        return {'agents': {
            name: {'lat': a['lat'], 'lon': a['lon'], 't': a['t'],
                   'trail': [list(p) for p in a['trail']], 'waypoint': a['waypoint']}
            for name, a in self._agents.items()
        }}

    def _consume_pose_file(self, path: Path, is_waypoint: bool) -> None:
        offset_attr = '_wp_offset' if is_waypoint else '_pose_offset'
        if not path.exists():
            return
        offset = getattr(self, offset_attr)
        if path.stat().st_size < offset:
            offset = 0
            self._agents = {}  # troncature (nouveau run) : état accumulé périmé
        with open(path, 'rb') as f:
            f.seek(offset)
            data = f.read()
        if data.endswith(b'\n'):
            consumed = data
        else:
            idx = data.rfind(b'\n')
            consumed = data[:idx + 1] if idx != -1 else b''  # dernière ligne partielle : laissée pour le prochain appel
        setattr(self, offset_attr, offset + len(consumed))
        for row in csv.reader(consumed.decode().splitlines()):
            if not row or row == _HEADER:
                continue
            ts, agent, lat, lon = row
            entry = self._agents.setdefault(
                agent, {'lat': None, 'lon': None, 't': None,
                        'trail': deque(maxlen=TRAIL_LEN), 'waypoint': None})
            if is_waypoint:
                entry['waypoint'] = [float(lat), float(lon)]
            else:
                entry['lat'], entry['lon'], entry['t'] = float(lat), float(lon), ts
                entry['trail'].append([float(lat), float(lon)])
