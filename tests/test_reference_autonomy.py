# tests/test_reference_autonomy.py
from tests.reference_fixtures import kinematic_provider, objective, snapshot
from tsm.execution.objectives import ObjectiveStatus


def test_goto_is_not_succeeded_until_an_observed_pose_reaches_target():
    provider, transport = kinematic_provider()
    goal = objective("g-000001", "cargo", "navigation.goto",
                     {"target": [1.001, 2.0], "arrival_radius_deg": 0.00002})
    assert provider.submit(goal, snapshot(0, {"cargo": (1.0, 2.0)})).status == ObjectiveStatus.ACCEPTED
    assert transport.waypoints == [("cargo", 1.001, 2.0)]
    assert provider.tick(snapshot(1, {"cargo": (1.0005, 2.0)}))[-1].status == ObjectiveStatus.IN_PROGRESS
    assert provider.tick(snapshot(2, {"cargo": (1.001, 2.0)}))[-1].status == ObjectiveStatus.SUCCEEDED


def test_follow_target_updates_waypoint_inside_provider_not_supervisor():
    provider, transport = kinematic_provider()
    provider.submit(objective("g-000001", "red", "navigation.follow_target",
                              {"target_agent": "cargo", "update_threshold_deg": 0.0003}),
                    snapshot(0, {"red": (1.0, 2.0), "cargo": (1.1, 2.0)}))
    provider.tick(snapshot(1, {"red": (1.0, 2.0), "cargo": (1.101, 2.0)}))
    assert len(transport.waypoints) == 2


def test_follow_target_does_not_reemit_below_update_threshold():
    provider, transport = kinematic_provider()
    provider.submit(objective("g-000001", "red", "navigation.follow_target",
                              {"target_agent": "cargo", "update_threshold_deg": 0.0003}),
                    snapshot(0, {"red": (1.0, 2.0), "cargo": (1.1, 2.0)}))
    provider.tick(snapshot(1, {"red": (1.0, 2.0), "cargo": (1.10001, 2.0)}))
    assert len(transport.waypoints) == 1


def test_follow_target_succeeds_only_when_stop_distance_is_configured_and_reached():
    provider, _ = kinematic_provider()
    provider.submit(objective("g-000001", "red", "navigation.follow_target",
                              {"target_agent": "cargo", "update_threshold_deg": 0.0003,
                               "stop_distance_deg": 0.05}),
                    snapshot(0, {"red": (1.0, 2.0), "cargo": (1.1, 2.0)}))
    update = provider.tick(snapshot(1, {"red": (1.08, 2.0), "cargo": (1.1, 2.0)}))[-1]
    assert update.status == ObjectiveStatus.SUCCEEDED


def test_follow_target_without_stop_distance_never_succeeds():
    provider, _ = kinematic_provider()
    provider.submit(objective("g-000001", "red", "navigation.follow_target",
                              {"target_agent": "cargo", "update_threshold_deg": 0.0003}),
                    snapshot(0, {"red": (1.0, 2.0), "cargo": (1.1, 2.0)}))
    update = provider.tick(snapshot(1, {"red": (1.1, 2.0), "cargo": (1.1, 2.0)}))[-1]
    assert update.status == ObjectiveStatus.IN_PROGRESS


def test_follow_target_abandons_once_the_follower_leaves_its_anchor_envelope():
    # Enveloppe d'engagement : condition d'abandon portée par l'objectif —
    # le suiveur rompt dès que LUI s'éloigne de l'ancre (le protégé) au-delà
    # du rayon, même s'il gagne sur sa cible. Prime sur le succès : ici le
    # suiveur est AUSSI au contact (stop_distance atteint), il rompt quand même.
    provider, _ = kinematic_provider()
    provider.submit(objective("g-000001", "escorte", "navigation.follow_target",
                              {"target_agent": "fuyard", "update_threshold_deg": 0.0003,
                               "stop_distance_deg": 0.0005,
                               "abandon_anchor_agent": "cargo",
                               "abandon_beyond_deg": 0.0015}),
                    snapshot(0, {"escorte": (1.0, 2.0), "fuyard": (1.001, 2.0),
                                 "cargo": (1.0005, 2.0)}))
    inside = provider.tick(snapshot(1, {"escorte": (1.0, 2.0), "fuyard": (1.01, 2.0),
                                        "cargo": (1.001, 2.0)}))[-1]
    assert inside.status == ObjectiveStatus.IN_PROGRESS
    outside = provider.tick(snapshot(2, {"escorte": (1.005, 2.0), "fuyard": (1.0054, 2.0),
                                         "cargo": (1.001, 2.0)}))[-1]
    assert outside.status == ObjectiveStatus.FAILED
    assert outside.reason == "hors_enveloppe"


def test_follow_target_ignores_the_envelope_when_the_anchor_is_unobserved():
    provider, _ = kinematic_provider()
    provider.submit(objective("g-000001", "escorte", "navigation.follow_target",
                              {"target_agent": "fuyard", "update_threshold_deg": 0.0003,
                               "abandon_anchor_agent": "cargo",
                               "abandon_beyond_deg": 0.0015}),
                    snapshot(0, {"escorte": (1.0, 2.0), "fuyard": (1.01, 2.0)}))
    update = provider.tick(snapshot(1, {"escorte": (1.005, 2.0), "fuyard": (1.01, 2.0)}))[-1]
    assert update.status == ObjectiveStatus.IN_PROGRESS


def test_goto_fails_when_the_target_agent_is_destroyed():
    provider, _ = kinematic_provider()
    goal = objective("g-000001", "cargo", "navigation.goto",
                     {"target": [1.1, 2.0], "arrival_radius_deg": 0.00002})
    provider.submit(goal, snapshot(0, {"cargo": (1.0, 2.0)}))
    update = provider.tick(snapshot(1, {"cargo": (1.0, 2.0)}, destroyed={"cargo"}))[-1]
    assert update.status == ObjectiveStatus.FAILED
    assert update.reason == "target_destroyed"


def test_goto_fails_when_the_observed_pose_is_missing():
    provider, _ = kinematic_provider()
    goal = objective("g-000001", "cargo", "navigation.goto",
                     {"target": [1.1, 2.0], "arrival_radius_deg": 0.00002})
    provider.submit(goal, snapshot(0, {"cargo": (1.0, 2.0)}))
    update = provider.tick(snapshot(1, {}))[-1]
    assert update.status == ObjectiveStatus.FAILED
    assert update.reason == "missing_pose"


def test_follow_target_submit_fails_when_target_pose_is_missing():
    provider, transport = kinematic_provider()
    update = provider.submit(
        objective("g-000001", "red", "navigation.follow_target",
                 {"target_agent": "cargo", "update_threshold_deg": 0.0003}),
        snapshot(0, {"red": (1.0, 2.0)}))
    assert update.status == ObjectiveStatus.FAILED
    assert update.reason == "missing_pose"
    assert transport.waypoints == []


def test_terminal_objective_leaves_active_set_and_emits_nothing_more():
    provider, _ = kinematic_provider()
    goal = objective("g-000001", "cargo", "navigation.goto",
                     {"target": [1.001, 2.0], "arrival_radius_deg": 0.00002})
    provider.submit(goal, snapshot(0, {"cargo": (1.0, 2.0)}))
    provider.tick(snapshot(1, {"cargo": (1.001, 2.0)}))
    assert provider.tick(snapshot(2, {"cargo": (1.001, 2.0)})) == []


def test_cancel_stops_the_vessel_and_emits_a_terminal_result():
    provider, transport = kinematic_provider()
    goal = objective("g-000001", "cargo", "navigation.goto",
                     {"target": [1.1, 2.0], "arrival_radius_deg": 0.00002},
                     deadline_sim_time_s=20)
    provider.submit(goal, snapshot(0, {"cargo": (1.0, 2.0)}))
    update = provider.cancel(goal.id, snapshot(1, {"cargo": (1.0, 2.0)}))
    assert update.status is ObjectiveStatus.CANCELLED
    assert transport.stopped == ["cargo"]


def test_goal_times_out_using_simulated_time_not_wall_time():
    provider, _ = kinematic_provider()
    goal = objective("g-000001", "cargo", "navigation.goto",
                     {"target": [1.1, 2.0], "arrival_radius_deg": 0.00002},
                     deadline_sim_time_s=5)
    provider.submit(goal, snapshot(0, {"cargo": (1.0, 2.0)}))
    assert provider.tick(snapshot(5, {"cargo": (1.0, 2.0)}))[-1].status is ObjectiveStatus.TIMED_OUT


def test_provider_rejects_unknown_capability():
    provider, _ = kinematic_provider()
    update = provider.submit(objective("g-000001", "cargo", "engage.attack_target",
                                       {}, deadline_sim_time_s=5),
                             snapshot(0, {"cargo": (1.0, 2.0)}))
    assert update.status is ObjectiveStatus.FAILED
    assert update.reason == "unsupported_capability"
