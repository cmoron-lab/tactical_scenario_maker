import json
import sys
import threading
from functools import partial
from http.client import HTTPConnection
from pathlib import Path

import pytest

import tsm.domain.scenario as scenario_mod
import tsm.web.api as api_mod
from tsm.domain.reference import ReferenceScenario
from tsm.domain.scenario import ScenarioError
from tsm.web.api import Api
from tsm.web.runs import RunManager
from tsm.web.server import make_server

# Scénario v1 minimal (attic/scenarios-v1/demo_veille_drone_intru.json n'est plus
# shippé dans scenarios/ depuis l'harmonisation v2) : les tests qui exercent le
# chemin v1 générique (get/plan/launch) le recréent en tmp_path plutôt que de
# dépendre d'un fichier parqué.
V1_MINIMAL = {
    "version": 1,
    "agents": {"veilleur": {
        "position": {"lat": 1.26, "lon": 103.75}, "heading_deg": 0.0,
        "model": "wamv", "velocity": {"linear": [0.0, 5.0], "angular_max": 0.05},
        "conditions": {"role": "patrol", "base_location": "1.26 103.75"},
        "mission": {"task": "veiller", "args": ["veilleur"]}}},
}


def _write_v1_scenario(monkeypatch, tmp_path, name='v1_fixture'):
    """Isole les fonctions v1 (défauts `directory` figés à l'import, cf. task-4-report)
    sur tmp_path — monkeypatcher `scenario_mod.SCENARIOS_DIR` seul n'a aucun effet sur
    les appels non qualifiés déjà faits par Api — puis y écrit un scénario minimal."""
    for fname in ('list_scenarios', 'load_scenario', 'save_scenario',
                  'delete_scenario', 'peek_version'):
        monkeypatch.setattr(api_mod, fname, partial(getattr(scenario_mod, fname),
                                                     directory=tmp_path))
    (tmp_path / f'{name}.json').write_text(json.dumps(V1_MINIMAL), encoding='utf-8')
    return name


def _get(conn, path):
    conn.request('GET', path)
    r = conn.getresponse()
    return r.status, json.loads(r.read())


def _post(conn, path, body=None):
    conn.request('POST', path, body=json.dumps(body) if body is not None else None)
    r = conn.getresponse()
    return r.status, json.loads(r.read())


def test_api_end_to_end_sans_ros(tmp_path, monkeypatch):
    # RunManager isolé : le défaut lit REPO_ROOT/logs, pollué par les vrais runs.
    name = _write_v1_scenario(monkeypatch, tmp_path)
    srv = make_server(port=0, api=Api(run_manager=RunManager(logs_dir=tmp_path)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    conn = HTTPConnection('127.0.0.1', port)
    try:
        status, names = _get(conn, '/api/scenarios')
        assert status == 200 and name in names

        status, doc = _get(conn, f'/api/scenario/{name}')
        assert status == 200 and doc['version'] == 1 and 'veilleur' in doc['agents']

        status, run = _get(conn, '/api/run')
        assert status == 200 and run['state'] == 'idle'

        status, resp = _post(conn, '/api/run/stop')
        assert status == 200 and resp == {'ok': False}

        status, events = _get(conn, '/api/run/events?since=0')
        assert status == 200 and events == {'events': [], 'next': 0}

        status, plans = _get(conn, f'/api/scenario/{name}/plan')
        assert status == 200 and set(plans) == set(doc['agents'])

        status, _ = _get(conn, '/api/scenario/inconnu')
        assert status == 404

        conn.request('POST', f'/api/scenario/{name}',
                     body=json.dumps({'version': 99}),
                     headers={'Content-Type': 'application/json'})
        assert conn.getresponse().status == 400  # ScenarioError → message explicite

        conn.request('POST', '/api/generate-scenario', body=json.dumps({'description': 'x'}),
                     headers={'Content-Type': 'application/json'})
        r = conn.getresponse()
        assert r.status == 501 and 'parqué' in json.loads(r.read())['error']
    finally:
        srv.shutdown()


def test_launch_twice_returns_409(tmp_path, monkeypatch):
    name = _write_v1_scenario(monkeypatch, tmp_path)
    cmd = lambda name, profile=None: [sys.executable, '-c', 'import time; time.sleep(2)']  # noqa: E731
    rm = RunManager(cmd=cmd, logs_dir=tmp_path)
    srv = make_server(port=0, api=Api(run_manager=rm))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    conn = HTTPConnection('127.0.0.1', port)
    try:
        status, resp = _post(conn, f'/api/scenario/{name}/launch')
        assert status == 200 and resp['ok'] is True

        status, resp = _post(conn, f'/api/scenario/{name}/launch')
        assert status == 409
        assert resp == {'error': 'run déjà en cours', 'scenario': name}

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


def test_launch_v1_scenario_with_profile_is_400(tmp_path, monkeypatch):
    name = _write_v1_scenario(monkeypatch, tmp_path)
    srv = make_server(port=0, api=Api(run_manager=RunManager(logs_dir=tmp_path)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    conn = HTTPConnection('127.0.0.1', port)
    try:
        status, resp = _post(conn, f'/api/scenario/{name}/launch',
                             {'profile': 'kinematic-ormuz'})
        assert status == 400
        assert 'profil' in resp['error']
    finally:
        srv.shutdown()


def test_launch_v2_scenario_with_unknown_profile_is_400(tmp_path):
    # refus AVANT spawn : sinon le sous-processus mourrait avant
    # create_run_directory et le run resterait sans run_id ni verdict.
    srv = make_server(port=0, api=Api(run_manager=RunManager(logs_dir=tmp_path)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    conn = HTTPConnection('127.0.0.1', port)
    try:
        status, resp = _post(conn, '/api/scenario/escorte_ormuz/launch',
                             {'profile': 'inexistant'})
        assert status == 400
        assert 'profil inconnu' in resp['error']
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


# ── Task 1 : sauvegarde v2 côté serveur ───────────────────────────────────────

def test_save_scenario_v2_validates_then_writes(tmp_path, monkeypatch):
    import tsm.domain.reference as reference
    monkeypatch.setattr(reference, 'SCENARIOS_DIR', tmp_path)
    import tsm.domain.scenario as scenario_mod
    monkeypatch.setattr(scenario_mod, 'SCENARIOS_DIR', tmp_path)
    api = Api(run_manager=RunManager(logs_dir=tmp_path))
    doc = json.loads((Path('scenarios') / 'escorte_ormuz.json').read_text(encoding='utf-8'))
    assert api.save_scenario('mon_v2', doc) == {'ok': True}
    assert (tmp_path / 'mon_v2.json').exists()


def test_save_scenario_v2_invalid_is_rejected_in_french(tmp_path, monkeypatch):
    import tsm.domain.reference as reference
    monkeypatch.setattr(reference, 'SCENARIOS_DIR', tmp_path)
    api = Api(run_manager=RunManager(logs_dir=tmp_path))
    with pytest.raises(ScenarioError, match='forces manquant'):
        api.save_scenario('casse', {'version': 2, 'information_policy': 'omniscient'})
    assert not (tmp_path / 'casse.json').exists()


# ── Task 2 : validation à l'édition + tâches v3 exposées ─────────────────────

def test_kb_exposes_v3_mission_tasks(tmp_path):
    api = Api(run_manager=RunManager(logs_dir=tmp_path))
    kb = api.get_kb()
    assert 'poursuivre' in kb['v3_tasks']
    assert 'escorter_convoi' in kb['v3_tasks']
    assert 'transiter_vers_zone' in kb['v3_tasks']
    assert 'veiller' not in kb['v3_tasks']  # tâche v1 : ne décompose pas en primitives v3


def test_validate_scenario_ok_for_reference_pair(tmp_path):
    api = Api(run_manager=RunManager(logs_dir=tmp_path))
    doc = json.loads((Path('scenarios') / 'escorte_ormuz.json').read_text(encoding='utf-8'))
    assert api.validate_scenario(doc, 'kinematic-ormuz') == {'ok': True, 'errors': []}


def test_validate_scenario_reports_missing_capability_in_french(tmp_path):
    api = Api(run_manager=RunManager(logs_dir=tmp_path))
    doc = json.loads((Path('scenarios') / 'escorte_ormuz.json').read_text(encoding='utf-8'))
    doc['agents']['cargo_1']['mission'] = {'task': 'escorter_convoi', 'args': ['cargo_1']}
    result = api.validate_scenario(doc, 'kinematic-ormuz')
    assert result['ok'] is False
    assert any('cargo_1' in e and 'manquante' in e for e in result['errors'])


def test_validate_scenario_reports_schema_errors(tmp_path):
    api = Api(run_manager=RunManager(logs_dir=tmp_path))
    result = api.validate_scenario({'version': 2}, 'kinematic-ormuz')
    assert result['ok'] is False and result['errors']


# ── Amendements post-review Task 4 : référents de mission (§4.5) ─────────────

def test_validate_scenario_reports_invalid_zone_referent_in_french(tmp_path):
    api = Api(run_manager=RunManager(logs_dir=tmp_path))
    doc = json.loads((Path('scenarios') / 'escorte_ormuz.json').read_text(encoding='utf-8'))
    doc['agents']['vedette_2']['mission']['args'] = ['vedette_2', '']
    result = api.validate_scenario(doc, 'kinematic-ormuz')
    assert result['ok'] is False
    assert any('vedette_2' in e and 'invalide' in e for e in result['errors'])


def test_validate_scenario_reports_unknown_zone_referent(tmp_path):
    api = Api(run_manager=RunManager(logs_dir=tmp_path))
    doc = json.loads((Path('scenarios') / 'escorte_ormuz.json').read_text(encoding='utf-8'))
    doc['agents']['vedette_2']['mission']['args'] = ['vedette_2', 'zone_inconnue']
    result = api.validate_scenario(doc, 'kinematic-ormuz')
    assert result['ok'] is False


def test_validate_scenario_reports_self_referent_mismatch(tmp_path):
    api = Api(run_manager=RunManager(logs_dir=tmp_path))
    doc = json.loads((Path('scenarios') / 'escorte_ormuz.json').read_text(encoding='utf-8'))
    doc['agents']['vedette_2']['mission']['args'] = ['autre_nom', 'repli_nord']
    result = api.validate_scenario(doc, 'kinematic-ormuz')
    assert result['ok'] is False


# ── Amendements post-review Task 5 : conditions et actions de trigger ────────

def test_validate_scenario_reports_all_in_zone_missing_force_in_french(tmp_path):
    api = Api(run_manager=RunManager(logs_dir=tmp_path))
    doc = json.loads((Path('scenarios') / 'escorte_ormuz.json').read_text(encoding='utf-8'))
    doc['end']['success'][0]['force'] = ''
    result = api.validate_scenario(doc, 'kinematic-ormuz')
    assert result['ok'] is False
    assert any('end.success[0]' in e and 'force' in e for e in result['errors'])


def test_validate_scenario_reports_agent_destroyed_without_carrier_in_french(tmp_path):
    api = Api(run_manager=RunManager(logs_dir=tmp_path))
    doc = json.loads((Path('scenarios') / 'escorte_ormuz.json').read_text(encoding='utf-8'))
    doc['end']['failure'][0] = {'type': 'agent_destroyed'}
    result = api.validate_scenario(doc, 'kinematic-ormuz')
    assert result['ok'] is False
    assert any('end.failure[0]' in e and 'porteur' in e for e in result['errors'])


def test_validate_scenario_reports_trigger_without_action_in_french(tmp_path):
    api = Api(run_manager=RunManager(logs_dir=tmp_path))
    doc = json.loads((Path('scenarios') / 'escorte_ormuz.json').read_text(encoding='utf-8'))
    doc['triggers'][0]['do'] = []
    result = api.validate_scenario(doc, 'kinematic-ormuz')
    assert result['ok'] is False
    assert any('embuscade-rouge' in e and 'sans action' in e for e in result['errors'])


def test_validate_scenario_reports_trigger_action_unknown_force_in_french(tmp_path):
    api = Api(run_manager=RunManager(logs_dir=tmp_path))
    doc = json.loads((Path('scenarios') / 'escorte_ormuz.json').read_text(encoding='utf-8'))
    doc['triggers'][0]['do'] = [{'type': 'spawn_force', 'force': 'force_inexistante'}]
    result = api.validate_scenario(doc, 'kinematic-ormuz')
    assert result['ok'] is False
    assert any('force_inexistante' in e for e in result['errors'])


def test_launch_v2_scenario_with_invalid_referent_rejected_before_spawn(tmp_path, monkeypatch):
    # Un référent invalide fait un 400 AVANT le spawn du run — sinon
    # timeout silencieux (goto_m → False à chaque tick, cf. controller.py).
    doc = json.loads((Path('scenarios') / 'escorte_ormuz.json').read_text(encoding='utf-8'))
    doc['agents']['vedette_2']['mission']['args'] = ['vedette_2', 'zone_inconnue']
    broken = ReferenceScenario.from_dict(doc)

    import tsm.web.api as api_mod
    monkeypatch.setattr(api_mod, 'peek_version', lambda name: 2)
    monkeypatch.setattr(api_mod, 'load_reference_scenario', lambda name: broken)

    seen = {}

    def cmd(name, profile=None):
        seen['called'] = True
        return [sys.executable, '-c', 'import time; time.sleep(2)']

    rm = RunManager(cmd=cmd, logs_dir=tmp_path)
    api = Api(run_manager=rm)
    with pytest.raises(ScenarioError):
        api.launch('escorte_ormuz', 'kinematic-ormuz')
    assert 'called' not in seen
