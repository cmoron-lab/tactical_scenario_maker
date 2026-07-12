import json
import sys
import threading
from http.client import HTTPConnection

from tsm.web.api import Api
from tsm.web.runs import RunManager
from tsm.web.server import make_server


def _get(conn, path):
    conn.request('GET', path)
    r = conn.getresponse()
    return r.status, json.loads(r.read())


def _post(conn, path, body=None):
    conn.request('POST', path, body=json.dumps(body) if body is not None else None)
    r = conn.getresponse()
    return r.status, json.loads(r.read())


def test_api_end_to_end_sans_ros(tmp_path):
    # RunManager isolé : le défaut lit REPO_ROOT/logs, pollué par les vrais runs.
    srv = make_server(port=0, api=Api(run_manager=RunManager(logs_dir=tmp_path)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    conn = HTTPConnection('127.0.0.1', port)
    try:
        status, names = _get(conn, '/api/scenarios')
        assert status == 200 and 'demo_veille_drone_intru' in names

        status, doc = _get(conn, '/api/scenario/demo_veille_drone_intru')
        assert status == 200 and doc['version'] == 1 and 'veilleur' in doc['agents']

        status, run = _get(conn, '/api/run')
        assert status == 200 and run['state'] == 'idle'

        status, resp = _post(conn, '/api/run/stop')
        assert status == 200 and resp == {'ok': False}

        status, events = _get(conn, '/api/run/events?since=0')
        assert status == 200 and events == {'events': [], 'next': 0}

        status, plans = _get(conn, '/api/scenario/demo_veille_drone_intru/plan')
        assert status == 200 and set(plans) == set(doc['agents'])

        status, _ = _get(conn, '/api/scenario/inconnu')
        assert status == 404

        conn.request('POST', '/api/scenario/demo_veille_drone_intru',
                     body=json.dumps({'version': 99}),
                     headers={'Content-Type': 'application/json'})
        assert conn.getresponse().status == 400  # ScenarioError → message explicite

        conn.request('POST', '/api/generate-scenario', body=json.dumps({'description': 'x'}),
                     headers={'Content-Type': 'application/json'})
        r = conn.getresponse()
        assert r.status == 501 and 'parqué' in json.loads(r.read())['error']
    finally:
        srv.shutdown()


def test_launch_twice_returns_409(tmp_path):
    cmd = lambda name, profile=None: [sys.executable, '-c', 'import time; time.sleep(2)']  # noqa: E731
    rm = RunManager(cmd=cmd, logs_dir=tmp_path)
    srv = make_server(port=0, api=Api(run_manager=rm))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    conn = HTTPConnection('127.0.0.1', port)
    try:
        status, resp = _post(conn, '/api/scenario/demo_veille_drone_intru/launch')
        assert status == 200 and resp['ok'] is True

        status, resp = _post(conn, '/api/scenario/demo_veille_drone_intru/launch')
        assert status == 409
        assert resp == {'error': 'run déjà en cours', 'scenario': 'demo_veille_drone_intru'}

        status, resp = _post(conn, '/api/run/stop')
        assert status == 200 and resp == {'ok': True}
    finally:
        srv.shutdown()


# ── Task 7 : scénarios v2, profils, artefacts de run ─────────────────────────

def test_get_scenario_v2_returns_version_2_document(tmp_path):
    srv = make_server(port=0, api=Api(run_manager=RunManager(logs_dir=tmp_path)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    conn = HTTPConnection('127.0.0.1', port)
    try:
        status, doc = _get(conn, '/api/scenario/escorte_ormuz')
        assert status == 200 and doc['version'] == 2 and 'cargo_1' in doc['agents']
    finally:
        srv.shutdown()


def test_list_profiles_returns_available_profile_names(tmp_path):
    srv = make_server(port=0, api=Api(run_manager=RunManager(logs_dir=tmp_path)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    conn = HTTPConnection('127.0.0.1', port)
    try:
        status, names = _get(conn, '/api/profiles')
        assert status == 200 and 'kinematic-ormuz' in names
    finally:
        srv.shutdown()


def test_launch_v2_scenario_without_profile_is_400(tmp_path):
    srv = make_server(port=0, api=Api(run_manager=RunManager(logs_dir=tmp_path)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    conn = HTTPConnection('127.0.0.1', port)
    try:
        status, resp = _post(conn, '/api/scenario/escorte_ormuz/launch')
        assert status == 400
        assert 'profil' in resp['error']
    finally:
        srv.shutdown()


def test_launch_v1_scenario_with_profile_is_400(tmp_path):
    srv = make_server(port=0, api=Api(run_manager=RunManager(logs_dir=tmp_path)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    conn = HTTPConnection('127.0.0.1', port)
    try:
        status, resp = _post(conn, '/api/scenario/demo_veille_drone_intru/launch',
                             {'profile': 'kinematic-ormuz'})
        assert status == 400
        assert 'profil' in resp['error']
    finally:
        srv.shutdown()


def test_launch_v2_scenario_with_profile_spawns_with_profile_flag(tmp_path):
    seen = {}

    def cmd(name, profile=None):
        seen['name'], seen['profile'] = name, profile
        return [sys.executable, '-c', 'import time; time.sleep(2)']

    rm = RunManager(cmd=cmd, logs_dir=tmp_path)
    srv = make_server(port=0, api=Api(run_manager=rm))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    conn = HTTPConnection('127.0.0.1', port)
    try:
        status, resp = _post(conn, '/api/scenario/escorte_ormuz/launch',
                             {'profile': 'kinematic-ormuz'})
        assert status == 200 and resp['ok'] is True
        assert seen == {'name': 'escorte_ormuz', 'profile': 'kinematic-ormuz'}

        status, run = _get(conn, '/api/run')
        assert status == 200 and run['profile'] == 'kinematic-ormuz'
    finally:
        rm.stop()
        srv.shutdown()


def test_run_artifact_404_when_missing_then_200_once_present(tmp_path):
    srv = make_server(port=0, api=Api(run_manager=RunManager(logs_dir=tmp_path)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    conn = HTTPConnection('127.0.0.1', port)
    try:
        status, _ = _get(conn, '/api/run/r-000001/report')
        assert status == 404

        run_dir = tmp_path / 'r-000001'
        run_dir.mkdir()
        (run_dir / 'manifest.json').write_text(json.dumps({'run_id': 'r-000001'}))
        status, doc = _get(conn, '/api/run/r-000001/manifest')
        assert status == 200 and doc == {'run_id': 'r-000001'}

        # run_id qui ne respecte pas le format r-%06d (protection traversée de
        # chemin) : jamais lu, toujours 404 — même s'il pointerait ailleurs.
        status, _ = _get(conn, '/api/run/../report')
        assert status == 404
    finally:
        srv.shutdown()
