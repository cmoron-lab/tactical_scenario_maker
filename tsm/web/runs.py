"""RunManager : cycle de vie du sous-processus runtime (main.py <scenario>,
processus rclpy séparé) et lecture des logs qu'il écrit (events.jsonl,
poses.csv, waypoints.csv). Aucun import ROS : ce module ne fait que piloter
le sous-processus et lire ses fichiers.

Provenance v3 : create_run_directory crée logs/<run_id>/ avec les entrées
immuables du run (scenario/profile/doctrine tels que résolus au lancement,
manifest.json) — écrit par le sous-processus (tsm/execution/runtime.py) avant
de démarrer, jamais réutilisé. write_report écrit le verdict atomiquement à la
fin. RunManager lui-même ne connaît le run_id qu'après coup (découvert dans
logs_dir) : il ne le choisit pas, il le sert."""
from __future__ import annotations

import csv
import json
import os
import re
import signal
import subprocess
import sys
import threading
from collections import deque
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import IO, Any

REPO_ROOT = Path(__file__).resolve().parents[2]

STOP_TIMEOUT = 8.0  # délai avant kill -9 si le SIGINT n'a pas suffi
TRAIL_LEN = 120
_HEADER = ['timestamp', 'agent', 'lat', 'lon']
_RUN_ID_RE = re.compile(r'^r-(\d{6})$')
_ARTIFACT_KINDS = ('report', 'manifest')


class RunBusyError(Exception):
    """Un run est déjà vivant — pas de double launch."""


class RunArtifactError(Exception):
    """run_id invalide, kind invalide ou artefact absent — toujours un 404 côté HTTP."""


def _default_cmd(name: str, profile: str | None = None) -> list[str]:
    if profile is not None:
        return [sys.executable, 'main.py', name, '--profile', profile]
    return [sys.executable, 'main.py', name]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')


# ── Provenance : répertoire de run (tsm/execution/runtime.py écrit dedans) ───

def next_run_id(base_dir: str | Path) -> str:
    """Prochain run_id libre sous base_dir — compteur, jamais réutilisé."""
    existing = [int(m.group(1)) for p in Path(base_dir).glob('r-*')
                if (m := _RUN_ID_RE.match(p.name))]
    return f'r-{max(existing, default=0) + 1:06d}'


def _write_json(path: Path, doc: Any) -> None:
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


def _capabilities_from_profile_doc(profile_doc: Mapping[str, Any]) -> dict[str, list[str]]:
    """Union des capacités déclarées par les providers de chaque agent — même
    dérivation que AgentExecutionSpec.capabilities, sur le document brut (pas
    de dépendance à tsm.domain.profile ici : ce module ne fait que du I/O)."""
    resolved = {}
    for agent, spec in profile_doc.get('agents', {}).items():
        caps: set[str] = set()
        for provider_cfg in spec.get('providers', {}).values():
            caps.update(provider_cfg.get('capabilities', []))
        resolved[agent] = sorted(caps)
    return resolved


def _git_version() -> str | None:
    try:
        result = subprocess.run(['git', 'rev-parse', '--short', 'HEAD'], cwd=REPO_ROOT,
                                capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def create_run_directory(base_dir: str | Path, run_id: str, scenario_doc: Mapping[str, Any],
                          profile_doc: Mapping[str, Any],
                          doctrine_doc: Mapping[str, Any]) -> Path:
    """Crée logs/<run_id>/ avec les entrées immuables du run + manifest.json +
    les fichiers vides que le run va remplir (events.jsonl, poses.csv,
    waypoints.csv). N'écrase jamais un répertoire existant : run_id doit être
    neuf (next_run_id), sinon FileExistsError."""
    run_dir = Path(base_dir) / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    _write_json(run_dir / 'scenario.json', scenario_doc)
    _write_json(run_dir / 'profile.json', profile_doc)
    _write_json(run_dir / 'doctrine.json', doctrine_doc)
    _write_json(run_dir / 'manifest.json', {
        'run_id': run_id,
        'scenario_version': scenario_doc.get('version'),
        'profile_name': profile_doc.get('name'),
        'profile_version': profile_doc.get('version'),
        'capabilities': _capabilities_from_profile_doc(profile_doc),
        'git_version': _git_version(),
    })
    (run_dir / 'events.jsonl').touch()
    (run_dir / 'poses.csv').touch()
    (run_dir / 'waypoints.csv').touch()
    return run_dir


def write_report(run_dir: str | Path, verdict: str, reason: str | None,
                  started_sim_time_s: float | None,
                  finished_sim_time_s: float | None) -> None:
    """Écriture atomique (temp file + os.replace) : un lecteur concurrent
    (RunManager.status()) ne voit jamais un report.json à moitié écrit."""
    run_dir = Path(run_dir)
    doc = {'verdict': verdict, 'reason': reason,
           'started_sim_time_s': started_sim_time_s,
           'finished_sim_time_s': finished_sim_time_s}
    tmp = run_dir / '.report.json.tmp'
    tmp.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    os.replace(tmp, run_dir / 'report.json')


class RunManager:
    """Détient le sous-processus runtime, expose état/événements/poses au
    serveur web. Le serveur HTTP est mono-threadé (requêtes sérialisées) :
    seul le threading.Timer de stop() tourne en dehors, et il ne touche que
    proc.kill() — sûr sans verrou."""

    def __init__(self, cmd: Callable[[str, str | None], list[str]] | None = None,
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
        self._profile: str | None = None
        self._run_id: str | None = None
        self._verdict: str | None = None
        self._verdict_reason: str | None = None

    # -- cycle de vie -----------------------------------------------------

    def launch(self, name: str, profile: str | None = None) -> int:
        if self._proc is not None and self._proc.poll() is None:
            raise RunBusyError('run déjà en cours')
        if self._log_f is not None:
            self._log_f.close()
        self._logs_dir.mkdir(parents=True, exist_ok=True)
        self._log_f = open(self._logs_dir / 'run.log', 'wb')
        self._proc = subprocess.Popen(self._cmd(name, profile), cwd=REPO_ROOT,
                                       stdout=self._log_f, stderr=subprocess.STDOUT)
        self._scenario = name
        self._profile = profile
        self._started_at = _now_iso()
        self._stop_requested = False
        self._pose_offset = 0
        self._wp_offset = 0
        self._agents = {}
        self._run_id = None
        self._verdict = None
        self._verdict_reason = None
        return self._proc.pid

    def stop(self) -> bool:
        if self._proc is None or self._proc.poll() is not None:
            return False
        self._proc.send_signal(signal.SIGINT)
        self._stop_requested = True
        # timer lié à CE process : un relaunch dans la fenêtre ne doit pas être tué
        timer = threading.Timer(STOP_TIMEOUT, self._kill_if_alive, args=(self._proc,))
        timer.daemon = True
        timer.start()
        return True

    @staticmethod
    def _kill_if_alive(proc: subprocess.Popen[bytes]) -> None:
        if proc.poll() is None:
            proc.kill()

    def record_verdict(self, verdict: str, reason: str | None) -> None:
        """Setter direct — utilisé par les tests. En production, le verdict
        vient plutôt de la lecture paresseuse de report.json dans status()."""
        self._verdict = verdict
        self._verdict_reason = reason

    def _discover_run_id(self) -> str | None:
        # ponytail: le run_id n'est pas transmis au sous-processus (l'argv est
        # fixé par la spec : [python, main.py, name, --profile, profile]) — on
        # le déduit du dernier répertoire r-* créé sous logs_dir, mémorisé une
        # fois trouvé. RunBusyError interdit les runs concurrents, donc la
        # seule fenêtre où ça pointerait vers le run PRÉCÉDENT est le court
        # instant entre le spawn et la création du répertoire par le runtime
        # v3 — upgrade si ça devient gênant : faire écrire le run_id découvert
        # dans un fichier connu (logs_dir/current_run_id) par le runtime lui-même.
        if self._profile is None:
            return None
        if self._run_id is not None:
            return self._run_id
        candidates = sorted(
            (p for p in self._logs_dir.glob('r-*') if _RUN_ID_RE.match(p.name)),
            key=lambda p: p.name)
        if candidates:
            self._run_id = candidates[-1].name
        return self._run_id

    def read_artifact(self, run_id: str, kind: str) -> dict[str, Any]:
        if kind not in _ARTIFACT_KINDS or not _RUN_ID_RE.match(run_id):
            raise RunArtifactError(f'artefact invalide: {run_id}/{kind}')
        path = self._logs_dir / run_id / f'{kind}.json'
        if not path.exists():
            raise RunArtifactError(f'introuvable: {path}')
        try:
            doc: dict[str, Any] = json.loads(path.read_text())
        except ValueError as exc:
            raise RunArtifactError(str(exc)) from exc
        return doc

    def status(self) -> dict[str, Any]:
        if self._proc is None:
            state, scenario, pid, returncode = 'idle', None, None, None
        else:
            rc = self._proc.poll()
            if rc is None:
                state = 'running'
            elif rc == 0:
                state = 'finished'
            else:
                state = 'failed'
            scenario, pid, returncode = self._scenario, self._proc.pid, rc

        run_id = self._discover_run_id()
        verdict, reason = self._verdict, self._verdict_reason
        if verdict is None and run_id is not None and state in ('finished', 'failed'):
            try:
                report = self.read_artifact(run_id, 'report')
            except RunArtifactError:
                report = None
            if report is not None:
                verdict = report.get('verdict')
                reason = report.get('reason')

        return {'state': state, 'scenario': scenario, 'pid': pid,
                 'started_at': self._started_at, 'returncode': returncode,
                 'stop_requested': self._stop_requested,
                 'verdict': verdict if verdict is not None else 'pending',
                 'verdict_reason': reason,
                 'profile': self._profile, 'run_id': run_id}

    # -- lecture des logs ---------------------------------------------------

    def _current_dir(self) -> Path:
        # v1 (legacy, self._profile is None) : fichiers plats sous logs_dir,
        # comme toujours. v3 (profile connu) : sous logs_dir/<run_id>/ une fois
        # que le sous-processus l'a créé — voir le ponytail de _discover_run_id
        # pour la fenêtre transitoire où run_id n'est pas encore connu.
        run_id = self._discover_run_id()
        return self._logs_dir / run_id if run_id is not None else self._logs_dir

    def events_since(self, since: int) -> dict[str, Any]:
        path = self._current_dir() / 'events.jsonl'
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
        pose_path = self._current_dir() / 'poses.csv'
        wp_path = self._current_dir() / 'waypoints.csv'
        # le runtime tronque LES DEUX fichiers au lancement d'un nouveau run :
        # détecter la troncature sur l'un OU l'autre et purger UNE seule fois —
        # une purge par fichier effacerait ce que le premier vient de lire
        if ((pose_path.exists() and pose_path.stat().st_size < self._pose_offset)
                or (wp_path.exists() and wp_path.stat().st_size < self._wp_offset)):
            self._pose_offset = 0
            self._wp_offset = 0
            self._agents = {}
        self._consume_pose_file(pose_path, is_waypoint=False)
        self._consume_pose_file(wp_path, is_waypoint=True)
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
