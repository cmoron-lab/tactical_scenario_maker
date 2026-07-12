# tests/test_reference_world.py
from tsm.domain.scenario import Position
from tsm.execution.world import WorldStore


def test_world_store_uses_simulated_time_and_never_predicts_a_goal():
    store = WorldStore()
    first = store.update_poses(5.0, {"cargo": Position(1.0, 2.0)})
    second = store.update_poses(5.2, {"cargo": Position(1.0001, 2.0)})
    assert first.sim_time_s == 5.0
    assert second.positions["cargo"] == Position(1.0001, 2.0)
    assert second.revision == first.revision + 1


def test_destroyed_agent_is_preserved_when_the_next_pose_message_omits_it():
    store = WorldStore()
    store.update_poses(1, {"red": Position(1, 2)})
    store.mark_destroyed("red")
    assert "red" in store.update_poses(2, {}).destroyed
