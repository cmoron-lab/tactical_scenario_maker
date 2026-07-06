#!/usr/bin/env python3
"""
Minimal web UI for Tactical Scenario Maker — no external dependencies.
Run:  python3 app.py
Open: http://localhost:5000
"""
import importlib
import json
import math
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
KB_PATH = Path(__file__).parent / 'bdd' / 'knowledge_base.json'


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


def _geo_dist_deg(lat1, lon1, lat2, lon2):
    return math.sqrt((lat1 - lat2) ** 2 + (lon1 - lon2) ** 2)


def _resolve_target_names(agents, pattern):
    if not pattern:
        return []

    target = str(pattern).strip()
    norm = target.strip('_').lower()
    matched = []

    for name, adata in agents.items():
        if name == target or target.lower() in name.lower():
            matched.append(name)
            continue
        role = str(adata.get('role', '')).strip().lower()
        kind = str(adata.get('kind', '')).strip().lower()
        if role and (role == norm or norm in role):
            matched.append(name)
            continue
        if kind and (kind == norm or norm in kind):
            matched.append(name)

    if matched:
        return matched

    marked = [
        name for name, adata in agents.items()
        if adata.get('is_intruder') or adata.get('role') == 'intruder' or adata.get('kind') == 'intruder'
    ]
    if marked:
        return marked

    return []


def _apply_triggers(triggers, agents, resolve_tokens):
    """Evaluate event triggers and set agent state variables in-place."""
    for trig in triggers:
        condition = trig.get('condition', '')
        sets_var  = trig.get('sets_variable', '')
        try:
            threshold = float(trig.get('threshold', 0))
        except (TypeError, ValueError):
            continue
        if not sets_var:
            continue
        # Support both new target_pattern and legacy target_token via resolve_tokens
        pattern = trig.get('target_pattern') or resolve_tokens.get(trig.get('target_token', ''), '')
        targets = _resolve_target_names(agents, pattern)
        for aname, adata in agents.items():
            if aname in targets:
                continue
            pos = adata.get('pos')
            if not pos:
                continue
            triggered = False
            for tname in targets:
                tpos = agents[tname].get('pos')
                if not tpos:
                    continue
                dist = _geo_dist_deg(pos['lat'], pos['lon'], tpos['lat'], tpos['lon'])
                if condition == 'distance_lt' and dist < threshold:
                    triggered = True; break
                if condition == 'distance_gt' and dist > threshold:
                    triggered = True; break
            adata[sets_var] = triggered


def _agent_conditions(agent):
    """Return conditions dict — prefers new 'conditions' key, falls back to equipement."""
    if 'conditions' in agent:
        return agent['conditions']
    eq = agent.get('equipement', {})
    cond = {}
    if 'drone' in eq:
        cond['drone_available'] = bool(eq['drone'])
    if 'weather' in eq:
        cond['weather'] = eq['weather']
    return cond


def _write_scenario(name, form_agents):
    lines = ['AGENTS = {\n']
    for aname, a in form_agents.items():
        try:
            x_val = float(a.get('x', 0))
        except (TypeError, ValueError):
            x_val = 0.0
        try:
            y_val = float(a.get('y', 0))
        except (TypeError, ValueError):
            y_val = 0.0
        base_pos = a.get('base_pos')
        if isinstance(base_pos, (list, tuple)) and len(base_pos) >= 2:
            base_lat, base_lon = base_pos[0], base_pos[1]
        else:
            base_lat, base_lon = None, None
        vel_min = float(a.get('vel_min', 0))
        vel_max = float(a.get('vel_max', 5))
        ang_vel = float(a.get('ang_vel', 0.05))
        mission = _str_to_mission(a.get('mission', ''))
        cond    = a.get('conditions', {})
        lines.append(f'    {repr(aname)}: {{\n')
        lines.append(f"        'x': {x_val},\n")
        lines.append(f"        'y': {y_val},\n")
        lines.append(f"        'model': {repr(a.get('model', 'wamv'))},\n")
        if base_lat is not None and base_lon is not None:
            lines.append(f"        'base_pos': ({base_lat}, {base_lon}),\n")
        lines.append(f"        'linear_velocities_limits': ({vel_min}, {vel_max}),\n")
        lines.append(f"        'angular_velocities_limits': {ang_vel},\n")
        lines.append(f"        'conditions': {repr(cond)},\n")
        lines.append(f"        'mission': {repr(mission)},\n")
        lines.append('    },\n')
    lines.append('}\n')
    with open(os.path.join(SCENARIOS_DIR, f'{name}.py'), 'w') as f:
        f.writelines(lines)


def _compute_plan(name):
    agents = _load_agents(name)
    if agents is None:
        return {'error': 'Scénario introuvable'}

    with open(KB_PATH, encoding='utf-8') as f:
        kb = json.load(f)
    triggers       = kb.get('event_triggers', [])
    resolve_tokens = kb.get('resolve_tokens', {})

    state = gtpyhop.State('ui_plan_state')
    state.agents = {}
    for aname, agent in agents.items():
        cond = _agent_conditions(agent)
        agent_state = {
            'pos':           {'lat': agent['x'], 'lon': agent['y']},
            'available':     True,
            'last_waypoint': None,
        }
        for k, v in cond.items():
            if isinstance(v, str) and v.lower() in ('true', 'false'):
                agent_state[k] = v.lower() == 'true'
            else:
                agent_state[k] = v
        state.agents[aname] = agent_state

    _apply_triggers(triggers, state.agents, resolve_tokens)

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
        if parts == ['api', 'kb']:
            return 'get_kb', {}
        if len(parts) == 3 and parts[0] == 'api' and parts[1] == 'scenario' and parts[3:] == []:
            return 'get_scenario', {'name': parts[2]}
        if len(parts) == 4 and parts[:2] == ['api', 'scenario'] and parts[3] == 'plan':
            return 'get_plan', {'name': parts[2]}

    if method == 'POST':
        if parts == ['api', 'kb']:
            return 'save_kb', {}
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

        elif action == 'get_kb':
            with open(KB_PATH, encoding='utf-8') as f:
                self._send_json(json.load(f))

        elif action == 'save_kb':
            kb = self._read_json()
            with open(KB_PATH, 'w', encoding='utf-8') as f:
                json.dump(kb, f, indent=2, ensure_ascii=False)
            # Reload methods in the running domain
            bdd.tasks_methods.load_kb()
            self._send_json({'ok': True})

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
                    'ang_vel':      agent.get('angular_velocities_limits', 0.05),
                    'conditions':   _agent_conditions(agent),
                    'mission':      _mission_to_str(agent['mission']),
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
