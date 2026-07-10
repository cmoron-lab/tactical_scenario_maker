import json
import sys
import time

import pytest

from tsm.web.runs import RunBusyError, RunManager

SLEEP_30 = lambda name: [sys.executable, '-c', 'import time; time.sleep(30)']  # noqa: E731
EXIT_3 = lambda name: [sys.executable, '-c', 'import sys; sys.exit(3)']  # noqa: E731
SIGINT_OK = lambda name: [  # noqa: E731
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
