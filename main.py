#!/usr/bin/env python3
"""
HTN - agents autonomes avec surveillance réactive et interception.
"""
import csv
import math
import os
import time
import threading
from datetime import datetime, timezone
import gtpyhop
import rclpy
from rclpy.node import Node
from rclpy.executors import MultiThreadedExecutor
from lotusim_msgs.msg import VesselPositionArray

# ── Config ────────────────────────────────────────────────────────────────────

_ros_node = None
_pose_log = None
_waypoint_log = None
_waypoint_log_lock = threading.Lock()

DETECTION_RADIUS_DEG = 0.003
MIN_MOVE_DEG = 0.0003  # ~30m : seuil avant de renvoyer un waypoint à suivre

# ── Fonctions utilitaires ─────────────────────────────────────────────────────

def _ts():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')

def init_logs():
    global _pose_log, _waypoint_log
    os.makedirs('logs', exist_ok=True)
    pf = open('logs/poses.csv', 'w', newline='')
    wf = open('logs/waypoints.csv', 'w', newline='')
    _pose_log = csv.writer(pf)
    _waypoint_log = (csv.writer(wf), wf)
    _pose_log.writerow(['timestamp', 'agent', 'lat', 'lon'])
    _waypoint_log[0].writerow(['timestamp', 'agent', 'lat', 'lon'])

def in_zone(center, pos, radius):
    return math.hypot(center['lat'] - pos['lat'], center['lon'] - pos['lon']) < radius

# ── PoseTracker ───────────────────────────────────────────────────────────────

class PoseTracker:
    """Source de vérité pour les positions, mise à jour par ROS."""

    def __init__(self):
        self._data = {}
        self._lock = threading.Lock()

    def start(self, node):
        node.create_subscription(VesselPositionArray, "/lotusim/poses", self._cb, 10)

    def _cb(self, msg):
        ts = _ts()
        with self._lock:
            for v in msg.vessels:
                self._data[v.vessel_name] = {
                    'lat': v.geo_point.latitude,
                    'lon': v.geo_point.longitude,
                }
                if _pose_log:
                    _pose_log.writerow([ts, v.vessel_name, v.geo_point.latitude, v.geo_point.longitude])

    def get(self, name):
        with self._lock:
            return self._data.get(name)

tracker = PoseTracker()

# ── Utilitaire futures ────────────────────────────────────────────────────────

def _wait(fut, timeout=10.0):
    done = threading.Event()
    fut.add_done_callback(lambda _: done.set())
    done.wait(timeout=timeout)

# ── HTN domain ────────────────────────────────────────────────────────────────

gtpyhop.Domain('htn_v1')

_last_sent = {}  # agent -> (lat, lon) du dernier waypoint envoyé

# garantit que "import main" depuis bdd/ retrouve CE module même quand lancé comme __main__
import sys as _sys; _sys.modules.setdefault('main', _sys.modules[__name__])

# imports après définition des globals pour éviter les imports circulaires
from bdd.events import EventChecker             
from bdd.primitives_actions import spawn_vessel 
import bdd.tasks_methods                        
from scenarios.scenario_1 import AGENTS         

# ── Boucle agent ──────────────────────────────────────────────────────────────

def run_agent(name, mission, state, node):
    current = mission
    while rclpy.ok() and current is not None:
        for event_name, next_mission in current.get('on_interrupt', {}).items():
            fn = getattr(EventChecker, event_name, None)
            if fn and fn():
                node.get_logger().info(f"[{name}] '{event_name}' → {next_mission['task']}")
                current = next_mission
                break
        else:
            plan = gtpyhop.find_plan(state, [current['task']])
            if plan:
                if current.get('loop_interval'):
                    time.sleep(current['loop_interval'])
                else:
                    current = current.get('on_complete')
            else:
                time.sleep(1.0)

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    global _ros_node
    rclpy.init()
    node = Node("goto_point", namespace="/lotusim")
    _ros_node = node

    executor = MultiThreadedExecutor()
    executor.add_node(node)
    threading.Thread(target=executor.spin, daemon=True).start()

    try:
        gtpyhop.verbose = 0
        state = gtpyhop.State('initial_state')
        state.agents = {
            name: {'x': info['x'], 'y': info['y'], 'model': info['model']}
            for name, info in AGENTS.items()
        }

        init_logs()
        tracker.start(node)

        for name, info in AGENTS.items():
            spawn_vessel(node, name, (info['x'], info['y']), info['model'],
            info.get('linear_velocities_limits', (0, 5)),
            info.get('angular_velocities_limits', 0.05))
            time.sleep(3.0)

        threads = [
            threading.Thread(
                target=run_agent,
                args=(name, info['mission'], state, node),
                daemon=True,
            )
            for name, info in AGENTS.items()
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    except KeyboardInterrupt:
        pass
    finally:
        if _waypoint_log:
            _waypoint_log[1].close()
        executor.shutdown()
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()
