# tests/test_reference_objectives.py
import dataclasses

import pytest

from tsm.execution.objectives import Objective, ObjectiveFactory, ObjectiveStatus, ObjectiveUpdate


def test_factory_assigns_deterministic_zero_padded_ids_without_uuid():
    factory = ObjectiveFactory()
    first = factory.create("cargo", "navigation.goto", {"target": [1.0, 2.0]},
                           sim_time_s=10.0, timeout_s=30.0)
    second = factory.create("cargo", "navigation.goto", {"target": [1.0, 2.0]},
                            sim_time_s=10.0, timeout_s=30.0)
    assert first.id == "g-000001"
    assert second.id == "g-000002"


def test_factory_computes_deadline_from_sim_time_and_timeout():
    factory = ObjectiveFactory()
    goal = factory.create("cargo", "navigation.goto", {}, sim_time_s=10.0, timeout_s=30.0)
    assert goal.submitted_sim_time_s == 10.0
    assert goal.deadline_sim_time_s == 40.0


def test_objective_update_reason_defaults_to_none():
    update = ObjectiveUpdate("g-000001", ObjectiveStatus.ACCEPTED, 1.0)
    assert update.reason is None


def test_objective_is_frozen():
    goal = Objective("g-000001", "cargo", "navigation.goto", {}, 0.0, 60.0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        goal.agent = "red"  # type: ignore[misc]
