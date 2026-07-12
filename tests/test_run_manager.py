import json
import subprocess
import sys
import time

import pytest

from tsm.web.runs import RunBusyError, RunManager, _default_cmd

SLEEP_30 = lambda name, profile=None: [sys.executable, '-c', 'import time; time.sleep(30)']  # noqa: E731
EXIT_3 = lambda name, profile=None: [sys.executable, '-c', 'import sys; sys.exit(3)']  # noqa: E731
SIGINT_OK = lambda name, profile=None: [  # noqa: E731
    sys.executable, '-c',
    'import signal,sys,time\n'
    'signal.signal(signal.SIGINT, lambda *a: sys.exit(0)); time.sleep(30)',
]


def _wait_until(predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError('timeout en attendant la condition')


def test_status_initial_idle(tmp_path):
    rm = RunManager(logs_dir=tmp_path)
    assert rm.status() == {
        'state': 'idle', 'scenario': None, 'pid': None,
        'started_at': None, 'returncode': None, 'stop_requested': False,
        'verdict': 'pending', 'verdict_reason': None,
        'profile': None, 'run_id': None,
    }


def test_launch_running(tmp_path):
    rm = RunManager(cmd=SLEEP_30, logs_dir=tmp_path)
    pid = rm.launch('demo')
    try:
        assert pid
        st = rm.status()
        assert st['state'] == 'running'
        assert st['pid'] == pid
        assert st['scenario'] == 'demo'
        assert st['stop_requested'] is False
    finally:
        rm.stop()


def test_double_launch_raises_run_busy(tmp_path):
    rm = RunManager(cmd=SLEEP_30, logs_dir=tmp_path)
    rm.launch('demo')
    try:
        with pytest.raises(RunBusyError):
            rm.launch('autre')
    finally:
        rm.stop()


def test_stop_leads_to_finished(tmp_path):
    rm = RunManager(cmd=SIGINT_OK, logs_dir=tmp_path)
    rm.launch('demo')
    time.sleep(0.2)  # laisse le sous-processus installer son handler SIGINT avant qu'on l'envoie
    assert rm.stop() is True
    assert rm.status()['stop_requested'] is True
    _wait_until(lambda: rm.status()['state'] != 'running')
    st = rm.status()
    assert st['state'] == 'finished'
    assert st['returncode'] == 0


def test_process_exit_nonzero_is_failed(tmp_path):
    rm = RunManager(cmd=EXIT_3, logs_dir=tmp_path)
    rm.launch('demo')
    _wait_until(lambda: rm.status()['state'] != 'running')
    st = rm.status()
    assert st['state'] == 'failed'
    assert st['returncode'] == 3


def test_stop_without_run_returns_false(tmp_path):
    rm = RunManager(logs_dir=tmp_path)
    assert rm.stop() is False


def test_stop_timer_does_not_kill_next_run(tmp_path, monkeypatch):
    # le timer armé au stop() du run N ne doit pas pouvoir tuer le run N+1
    # relancé dans sa fenêtre — fenêtre rétrécie pour la traverser vite
    monkeypatch.setattr('tsm.web.runs.STOP_TIMEOUT', 0.3)
    cmd = lambda name, profile=None: SIGINT_OK(name) if name == 'court' else SLEEP_30(name)  # noqa: E731
    rm = RunManager(cmd=cmd, logs_dir=tmp_path)
    rm.launch('court')
    time.sleep(0.2)  # laisse le sous-processus installer son handler SIGINT
    assert rm.stop() is True
    _wait_until(lambda: rm.status()['state'] != 'running')  # N sort proprement
    rm.launch('long')  # relaunch dans la fenêtre du timer de N
    try:
        time.sleep(0.6)  # traverse le déclenchement du timer périmé
        assert rm.status()['state'] == 'running'
    finally:
        rm.stop()


def test_events_since(tmp_path):
    rm = RunManager(logs_dir=tmp_path)
    assert rm.events_since(0) == {'events': [], 'next': 0}

    lines = [
        json.dumps({'kind': 'a'}),
        json.dumps({'kind': 'b'}),
        json.dumps({'kind': 'c'}),
        '{"kind": "d"',  # dernière ligne partielle (écriture en cours)
    ]
    (tmp_path / 'events.jsonl').write_text('\n'.join(lines) + '\n')

    result = rm.events_since(0)
    assert result['next'] == 3
    assert [e['kind'] for e in result['events']] == ['a', 'b', 'c']

    result = rm.events_since(2)
    assert [e['kind'] for e in result['events']] == ['c']


def test_poses_incremental_and_reset(tmp_path):
    rm = RunManager(logs_dir=tmp_path)
    assert rm.poses() == {'agents': {}}

    poses_csv = tmp_path / 'poses.csv'
    wp_csv = tmp_path / 'waypoints.csv'
    poses_csv.write_text(
        'timestamp,agent,lat,lon\n'
        't1,usv,1.0,103.0\n'
        't2,usv,1.1,103.1\n'
    )
    wp_csv.write_text(
        'timestamp,agent,lat,lon\n'
        't1,usv,1.5,103.5\n'
    )

    result = rm.poses()
    agent = result['agents']['usv']
    assert agent['lat'] == 1.1
    assert agent['lon'] == 103.1
    assert agent['t'] == 't2'
    assert agent['trail'] == [[1.0, 103.0], [1.1, 103.1]]
    assert agent['waypoint'] == [1.5, 103.5]

    # incrémental : une ligne de plus, seule la nouvelle est lue
    with open(poses_csv, 'a') as f:
        f.write('t3,usv,1.2,103.2\n')
    result = rm.poses()
    agent = result['agents']['usv']
    assert agent['trail'] == [[1.0, 103.0], [1.1, 103.1], [1.2, 103.2]]

    # troncature (nouveau run) : reset détecté, l'ancien trail est purgé
    poses_csv.write_text(
        'timestamp,agent,lat,lon\n'
        't1,usv,9.0,9.0\n'
    )
    result = rm.poses()
    agent = result['agents']['usv']
    assert agent['trail'] == [[9.0, 9.0]]


def test_poses_truncation_of_both_files_purges_once(tmp_path):
    # un nouveau run tronque LES DEUX fichiers : un seul appel poses() doit
    # rendre poses ET waypoint — pas de re-purge entre les deux consommations
    rm = RunManager(logs_dir=tmp_path)
    poses_csv = tmp_path / 'poses.csv'
    wp_csv = tmp_path / 'waypoints.csv'
    poses_csv.write_text(
        'timestamp,agent,lat,lon\n'
        't1,usv,1.0,103.0\n'
        't2,usv,1.1,103.1\n'
        't3,usv,1.2,103.2\n'
    )
    wp_csv.write_text(
        'timestamp,agent,lat,lon\n'
        't1,usv,1.5,103.5\n'
        't2,usv,1.6,103.6\n'
    )
    rm.poses()  # accumule et mémorise les offsets du run N

    # run N+1 : les deux fichiers tronqués puis réécrits (plus courts)
    poses_csv.write_text(
        'timestamp,agent,lat,lon\n'
        't9,usv,9.0,9.0\n'
    )
    wp_csv.write_text(
        'timestamp,agent,lat,lon\n'
        't9,usv,9.5,9.5\n'
    )
    agent = rm.poses()['agents']['usv']
    assert agent['lat'] == 9.0
    assert agent['lon'] == 9.0
    assert agent['t'] == 't9'
    assert agent['trail'] == [[9.0, 9.0]]
    assert agent['waypoint'] == [9.5, 9.5]


# ── Task 7 : profil, run_id, verdict, provenance ─────────────────────────────

def test_default_cmd_includes_profile_flag_only_when_given():
    assert _default_cmd('escorte_ormuz', 'kinematic-ormuz') == [
        sys.executable, 'main.py', 'escorte_ormuz', '--profile', 'kinematic-ormuz']
    assert _default_cmd('demo') == [sys.executable, 'main.py', 'demo']
    assert _default_cmd('demo', None) == [sys.executable, 'main.py', 'demo']


def test_launch_forwards_profile_to_cmd_and_exposes_it_in_status(tmp_path):
    seen = {}

    def cmd(name, profile=None):
        seen['name'], seen['profile'] = name, profile
        return SLEEP_30(name)

    rm = RunManager(cmd=cmd, logs_dir=tmp_path)
    rm.launch('escorte_ormuz', profile='kinematic-ormuz')
    try:
        assert seen == {'name': 'escorte_ormuz', 'profile': 'kinematic-ormuz'}
        assert rm.status()['profile'] == 'kinematic-ormuz'
    finally:
        rm.stop()


def test_relaunch_resets_verdict_from_previous_run(tmp_path):
    rm = RunManager(cmd=SLEEP_30, logs_dir=tmp_path)
    rm.record_verdict('succeeded', 'all_in_zone')
    rm.launch('demo')
    try:
        status = rm.status()
        assert status['verdict'] == 'pending'
        assert status['verdict_reason'] is None
    finally:
        rm.stop()


def test_status_reads_verdict_lazily_from_report_json_once_process_exited(tmp_path):
    rm = RunManager(cmd=EXIT_3, logs_dir=tmp_path)
    rm.launch('escorte_ormuz', profile='kinematic-ormuz')
    # le sous-processus crée SON répertoire APRÈS le launch (clôture de
    # propriété : seul un id postérieur au launch est adoptable) — simulé ici
    run_dir = tmp_path / 'r-000001'
    run_dir.mkdir()
    (run_dir / 'report.json').write_text(json.dumps({
        'verdict': 'failed', 'reason': 'agent_destroyed',
        'started_sim_time_s': 0.0, 'finished_sim_time_s': 12.0,
    }))
    _wait_until(lambda: rm.status()['state'] != 'running')
    status = rm.status()
    assert status['state'] == 'failed'  # état processus (EXIT_3 → rc=3)
    assert status['verdict'] == 'failed'  # verdict métier, lu dans report.json
    assert status['verdict_reason'] == 'agent_destroyed'
    assert status['run_id'] == 'r-000001'


def test_events_and_poses_are_read_from_the_run_id_subdirectory_once_known(tmp_path):
    # fichiers plats (legacy) : ne doivent pas être lus une fois qu'un run_id
    # v3 est connu — sinon on afficherait un run périmé.
    (tmp_path / 'events.jsonl').write_text(json.dumps({'kind': 'stale'}) + '\n')

    rm = RunManager(cmd=SLEEP_30, logs_dir=tmp_path)
    rm.launch('escorte_ormuz', profile='kinematic-ormuz')
    try:
        # répertoire créé par le sous-processus APRÈS le launch (clôture de propriété)
        run_dir = tmp_path / 'r-000001'
        run_dir.mkdir()
        (run_dir / 'events.jsonl').write_text(json.dumps({'kind': 'run_start'}) + '\n')
        (run_dir / 'poses.csv').write_text('timestamp,agent,lat,lon\n0.0,usv,1.0,103.0\n')
        events = rm.events_since(0)
        assert [e['kind'] for e in events['events']] == ['run_start']
        assert rm.poses()['agents']['usv']['lat'] == 1.0
    finally:
        rm.stop()


def test_status_never_adopts_a_previous_runs_verdict(tmp_path):
    # run 1 : a laissé son répertoire et un verdict succeeded
    old_dir = tmp_path / 'r-000001'
    old_dir.mkdir()
    (old_dir / 'report.json').write_text(json.dumps({
        'verdict': 'succeeded', 'reason': 'all_in_zone',
        'started_sim_time_s': 0.0, 'finished_sim_time_s': 60.0,
    }))
    # run 2 : meurt AVANT create_run_directory (ex. profil introuvable) —
    # aucun nouveau répertoire. Son échec ne doit JAMAIS hériter du verdict
    # du run 1 (clôture de propriété dans _discover_run_id).
    rm = RunManager(cmd=EXIT_3, logs_dir=tmp_path)
    rm.launch('escorte_ormuz', profile='inexistant')
    _wait_until(lambda: rm.status()['state'] != 'running')
    status = rm.status()
    assert status['state'] == 'failed'
    assert status['verdict'] == 'pending'
    assert status['verdict_reason'] is None
    assert status['run_id'] is None


# ── CLI (main.py) : erreurs claires avant tout import ROS ────────────────────

def _run_cli(*args):
    from tsm.web.runs import REPO_ROOT
    return subprocess.run([sys.executable, 'main.py', *args], cwd=REPO_ROOT,
                          capture_output=True, text=True, timeout=10)


def test_cli_v2_scenario_without_profile_exits_with_clear_french_error():
    result = _run_cli('escorte_ormuz')
    assert result.returncode != 0
    assert 'profile' in result.stderr


def test_cli_v1_scenario_with_profile_exits_with_clear_french_error():
    result = _run_cli('demo_veille_drone_intru', '--profile', 'kinematic-ormuz')
    assert result.returncode != 0
    assert 'profile' in result.stderr
