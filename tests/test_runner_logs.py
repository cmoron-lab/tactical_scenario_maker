import csv
import json
import threading

from tsm.execution.runner import RunLogs


def test_runlogs_writes_flushed_rows(tmp_path):
    logs = RunLogs(directory=tmp_path)
    logs.log_pose('usv', 1.26, 103.75)
    logs.log_waypoint('usv', 1.27, 103.76)
    # flush systématique : lisible AVANT close
    with open(tmp_path / 'poses.csv') as f:
        rows = list(csv.reader(f))
    assert rows[0] == ['timestamp', 'agent', 'lat', 'lon']
    assert rows[1][1:] == ['usv', '1.26', '103.75']
    logs.close()
    with open(tmp_path / 'waypoints.csv') as f:
        assert list(csv.reader(f))[1][1:] == ['usv', '1.27', '103.76']


def test_log_event_writes_flushed_json_line(tmp_path):
    logs = RunLogs(directory=tmp_path)
    logs.log_event('run_start', scenario='x', agents=['a'])
    # flush systématique : lisible AVANT close
    with open(tmp_path / 'events.jsonl') as f:
        lines = f.readlines()
    assert len(lines) == 1
    event = json.loads(lines[0])
    assert event['kind'] == 'run_start'
    assert event['scenario'] == 'x'
    assert event['agents'] == ['a']
    assert 't' in event
    logs.close()


def test_log_event_accepts_optional_sim_time_s(tmp_path):
    logs = RunLogs(directory=tmp_path)
    logs.log_event('plan', agent='usv', sim_time_s=12.5)
    logs.log_event('spawn', agent='usv2')
    logs.close()
    with open(tmp_path / 'events.jsonl') as f:
        events = [json.loads(line) for line in f]
    assert events[0]['sim_time_s'] == 12.5
    assert events[1]['sim_time_s'] is None  # horodatage mur ('t') reste, sim_time_s optionnel


def test_log_event_preserves_order(tmp_path):
    logs = RunLogs(directory=tmp_path)
    logs.log_event('spawn', agent='usv1')
    logs.log_event('spawn', agent='usv2')
    logs.close()
    with open(tmp_path / 'events.jsonl') as f:
        events = [json.loads(line) for line in f]
    assert [e['agent'] for e in events] == ['usv1', 'usv2']


def test_log_event_thread_safe(tmp_path):
    logs = RunLogs(directory=tmp_path)

    def emit(agent):
        for i in range(50):
            logs.log_event('spawn', agent=agent, i=i)

    threads = [threading.Thread(target=emit, args=(a,)) for a in ('usv1', 'usv2')]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    logs.close()
    with open(tmp_path / 'events.jsonl') as f:
        events = [json.loads(line) for line in f]
    assert len(events) == 100
