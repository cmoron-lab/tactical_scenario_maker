# tests/test_reference_schema.py
import json

import pytest

from tsm.domain.reference import (
    ReferenceScenario,
    compile_authored_graph,
    load_reference_scenario,
)
from tsm.domain.scenario import ScenarioError


def test_reference_scenario_keeps_spawn_config_out_of_tactical_agents():
    doc = {
        "version": 2,
        "information_policy": "omniscient",
        "forces": {"verte": {"agents": ["cargo"]}},
        "relations": [],
        "zones": {"sortie": {"center": {"lat": 1.0, "lon": 2.0}, "radius_deg": 0.001}},
        "agents": {
            "cargo": {
                "platform": "surface_vessel",
                "position": {"lat": 1.0, "lon": 2.0},
                "mission": {"task": "transiter", "args": ["cargo", "sortie"]},
                "conditions": {},
            }
        },
        "triggers": [],
        "end": {"success": [{"type": "all_in_zone", "force": "verte", "zone": "sortie"}],
                "failure": [], "timeout": "PT60S"},
    }
    scenario = ReferenceScenario.from_dict(doc)
    assert scenario.to_dict() == doc
    with pytest.raises(ScenarioError, match="profil d.execution"):
        ReferenceScenario.from_dict({**doc, "agents": {**doc["agents"],
            "cargo": {**doc["agents"]["cargo"], "model": "wamv"}}})


def test_compile_authored_graph_includes_deferred_forces_but_marks_them_inactive():
    doc = {
        "version": 2,
        "information_policy": "omniscient",
        "forces": {
            "bleue": {"agents": ["cargo"]},
            "rouge": {"agents": ["patrouilleur"], "spawn": "deferred"},
        },
        "relations": [],
        "zones": {},
        "agents": {
            "cargo": {
                "platform": "surface_vessel",
                "position": {"lat": 1.0, "lon": 2.0},
                "mission": {"task": "transiter", "args": ["cargo"]},
                "conditions": {},
            },
            "patrouilleur": {
                "platform": "surface_vessel",
                "position": {"lat": 1.1, "lon": 2.1},
                "mission": {"task": "patrouiller", "args": ["patrouilleur"]},
                "conditions": {},
            },
        },
        "triggers": [],
        "end": {"success": [], "failure": [], "timeout": "PT60S"},
    }
    scenario = ReferenceScenario.from_dict(doc)
    graph = compile_authored_graph(scenario)

    assert set(graph.by_force) == {"bleue", "rouge"}
    assert graph.by_force["rouge"]["patrouilleur"].task == "patrouiller"
    assert scenario.forces["bleue"].spawn == "initial"
    assert scenario.forces["rouge"].spawn == "deferred"


def test_load_reference_scenario_reads_from_directory(tmp_path):
    doc = {
        "version": 2, "information_policy": "omniscient",
        "forces": {"bleue": {"agents": ["cargo"]}}, "relations": [],
        "zones": {}, "triggers": [],
        "agents": {"cargo": {
            "platform": "surface_vessel",
            "position": {"lat": 1.0, "lon": 2.0},
            "mission": {"task": "transiter", "args": ["cargo"]},
            "conditions": {},
        }},
        "end": {"success": [], "failure": [], "timeout": "PT60S"},
    }
    (tmp_path / "demo.json").write_text(json.dumps(doc), encoding="utf-8")
    scenario = load_reference_scenario("demo", directory=tmp_path)
    assert scenario.information_policy == "omniscient"


def test_load_reference_scenario_missing_file_raises(tmp_path):
    with pytest.raises(ScenarioError, match="introuvable"):
        load_reference_scenario("absent", directory=tmp_path)
