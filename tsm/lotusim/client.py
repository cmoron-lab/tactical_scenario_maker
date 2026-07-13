"""Adaptateur ROS vers LOTUSim — SEUL module du paquet à importer rclpy.

Possède le nœud et son executor ; expose le spawn, l'envoi de waypoints et
l'observation des poses avec réveil sur changement réel (wake-on-change).
C'est la couture où se brancheront les autonomies de l'architecture cible
(docs/lsga-architecture-v3.md §4.2).
"""
from __future__ import annotations

import math
import threading
from typing import Any, Callable, Optional

import rclpy
from geographic_msgs.msg import GeoPoint
from rclpy.action import ActionClient
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from std_srvs.srv import Empty

from lotusim_msgs.action import MASCmd
from lotusim_msgs.msg import MASCmd as MASCmdMsg
from lotusim_msgs.msg import VesselPositionArray
from lotusim_msgs.srv import SetWaypoints

from tsm.domain.scenario import Position
from tsm.lotusim.futures import require_result

# En dessous, deux positions sont "identiques" (bruit GPS/float) : une mise à
# jour de pose ne réveille pas inutilement les agents qui la surveillent.
POSITION_EPSILON_DEG = 1e-6

MAS_CMD_ACTION = '/lotusim/mas_cmd'


def _wait(fut: Any, timeout: float = 10.0) -> None:
    done = threading.Event()
    fut.add_done_callback(lambda _: done.set())
    done.wait(timeout=timeout)


def _seconds(stamp: Any) -> float:
    return float(stamp.sec) + float(stamp.nanosec) / 1_000_000_000


class LotusimClient:
    def __init__(self, node_name: str = 'goto_point', namespace: str = '/lotusim',
                 on_pose: Optional[Callable[[str, float, float], None]] = None,
                 on_world_update: Optional[Callable[[float, dict[str, Position]], None]] = None
                 ) -> None:
        self._node = Node(node_name, namespace=namespace)
        self._executor = MultiThreadedExecutor()
        self._executor.add_node(self._node)
        threading.Thread(target=self._executor.spin, daemon=True).start()
        self._data: dict[str, dict[str, float]] = {}
        self._lock = threading.Lock()
        self._watchers: dict[str, list[threading.Event]] = {}
        self._on_pose = on_pose
        # Observation groupée (flotte complète + sim_time_s) pour WorldStore
        # (Task 7, v3) — distincte de on_pose, qui notifie agent par agent
        # (legacy v1, register_watch/get_pose).
        self._on_world_update = on_world_update
        self._node.create_subscription(VesselPositionArray, '/lotusim/poses', self._cb, 10)

    # ── Observation des poses ────────────────────────────────────────────

    def _cb(self, msg: VesselPositionArray) -> None:
        poses = {v.vessel_name: Position(v.geo_point.latitude, v.geo_point.longitude)
                 for v in msg.vessels}
        self._on_world(_seconds(msg.header.stamp), poses)

    def _on_world(self, sim_time_s: float, poses: dict[str, Position]) -> None:
        """Point d'entrée unique d'une observation du monde. Le câblage vers
        WorldStore (source de vérité du contrôleur v3) arrive avec le
        contrôleur ; ici on préserve le comportement legacy : self._data pour
        get_pose, réveil des watchers sur changement réel, callback on_pose."""
        to_notify: list[tuple[str, float, float]] = []
        cb = self._on_pose
        with self._lock:
            for name, pos in poses.items():
                new = {'lat': pos.lat, 'lon': pos.lon}
                old = self._data.get(name)
                changed = (
                    old is None
                    or abs(old['lat'] - new['lat']) > POSITION_EPSILON_DEG
                    or abs(old['lon'] - new['lon']) > POSITION_EPSILON_DEG
                )
                self._data[name] = new
                if cb:
                    to_notify.append((name, new['lat'], new['lon']))
                if changed:
                    for ev in self._watchers.get(name, []):
                        ev.set()
        # Callbacks utilisateur hors verrou : évite le self-deadlock si l'un
        # d'eux relit get_pose/register_watch.
        if self._on_world_update:
            self._on_world_update(sim_time_s, poses)
        if cb:
            for name, lat, lon in to_notify:
                cb(name, lat, lon)

    def get_pose(self, name: str) -> Optional[dict[str, float]]:
        with self._lock:
            return self._data.get(name)

    def register_watch(self, name: str, event: threading.Event) -> None:
        """Réveille `event` quand la position de `name` change réellement."""
        with self._lock:
            self._watchers.setdefault(name, []).append(event)

    # ── Commandes LOTUSim ────────────────────────────────────────────────

    def wait_sim_ready(self, timeout_s: float) -> bool:
        """La simulation répond-elle ? (serveur d'action MASCmd disponible.)
        Départage un monde vide-mais-vivant — l'entity manager ne publie pas
        de poses tant qu'aucun navire n'existe — d'un simulateur absent."""
        client = ActionClient(self._node, MASCmd, MAS_CMD_ACTION)
        try:
            return bool(client.wait_for_server(timeout_sec=timeout_s))
        finally:
            client.destroy()

    def _mas_cmd(self, cmd: Any, operation: str, timeout_s: float) -> Any:
        """Envoie un MASCmd (action) et rend le Result (bool result, name,
        entity) validé — done/exception vérifiés via require_result."""
        client = ActionClient(self._node, MASCmd, MAS_CMD_ACTION)
        if not client.wait_for_server(timeout_sec=timeout_s):
            raise RuntimeError(f"{operation}: serveur d'action indisponible ({MAS_CMD_ACTION})")
        goal = MASCmd.Goal()
        goal.cmd = cmd
        goal_future = client.send_goal_async(goal)
        _wait(goal_future, timeout_s)
        goal_handle = require_result(goal_future, operation)
        result_future = goal_handle.get_result_async()
        _wait(result_future, timeout_s)
        return require_result(result_future, operation).result

    def spawn_vessel(self, vessel: str, init_pos: tuple[float, float], model: str,
                     linear_velocity: tuple[float, float], angular_velocity_max: float,
                     heading_deg: float = 0.0, timeout_s: float = 10.0) -> str:
        cmd = MASCmdMsg()
        cmd.cmd_type = MASCmdMsg.CREATE_CMD
        cmd.model_name = model
        cmd.vessel_name = vessel
        cmd.geo_point = GeoPoint(latitude=init_pos[0], longitude=init_pos[1], altitude=0.0)
        # MASCmd.heading est un champ top-level (radians, utilisé tel quel comme yaw
        # par entity_spawner.cpp) — pas un tag SDF. `heading_deg` ici est en degrés
        # (convention scénario/UI), donc conversion.
        cmd.heading = math.radians(heading_deg)
        cmd.sdf_string = f"""
            <lotus_param>
                <waypoint_follower>
                    <follower>
                        <loop>false</loop>
                        <range_tolerance>2</range_tolerance>
                        <linear_velocities_limits>{linear_velocity[0]} {linear_velocity[1]}</linear_velocities_limits>
                        <angular_velocities_limits>{angular_velocity_max}</angular_velocities_limits>
                    </follower>
                </waypoint_follower>
            </lotus_param>
        """
        result = self._mas_cmd(cmd, f"spawn_vessel({vessel})", timeout_s)
        if not result.result:
            raise RuntimeError(f"spawn_vessel({vessel}): échec côté LOTUSim")
        if result.name != vessel:
            raise RuntimeError(
                f"spawn_vessel({vessel}): nom canonique différent ({result.name!r})")
        self._node.get_logger().info(f'Spawned: {result.name}')
        return str(result.name)

    def delete_vessel(self, agent: str, timeout_s: float = 10.0) -> None:
        cmd = MASCmdMsg()
        cmd.cmd_type = MASCmdMsg.DELETE_CMD
        cmd.vessel_name = agent
        result = self._mas_cmd(cmd, f"delete_vessel({agent})", timeout_s)
        if not result.result:
            raise RuntimeError(f"delete_vessel({agent}): échec côté LOTUSim")
        self._node.get_logger().info(f'Deleted: {agent}')

    def set_waypoints(self, agent: str, lat: float, lon: float, timeout_s: float = 10.0) -> None:
        service_name = f'/lotusim/{agent}/waypoints'
        cli = self._node.create_client(SetWaypoints, service_name)
        if not cli.wait_for_service(timeout_sec=timeout_s):
            raise RuntimeError(f"set_waypoints: service indisponible ({service_name})")
        req = SetWaypoints.Request()
        req.path = [GeoPoint(latitude=lat, longitude=lon, altitude=0.0)]
        req.loop = False
        fut = cli.call_async(req)
        _wait(fut, timeout_s)
        response = require_result(fut, f"set_waypoints({agent})")
        if not response.success:
            raise RuntimeError(f"set_waypoints({agent}): échec côté LOTUSim")
        self._node.get_logger().info(f'[{agent}] → ({lat:.5f}, {lon:.5f})')

    def wait_ready(self, agent: str, timeout_s: float = 10.0) -> None:
        """Probe de disponibilité (Task 7) : le contrôleur v3 l'appelle après
        spawn_vessel, avant de considérer l'agent utilisable — attend que le
        service de waypoints soit prêt côté LOTUSim."""
        service_name = f'/lotusim/{agent}/waypoints'
        cli = self._node.create_client(SetWaypoints, service_name)
        if not cli.wait_for_service(timeout_sec=timeout_s):
            raise RuntimeError(f"wait_ready({agent}): service indisponible ({service_name})")

    def stop_vessel(self, agent: str, timeout_s: float = 10.0) -> None:
        service_name = f'/lotusim/{agent}/stop'
        cli = self._node.create_client(Empty, service_name)
        if not cli.wait_for_service(timeout_sec=timeout_s):
            raise RuntimeError(f"stop_vessel: service indisponible ({service_name})")
        fut = cli.call_async(Empty.Request())
        _wait(fut, timeout_s)
        require_result(fut, f"stop_vessel({agent})")
        self._node.get_logger().info(f'[{agent}] stop')

    # ── Divers ───────────────────────────────────────────────────────────

    def ok(self) -> bool:
        return bool(rclpy.ok())

    def log_info(self, msg: str) -> None:
        self._node.get_logger().info(msg)

    def log_error(self, msg: str) -> None:
        self._node.get_logger().error(msg)

    def shutdown(self) -> None:
        self._executor.shutdown()
        self._node.destroy_node()
