import json

import pytest

from tsm.web.runs import RunManager, create_run_directory, next_run_id, write_report


# ── Red tests du brief (verbatim) ────────────────────────────────────────────

def test_v3_run_creates_a_unique_directory_with_immutable_inputs(tmp_path):
    run = create_run_directory(tmp_path, run_id="r-000001",
                               scenario_doc={"version": 2}, profile_doc={"version": 1},
                               doctrine_doc={"tasks": {}})
    assert (run / "scenario.json").read_text() == '{\n  "version": 2\n}\n'
    assert (run / "profile.json").exists()
    assert (run / "events.jsonl").exists()


def test_status_keeps_process_and_verdict_distinct(tmp_path):
    manager = RunManager(logs_dir=tmp_path)
    manager.record_verdict("succeeded", "all_in_zone")
    status = manager.status()
    assert status["verdict"] == "succeeded"
    assert status["state"] != "succeeded"


# ── Compléments Task 7 ────────────────────────────────────────────────────────

def test_create_run_directory_writes_doctrine_and_empty_pose_files(tmp_path):
    run = create_run_directory(tmp_path, run_id="r-000001", scenario_doc={"version": 2},
                               profile_doc={"version": 1, "name": "p"}, doctrine_doc={"tasks": {}})
    assert (run / "doctrine.json").read_text() == '{\n  "tasks": {}\n}\n'
    assert (run / "poses.csv").read_text() == ''
    assert (run / "waypoints.csv").read_text() == ''
    assert (run / "events.jsonl").read_text() == ''


def test_create_run_directory_never_reuses_an_existing_run_id(tmp_path):
    create_run_directory(tmp_path, run_id="r-000001", scenario_doc={"version": 2},
                         profile_doc={"version": 1, "name": "p"}, doctrine_doc={})
    with pytest.raises(FileExistsError):
        create_run_directory(tmp_path, run_id="r-000001", scenario_doc={"version": 2},
                             profile_doc={"version": 1, "name": "p"}, doctrine_doc={})


def test_next_run_id_increments_past_existing_directories_and_never_reuses(tmp_path):
    assert next_run_id(tmp_path) == "r-000001"
    (tmp_path / "r-000001").mkdir()
    (tmp_path / "r-000007").mkdir()
    assert next_run_id(tmp_path) == "r-000008"


def test_manifest_contains_run_id_versions_capabilities_and_git_version(tmp_path):
    profile_doc = {
        "version": 1, "name": "kinematic-ormuz",
        "agents": {
            "escorte": {"providers": {
                "lotusim.waypoint_follower": {"capabilities": ["navigation.follow_target"]},
                "adjudicated": {"capabilities": ["engage.attack_target"]},
            }},
        },
    }
    run = create_run_directory(tmp_path, run_id="r-000002",
                               scenario_doc={"version": 2}, profile_doc=profile_doc,
                               doctrine_doc={})
    manifest = json.loads((run / "manifest.json").read_text())
    assert manifest["run_id"] == "r-000002"
    assert manifest["scenario_version"] == 2
    assert manifest["profile_name"] == "kinematic-ormuz"
    assert manifest["profile_version"] == 1
    assert manifest["capabilities"]["escorte"] == [
        "engage.attack_target", "navigation.follow_target"]
    assert "git_version" in manifest  # None si git absent, sinon un sha court


def test_report_is_written_atomically_with_verdict_fields(tmp_path):
    run = create_run_directory(tmp_path, run_id="r-000003", scenario_doc={"version": 2},
                               profile_doc={"version": 1, "name": "p"}, doctrine_doc={})
    write_report(run, verdict="timed_out", reason=None,
                started_sim_time_s=0.0, finished_sim_time_s=180.0)
    assert not (run / ".report.json.tmp").exists()
    report = json.loads((run / "report.json").read_text())
    assert report == {"verdict": "timed_out", "reason": None,
                      "started_sim_time_s": 0.0, "finished_sim_time_s": 180.0}


def test_read_artifact_rejects_invalid_run_id_or_kind(tmp_path):
    rm = RunManager(logs_dir=tmp_path)
    with pytest.raises(Exception):
        rm.read_artifact("../../etc", "report")
    with pytest.raises(Exception):
        rm.read_artifact("r-000001", "run.log")
