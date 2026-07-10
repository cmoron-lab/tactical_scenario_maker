import csv

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
