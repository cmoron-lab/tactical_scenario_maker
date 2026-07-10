# tests/test_scenario_schema.py
import json

import pytest

from tsm.domain.scenario import (
    Mission, Scenario, ScenarioError,
    list_scenarios, load_scenario, save_scenario, delete_scenario,
)

DOC = {
    "version": 1,
    "agents": {
        "veilleur": {
            "position": {"lat": 1.26, "lon": 103.75},
            "heading_deg": 0.0,
            "model": "wamv",
            "velocity": {"linear": [0.0, 5.0], "angular_max": 0.05},
            "conditions": {"role": "patrol", "base_location": "1.260 103.750"},
            "mission": {"task": "veiller", "args": ["veilleur"]},
        }
    },
}


def test_round_trip():
    sc = Scenario.from_dict(DOC)
    assert sc.to_dict() == DOC


def test_agent_fields():
    sc = Scenario.from_dict(DOC)
    ag = sc.agents["veilleur"]
    assert ag.position.lat == 1.26 and ag.position.lon == 103.75
    assert ag.linear_velocity == (0.0, 5.0)
    assert ag.angular_velocity_max == 0.05


def test_mission_to_htn_task_converts_position_args():
    m = Mission(task="aller_a_position", args=["intrus", [1.28, 103.77]])
    assert m.to_htn_task() == ("aller_a_position", "intrus", (1.28, 103.77))


def test_bad_version_rejected():
    with pytest.raises(ScenarioError, match="version"):
        Scenario.from_dict({"version": 99, "agents": {}})


def test_missing_position_names_the_field():
    doc = json.loads(json.dumps(DOC))
    del doc["agents"]["veilleur"]["position"]
    with pytest.raises(ScenarioError, match="veilleur.*position"):
        Scenario.from_dict(doc)


def test_non_numeric_lat_rejected():
    doc = json.loads(json.dumps(DOC))
    doc["agents"]["veilleur"]["position"]["lat"] = "nord"
    with pytest.raises(ScenarioError, match="lat"):
        Scenario.from_dict(doc)


def test_store_round_trip(tmp_path):
    sc = Scenario.from_dict(DOC)
    save_scenario("demo", sc, directory=tmp_path)
    assert list_scenarios(directory=tmp_path) == ["demo"]
    assert load_scenario("demo", directory=tmp_path).to_dict() == DOC
    delete_scenario("demo", directory=tmp_path)
    assert list_scenarios(directory=tmp_path) == []


def test_store_rejects_path_traversal(tmp_path):
    with pytest.raises(ScenarioError, match="nom"):
        load_scenario("../etc/passwd", directory=tmp_path)
