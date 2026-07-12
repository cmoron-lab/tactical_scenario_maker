"""Snapshots immuables de l'état observé du monde.

La pose observée et son horodatage simulé sont la seule source de vérité —
jamais la cible commandée. WorldStore détient l'état mutable ; chaque mutation
copie les mappings, incrémente la revision, et snapshot() ne rend jamais les
dictionnaires internes. Les superviseurs ne reçoivent que des WorldSnapshot.
"""
from __future__ import annotations

import threading
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from tsm.domain.scenario import Position


@dataclass(frozen=True)
class WorldSnapshot:
    revision: int
    sim_time_s: float
    positions: Mapping[str, Position]
    destroyed: frozenset[str]


class WorldStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._revision = 0
        self._sim_time_s = 0.0
        self._positions: dict[str, Position] = {}
        self._destroyed: set[str] = set()

    def update_poses(self, sim_time_s: float, positions: Mapping[str, Position]) -> WorldSnapshot:
        """Remplace intégralement les positions par `positions` : chaque
        VesselPositionArray transporte la flotte complète. `destroyed` est
        préservé (monotone), pas réinitialisé par une observation de pose."""
        with self._lock:
            self._sim_time_s = sim_time_s
            self._positions = dict(positions)
            self._revision += 1
            return self.snapshot()

    def mark_destroyed(self, agent: str) -> WorldSnapshot:
        with self._lock:
            self._destroyed.add(agent)
            self._revision += 1
            return self.snapshot()

    def snapshot(self) -> WorldSnapshot:
        with self._lock:
            return WorldSnapshot(
                revision=self._revision,
                sim_time_s=self._sim_time_s,
                positions=MappingProxyType(dict(self._positions)),
                destroyed=frozenset(self._destroyed),
            )
