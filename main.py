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

# If no watched position has changed after this long, re-check anyway — a safety
# net in case a watch was missed (e.g. token resolution changed), not the normal
# pacing mechanism (that's the wake-on-change event below).
REPLAN_SAFETY_TIMEOUT = 5.0

# Below this, two positions are considered "the same" (GPS/float noise), so a
# pose update doesn't spuriously wake every agent watching that vessel.
POSITION_EPSILON_DEG = 1e-6

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
#
# Event-driven replanning: an agent's thread doesn't poll on a fixed interval —
# it blocks until the position of a vessel it actually cares about (itself, or
# one of the "watched" agents its mission depends on) genuinely changes, per
# collect_watched_tokens()/resolve_watched_agents() (bdd/tasks_methods.py).

class PoseTracker:
    def __init__(self):
        self._data = {}
        self._lock = threading.Lock()
        self._watchers = {}  # vessel_name -> list[threading.Event]

    def start(self, node):
        node.create_subscription(VesselPositionArray, "/lotusim/poses", self._cb, 10)

    def _cb(self, msg):
        ts = _ts()
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
                if _pose_log:
                    _pose_log.writerow([ts, v.vessel_name, new['lat'], new['lon']])
                if changed:
                    for ev in self._watchers.get(v.vessel_name, []):
                        ev.set()

    def get(self, name):
        with self._lock:
            return self._data.get(name)

    def register_watch(self, name, event):
        """Wake `event` whenever `name`'s position genuinely changes."""
        with self._lock:
            self._watchers.setdefault(name, []).append(event)

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
from bdd.utils import agent_conditions

_scenario_name = sys.argv[1] if len(sys.argv) > 1 else 'scenario_1'
import importlib
AGENTS = importlib.import_module(f'scenarios.{_scenario_name}').AGENTS

# ── Mise à jour du state depuis le tracker ────────────────────────────────────

def _update_state_from_tracker(state):
    # Positions + historique — les préconditions "distance_below"/"distance_above"
    # (bdd/tasks_methods.py) calculent la proximité directement à partir de ces
    # positions à chaque find_plan, donc aucun calcul intermédiaire n'est nécessaire ici.
    for name in state.agents:
        pos = tracker.get(name)
        if pos:
            old = state.agents[name].get('pos')
            if old and (old['lat'] != pos['lat'] or old['lon'] != pos['lon']):
                hist = state.position_history.setdefault(name, [])
                hist.append(old)
                state.position_history[name] = hist[-5:]
            state.agents[name]['pos'] = pos

# ── Exécution de plan ─────────────────────────────────────────────────────────

def _execute_plan(plan, state):
    for action in plan:
        cmd_fn = gtpyhop.current_domain._command_dict.get('c_' + action[0])
        if cmd_fn is None:
            cmd_fn = gtpyhop.current_domain._action_dict.get(action[0])
        if cmd_fn:
            cmd_fn(state, *action[1:])

# ── Cibles à surveiller par agent ─────────────────────────────────────────────

def _watched_names_for(name, info, kb, state):
    """
    Which OTHER agents' positions this agent's mission could depend on — walks
    every method reachable from its mission task (not just whichever currently
    applies, since that can change), resolved against the initial state.
    Best-effort: if the resolved target changes identity later (e.g. a
    different agent becomes "the intruder"), this won't pick that up — the
    REPLAN_SAFETY_TIMEOUT re-check covers that edge case.
    """
    mission_task = info['mission'][0] if info.get('mission') else None
    if not mission_task:
        return set()
    tokens = bdd.tasks_methods.collect_watched_tokens(kb, mission_task)
    return bdd.tasks_methods.resolve_watched_agents(state, name, tokens)

# ── Boucle agent (événementielle) ─────────────────────────────────────────────

def run_agent(name, task, state, node, watched_names):
    wake = threading.Event()
    for watched in watched_names | {name}:
        tracker.register_watch(watched, wake)

    if node:
        node.get_logger().info(f"[{name}] surveille : {sorted(watched_names | {name})}")

    while rclpy.ok():
        _update_state_from_tracker(state)
        plan = gtpyhop.find_plan(state, [task])
        if plan is not False and plan:
            node.get_logger().info(f'[{name}] exécute plan: {[a[0] for a in plan]}')
            _execute_plan(plan, state)
        # Block until a watched position actually changes, instead of polling on
        # a fixed interval — REPLAN_SAFETY_TIMEOUT is just a defensive fallback.
        wake.wait(timeout=REPLAN_SAFETY_TIMEOUT)
        wake.clear()

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
        state.position_history = {}

        kb = bdd.tasks_methods.load_kb()

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
                args=(name, info['mission'], state, node, _watched_names_for(name, info, kb, state)),
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
