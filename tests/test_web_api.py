import json
import threading
from http.client import HTTPConnection

from tsm.web.server import make_server


def _get(conn, path):
    conn.request('GET', path)
    r = conn.getresponse()
    return r.status, json.loads(r.read())


def test_api_end_to_end_sans_ros():
    srv = make_server(port=0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    conn = HTTPConnection('127.0.0.1', port)
    try:
        status, names = _get(conn, '/api/scenarios')
        assert status == 200 and 'demo_veille_drone_intru' in names

        status, doc = _get(conn, '/api/scenario/demo_veille_drone_intru')
        assert status == 200 and doc['version'] == 1 and 'veilleur' in doc['agents']

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
