"""Serveur HTTP local (stdlib) : routing + sérialisation, la logique vit dans Api."""
from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from tsm.domain.scenario import ScenarioError
from tsm.web.api import Api
from tsm.web.runs import RunBusyError

TEMPLATE_PATH = Path(__file__).resolve().parents[2] / 'templates' / 'index.html'


def _route(method: str, path: str):
    """Retourne (action, params) ou (None, {})."""
    parts = path.strip('/').split('/')
    if method == 'GET':
        if parts == ['']:
            return 'html', {}
        if parts == ['api', 'scenarios']:
            return 'list_scenarios', {}
        if parts == ['api', 'kb']:
            return 'get_kb', {}
        if parts == ['api', 'run']:
            return 'run_status', {}
        if parts == ['api', 'run', 'events']:
            return 'run_events', {}
        if parts == ['api', 'run', 'poses']:
            return 'run_poses', {}
        if len(parts) == 3 and parts[:2] == ['api', 'scenario']:
            return 'get_scenario', {'name': parts[2]}
        if len(parts) == 4 and parts[:2] == ['api', 'scenario'] and parts[3] == 'plan':
            return 'get_plan', {'name': parts[2]}
    if method == 'POST':
        if parts == ['api', 'kb']:
            return 'save_kb', {}
        if parts == ['api', 'run', 'stop']:
            return 'run_stop', {}
        if len(parts) == 3 and parts[:2] == ['api', 'scenario']:
            return 'save_scenario', {'name': parts[2]}
        if len(parts) == 4 and parts[:2] == ['api', 'scenario'] and parts[3] == 'launch':
            return 'launch_scenario', {'name': parts[2]}
        if parts == ['api', 'generate-scenario']:
            return 'generate_scenario', {}
    if method == 'DELETE':
        if len(parts) == 3 and parts[:2] == ['api', 'scenario']:
            return 'delete_scenario', {'name': parts[2]}
    return None, {}


class _Handler(BaseHTTPRequestHandler):
    api: Api  # posé par make_server

    def log_message(self, fmt, *args):
        pass

    def _send_json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _send_html(self):
        content = TEMPLATE_PATH.read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(content)))
        self.end_headers()
        try:
            self.wfile.write(content)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _read_json(self):
        length = int(self.headers.get('Content-Length', 0))
        return json.loads(self.rfile.read(length))

    def _dispatch(self, method):
        action, params = _route(method, urlparse(self.path).path)
        try:
            if action == 'html':
                self._send_html()
            elif action == 'list_scenarios':
                self._send_json(self.api.scenarios())
            elif action == 'get_kb':
                self._send_json(self.api.get_kb())
            elif action == 'save_kb':
                self._send_json(self.api.save_kb(self._read_json()))
            elif action == 'get_scenario':
                self._send_json(self.api.get_scenario(params['name']))
            elif action == 'get_plan':
                self._send_json(self.api.plan(params['name']))
            elif action == 'save_scenario':
                self._send_json(self.api.save_scenario(params['name'], self._read_json()))
            elif action == 'delete_scenario':
                self._send_json(self.api.delete_scenario(params['name']))
            elif action == 'launch_scenario':
                self._send_json(self.api.launch(params['name']))
            elif action == 'run_status':
                self._send_json(self.api.run_status())
            elif action == 'run_events':
                query = parse_qs(urlparse(self.path).query)
                try:
                    since = int(query.get('since', ['0'])[0])
                except ValueError:
                    since = 0
                self._send_json(self.api.run_events(since))
            elif action == 'run_poses':
                self._send_json(self.api.run_poses())
            elif action == 'run_stop':
                self._send_json(self.api.run_stop())
            elif action == 'generate_scenario':
                self._send_json({'error': 'générateur IA parqué — voir attic/'}, 501)
            else:
                self._send_json({'error': 'not found'}, 404)
        except ScenarioError as e:
            if method == 'POST':
                self._send_json({'error': str(e)}, 400)
            else:
                self._send_json({'error': 'not found'}, 404)
        except RunBusyError:
            self._send_json({'error': 'run déjà en cours',
                              'scenario': self.api.run_status()['scenario']}, 409)

    def do_GET(self):
        self._dispatch('GET')

    def do_POST(self):
        self._dispatch('POST')

    def do_DELETE(self):
        self._dispatch('DELETE')


class _Server(HTTPServer):
    allow_reuse_address = True


def make_server(port: int = 8080, api: Api | None = None) -> HTTPServer:
    handler = type('Handler', (_Handler,), {'api': api or Api()})
    return _Server(('', port), handler)


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    try:
        server = make_server(port)
    except OSError:
        print(f'Port {port} déjà utilisé. Essayez : python3 app.py 8081')
        sys.exit(1)
    print(f'Tactical Scenario Maker → http://localhost:{port}')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nArrêt.')
