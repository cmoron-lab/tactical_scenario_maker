"""Adaptateur ROS vers LOTUSim — SEUL module du paquet à importer rclpy.

Possède le nœud et son executor ; expose le spawn, l'envoi de waypoints et
l'observation des poses avec réveil sur changement réel (wake-on-change).
C'est la couture où se brancheront les autonomies de l'architecture cible
(ARCHITECTURE.md §7.6).
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

from lotusim_msgs.action import MASCmd
from lotusim_msgs.msg import MASCmd as MASCmdMsg
from lotusim_msgs.msg import VesselPositionArray
from lotusim_msgs.srv import SetWaypoints

# En dessous, deux positions sont "identiques" (bruit GPS/float) : une mise à
# jour de pose ne réveille pas inutilement les agents qui la surveillent.
POSITION_EPSILON_DEG = 1e-6


def _wait(fut: Any, timeout: float = 10.0) -> None:
    done = threading.Event()
    fut.add_done_callback(lambda _: done.set())
    done.wait(timeout=timeout)


class LotusimClient:
    def __init__(self, node_name: str = 'goto_point', namespace: str = '/lotusim',
                 on_pose: Optional[Callable[[str, float, float], None]] = None) -> None:
        self._node = Node(node_name, namespace=namespace)
        self._executor = MultiThreadedExecutor()
        self._executor.add_node(self._node)
        threading.Thread(target=self._executor.spin, daemon=True).start()
        self._data: dict[str, dict[str, float]] = {}
        self._lock = threading.Lock()
        self._watchers: dict[str, list[threading.Event]] = {}
        self._on_pose = on_pose
        self._node.create_subscription(VesselPositionArray, '/lotusim/poses', self._cb, 10)

    # ── Observation des poses ────────────────────────────────────────────

    def _cb(self, msg: Any) -> None:
        poses: list[tuple[str, float, float]] = []
        cb = self._on_pose
        with self._lock:
            for v in msg.vessels:
                new = {'lat': v.geo_point.latitude, 'lon': v.geo_point.longitude}
                old = self._data.get(v.vessel_name)
                changed = (
                    old is None
                    or abs(old['lat'] - new['lat']) > POSITION_EPSILON_DEG
                    or abs(old['lon'] - new['lon']) > POSITION_EPSILON_DEG
                )
                self._data[v.vessel_name] = new
                if cb:
                    poses.append((v.vessel_name, new['lat'], new['lon']))
                if changed:
                    for ev in self._watchers.get(v.vessel_name, []):
                        ev.set()
        # Callback utilisateur hors verrou : évite le self-deadlock si le
        # callback relit get_pose/register_watch.
        if cb:
            for name, lat, lon in poses:
                cb(name, lat, lon)

    def get_pose(self, name: str) -> Optional[dict[str, float]]:
        with self._lock:
            return self._data.get(name)

    def register_watch(self, name: str, event: threading.Event) -> None:
        """Réveille `event` quand la position de `name` change réellement."""
        with self._lock:
            self._watchers.setdefault(name, []).append(event)

    # ── Commandes LOTUSim ────────────────────────────────────────────────

    def spawn_vessel(self, vessel: str, init_pos: tuple[float, float], model: str,
                     linear_velocities_limits: tuple[float, float],
                     angular_velocities_limits: float, heading: float = 0.0) -> None:
        spawn = ActionClient(self._node, MASCmd, '/lotusim/mas_cmd')
        spawn.wait_for_server()
        cmd = MASCmdMsg()
        cmd.cmd_type = MASCmdMsg.CREATE_CMD
        cmd.model_name = model
        cmd.vessel_name = vessel
        cmd.geo_point = GeoPoint(latitude=init_pos[0], longitude=init_pos[1], altitude=0.0)
        # MASCmd.heading est un champ top-level (radians, utilisé tel quel comme yaw
        # par entity_spawner.cpp) — pas un tag SDF. `heading` ici est en degrés
        # (convention scénario/UI), donc conversion.
        cmd.heading = math.radians(heading)
        cmd.sdf_string = f"""
            <lotus_param>
                <waypoint_follower>
                    <follower>
                        <loop>false</loop>
                        <range_tolerance>2</range_tolerance>
                        <linear_velocities_limits>{linear_velocities_limits[0]} {linear_velocities_limits[1]}</linear_velocities_limits>
                        <angular_velocities_limits>{angular_velocities_limits}</angular_velocities_limits>
                    </follower>
                </waypoint_follower>
            </lotus_param>
        """
        goal = MASCmd.Goal()
        goal.cmd = cmd
        fut = spawn.send_goal_async(goal)
        _wait(fut, timeout=10.0)
        if not fut.done() or fut.result() is None:
            raise RuntimeError(f"spawn_vessel: pas de réponse pour '{vessel}'")
        res_fut = fut.result().get_result_async()
        _wait(res_fut, timeout=10.0)
        if not res_fut.done() or res_fut.result() is None:
            raise RuntimeError(f"spawn_vessel: timeout résultat pour '{vessel}'")
        self._node.get_logger().info(f'Spawned: {res_fut.result().result.name}')

    def set_waypoints(self, agent: str, lat: float, lon: float) -> None:
        cli = self._node.create_client(SetWaypoints, f'/lotusim/{agent}/waypoints')
        cli.wait_for_service()
        req = SetWaypoints.Request()
        req.path = [GeoPoint(latitude=lat, longitude=lon, altitude=0.0)]
        req.loop = False
        fut = cli.call_async(req)
        _wait(fut)
        self._node.get_logger().info(f'[{agent}] → ({lat:.5f}, {lon:.5f})')

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
