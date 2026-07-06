#!/usr/bin/env python3
"""
Minimal web UI for Tactical Scenario Maker — no external dependencies.
Run:  python3 app.py
Open: http://localhost:5000
"""
import importlib
import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse

# ── GTpyhop domain (set up before method files are imported) ──────────────────
import gtpyhop
gtpyhop.Domain('ui_plan')
import bdd.tasks_methods        # noqa: E402
import bdd.primitives_actions   # noqa: E402

SCENARIOS_DIR = 'scenarios'
TEMPLATE_PATH = Path(__file__).parent / 'templates' / 'index.html'


# ── Helpers ────────────────────────────────────────────────────────────────────

def _list_scenarios():
    return sorted(
        f[:-3] for f in os.listdir(SCENARIOS_DIR)
        if f.endswith('.py') and not f.startswith('_')
    )


def _load_agents(name):
    full = f'scenarios.{name}'
    sys.modules.pop(full, None)
    try:
        return importlib.import_module(full).AGENTS
    except Exception:
        return None


def _mission_to_str(mission):
    parts = []
    for x in mission:
        if isinstance(x, (tuple, list)):
            parts.extend(str(v) for v in x)
        else:
            parts.append(str(x))
    return ' '.join(parts)


def _str_to_mission(s):
    tokens = s.strip().split()
    result = []
    i = 0
    while i < len(tokens):
        try:
            v1 = float(tokens[i])
            if i + 1 < len(tokens):
                try:
                    v2 = float(tokens[i + 1])
                    result.append((v1, v2))
                    i += 2
                    continue
                except ValueError:
                    pass
            result.append(v1)
        except ValueError:
            if tokens[i].lower() == 'true':
                result.append(True)
            elif tokens[i].lower() == 'false':
                result.append(False)
            else:
                result.append(tokens[i])
        i += 1
    return tuple(result)


def _write_scenario(name, form_agents):
    lines = ['AGENTS = {\n']
    for aname, a in form_agents.items():
        vel_min = float(a.get('vel_min', 0))
        vel_max = float(a.get('vel_max', 5))
        ang_vel = float(a.get('ang_vel', 0.05))
        mission = _str_to_mission(a.get('mission', ''))
        equip   = a.get('equipement', {})
        lines.append(f'    {repr(aname)}: {{\n')
        lines.append(f"        'x': {float(a['x'])},\n")
        lines.append(f"        'y': {float(a['y'])},\n")
        lines.append(f"        'model': {repr(a.get('model', 'wamv'))},\n")
        lines.append(f"        'linear_velocities_limits': ({vel_min}, {vel_max}),\n")
        lines.append(f"        'angular_velocities_limits': {ang_vel},\n")
        lines.append(f"        'equipement': {repr(equip)},\n")
        lines.append(f"        'mission': {repr(mission)},\n")
        lines.append('    },\n')
    lines.append('}\n')
    with open(os.path.join(SCENARIOS_DIR, f'{name}.py'), 'w') as f:
        f.writelines(lines)


def _compute_plan(name):
    agents = _load_agents(name)
    if agents is None:
        return {'error': 'Scénario introuvable'}

    state = gtpyhop.State('ui_plan_state')
    state.agents = {
        aname: {
            'pos':             {'lat': agent['x'], 'lon': agent['y']},
            'drone_available': bool(agent.get('equipement', {}).get('drone', False)),
            'weather':         agent.get('equipement', {}).get('weather'),
            'available':       True,
            'intruder_nearby': True,
            'last_waypoint':   None,
        }
        for aname, agent in agents.items()
    }
    state.orders = {}
    state.position_history = {}

    gtpyhop.verbose = 0
    results = {}
    for aname, agent in agents.items():
        try:
            plan = gtpyhop.find_plan(state, [agent['mission']])
            if plan is False:
                results[aname] = 'Aucun plan applicable (standby / attente)'
            elif not plan:
                results[aname] = '[] — inactif (drone géré par agent dédié)'
            else:
                results[aname] = str(plan)
        except Exception as e:
            results[aname] = f'Erreur: {e}'
    return results


# ── HTTP Handler ───────────────────────────────────────────────────────────────

def _route(method, path):
    """Decorator-less router: returns (handler_fn, path_params) or (None, None)."""
    parts = path.strip('/').split('/')

    if method == 'GET':
        if parts == ['']:
            return 'html', {}
        if parts == ['api', 'scenarios']:
            return 'list_scenarios', {}
        if len(parts) == 3 and parts[0] == 'api' and parts[1] == 'scenario' and parts[3:] == []:
            return 'get_scenario', {'name': parts[2]}
        if len(parts) == 4 and parts[:2] == ['api', 'scenario'] and parts[3] == 'plan':
            return 'get_plan', {'name': parts[2]}

    if method == 'POST':
        if len(parts) == 3 and parts[0] == 'api' and parts[1] == 'scenario' and parts[3:] == []:
            return 'save_scenario', {'name': parts[2]}
        if len(parts) == 4 and parts[:2] == ['api', 'scenario'] and parts[3] == 'launch':
            return 'launch_scenario', {'name': parts[2]}

    if method == 'DELETE':
        if len(parts) == 3 and parts[0] == 'api' and parts[1] == 'scenario':
            return 'delete_scenario', {'name': parts[2]}

    return None, {}


class Handler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        pass  # Silence default HTTP log noise

    def _send_json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', len(body))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, path):
        content = path.read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', len(content))
        self.end_headers()
        self.wfile.write(content)

    def _read_json(self):
        length = int(self.headers.get('Content-Length', 0))
        return json.loads(self.rfile.read(length))

    def _dispatch(self, method):
        parsed = urlparse(self.path)
        action, params = _route(method, parsed.path)

        if action == 'html':
            self._send_html(TEMPLATE_PATH)

        elif action == 'list_scenarios':
            self._send_json(_list_scenarios())

        elif action == 'get_scenario':
            agents = _load_agents(params['name'])
            if agents is None:
                self._send_json({'error': 'not found'}, 404)
                return
            result = {}
            for aname, agent in agents.items():
                lim = agent.get('linear_velocities_limits', (0, 5))
                result[aname] = {
                    'x':          agent['x'],
                    'y':          agent['y'],
                    'model':      agent.get('model', 'wamv'),
                    'vel_min':    lim[0],
                    'vel_max':    lim[1],
                    'ang_vel':    agent.get('angular_velocities_limits', 0.05),
                    'equipement': agent.get('equipement', {}),
                    'mission':    _mission_to_str(agent['mission']),
                }
            self._send_json(result)

        elif action == 'get_plan':
            self._send_json(_compute_plan(params['name']))

        elif action == 'save_scenario':
            form_agents = self._read_json()
            _write_scenario(params['name'], form_agents)
            self._send_json({'ok': True})

        elif action == 'delete_scenario':
            path = os.path.join(SCENARIOS_DIR, f"{params['name']}.py")
            if os.path.exists(path):
                os.remove(path)
            self._send_json({'ok': True})

        elif action == 'launch_scenario':
            proc = subprocess.Popen(
                [sys.executable, 'main.py', params['name']],
                cwd=os.path.dirname(os.path.abspath(__file__)),
            )
            self._send_json({'ok': True, 'pid': proc.pid})

        else:
            self._send_json({'error': 'not found'}, 404)

    def do_GET(self):
        self._dispatch('GET')

    def do_POST(self):
        self._dispatch('POST')

    def do_DELETE(self):
        self._dispatch('DELETE')


# ── Entry point ────────────────────────────────────────────────────────────────

class _Server(HTTPServer):
    allow_reuse_address = True


if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    try:
        server = _Server(('', port), Handler)
    except OSError:
        print(f'Port {port} déjà utilisé. Essayez : python3 app.py 8081')
        sys.exit(1)
    print(f'Tactical Scenario Maker → http://localhost:{port}')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nArrêt.')
