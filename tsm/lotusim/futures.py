"""Vérification pure d'un future ROS — aucun import rclpy/lotusim_msgs.

Extrait de LotusimClient pour permettre un test de contrat de transport sans
ROS : FutureLike est le protocole local (done/result/exception) que
rclpy.task.Future satisfait déjà.
"""
from __future__ import annotations

from typing import Any, Protocol


class FutureLike(Protocol):
    def done(self) -> bool:
        pass

    def result(self) -> Any:
        pass

    def exception(self) -> BaseException | None:
        pass


def require_result(future: FutureLike, operation: str) -> Any:
    if not future.done():
        raise RuntimeError(f"{operation}: timeout")
    if future.exception() is not None:
        raise RuntimeError(f"{operation}: {future.exception()}")
    return future.result()
