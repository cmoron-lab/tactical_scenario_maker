#!/usr/bin/env python3
import csv
import os
import sys
import time
import threading
from datetime import datetime, timezone
import gtpyhop
import rclpy
from rclpy.node import Node
from rclpy.executors import MultiThreadedExecutor
from lotusim_msgs.msg import VesselPositionArray

# ── Utilitaires ───────────────────────────────────────────────────────────────

_ros_node = None
_pose_log = None
_waypoint_log = None
_waypoint_log_lock = threading.Lock()

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

# ── PoseTracker ───────────────────────────────────────────────────────────────

class PoseTracker:
    def __init__(self):
        self._data = {}
        self._lock = threading.Lock()

    def start(self, node):
        node.create_subscription(VesselPositionArray, "/lotusim/poses", self._cb, 10)

    def _cb(self, msg):
        ts = _ts()
        with self._lock:
            for v in msg.vessels:
                self._data[v.vessel_name] = {'lat': v.geo_point.latitude, 'lon': v.geo_point.longitude}
                if _pose_log:
                    _pose_log.writerow([ts, v.vessel_name, v.geo_point.latitude, v.geo_point.longitude])

    def get(self, name):
        with self._lock:
            return self._data.get(name)

tracker = PoseTracker()

def _wait(fut, timeout=10.0):
    done = threading.Event()
    fut.add_done_callback(lambda _: done.set())
    done.wait(timeout=timeout)

# ── Domaine HTN ───────────────────────────────────────────────────────────────

gtpyhop.Domain('htn_v1')

import sys as _sys; _sys.modules.setdefault('main', _sys.modules[__name__])

from bdd.primitives_actions import spawn_vessel
import bdd.tasks_methods
from bdd.utils import in_zone, DETECTION_RADIUS_DEG, agent_conditions, is_intruder_agent

_scenario_name = sys.argv[1] if len(sys.argv) > 1 else 'scenario_1'
import importlib
AGENTS = importlib.import_module(f'scenarios.{_scenario_name}').AGENTS

# ── Mise à jour du state depuis le tracker ────────────────────────────────────

def _update_state_from_tracker(state):
    # Mise à jour positions + historique
    for name in state.agents:
        pos = tracker.get(name)
        if pos:
            old = state.agents[name].get('pos')
            if old and (old['lat'] != pos['lat'] or old['lon'] != pos['lon']):
                hist = state.position_history.setdefault(name, [])
                hist.append(old)
                state.position_history[name] = hist[-5:]
            state.agents[name]['pos'] = pos

    # Calcul automatique de intruder_nearby pour chaque agent non-intruder
    threats = [n for n in state.agents if is_intruder_agent(AGENTS.get(n, {}))]
    for name in state.agents:
        if name in threats:
            continue
        agent_pos = state.agents[name].get('pos')
        nearby = any(
            agent_pos and state.agents[t].get('pos') and
            in_zone(agent_pos, state.agents[t]['pos'], DETECTION_RADIUS_DEG)
            for t in threats
        )
        state.agents[name]['intruder_nearby'] = nearby

# ── Exécution de plan ─────────────────────────────────────────────────────────

def _execute_plan(plan, state):
    for action in plan:
        cmd_fn = gtpyhop.current_domain._command_dict.get('c_' + action[0])
        if cmd_fn is None:
            cmd_fn = gtpyhop.current_domain._action_dict.get(action[0])
        if cmd_fn:
            cmd_fn(state, *action[1:])

# ── Boucle agent ──────────────────────────────────────────────────────────────

def run_agent(name, task, state, node):
    while rclpy.ok():
        _update_state_from_tracker(state)
        plan = gtpyhop.find_plan(state, [task])
        if plan is not False and plan:
            node.get_logger().info(f'[{name}] exécute plan: {[a[0] for a in plan]}')
            _execute_plan(plan, state)
            time.sleep(2.0)
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
        state.agents = {}
        for name, info in AGENTS.items():
            agent_state = {
                'pos':             {'lat': info['x'], 'lon': info['y']},
                'available':       True,
                'intruder_nearby': False,
                'last_waypoint':   None,
            }
            agent_state.update(agent_conditions(info))
            state.agents[name] = agent_state
        state.orders = {}
        state.position_history = {}

        # Calcul du plan HTN au démarrage (positions initiales connues)
        node.get_logger().info(f'[HTN] Scénario : {_scenario_name}')
        for name, info in AGENTS.items():
            plan = gtpyhop.find_plan(state, [info['mission']])
            node.get_logger().info(f'[HTN] {name}: {plan}')

        init_logs()
        tracker.start(node)

        for name, info in AGENTS.items():
            try:
                spawn_vessel(node, name, (info['x'], info['y']), info['model'],
                             info.get('linear_velocities_limits', (0, 5)),
                             info.get('angular_velocities_limits', 0.05),
                             heading=info.get('heading', 0.0))
            except Exception as e:
                node.get_logger().error(f"[spawn] échec pour '{name}' (model={info['model']!r}): {e}")
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
