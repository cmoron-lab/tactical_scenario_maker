# tests/test_reference_controller.py
from dataclasses import replace

import pytest

from tests.reference_fixtures import (
    FakeProvider,
    FakeTransport,
    NoopWhiteCell,
    StaticPlanner,
    controller_with,
    ormuz_profile,
    ormuz_scenario,
    profile_for_scenario,
    scenario_forces,
    snapshot,
    view,
)
from tsm.domain.reference import compile_authored_graph
from tsm.execution.controller import MissionSupervisor, RunController, RunStartError
from tsm.execution.objectives import ObjectiveFactory, ObjectiveStatus
from tsm.execution.white_cell import WhiteCell
from tsm.execution.world import WorldStore


# ── Step 1 : isolation des vues et des états ─────────────────────────────────

def test_force_view_hides_unobserved_agents_when_policy_becomes_force_scoped():
    scenario = scenario_forces(
        policy="force_scoped",
        forces={"bleue": ("escorte",), "rouge": ("vedette",)})
    controller = controller_with(scenario)
    view = controller.view_for("bleue",
                               snapshot(1, {"escorte": (1, 2), "vedette": (3, 4)}))
    assert "vedette" not in view.world.positions


def test_omniscient_reference_view_is_explicit_and_each_supervisor_has_own_state():
    controller = controller_with(scenario_forces(
        policy="omniscient",
        forces={"bleue": ("escorte",), "verte": ("cargo_1",)}))
    controller.start_initial_forces()
    controller.tick(snapshot(1, {"escorte": (1, 2), "cargo_1": (1.1, 2)}))
    assert controller.supervisor("bleue", "escorte") is not controller.supervisor("verte", "cargo_1")


# ── Step 2 : traduction de plan, un seul objectif à la fois ──────────────────

def test_supervisor_submits_one_goal_then_waits_for_terminal_update():
    provider = FakeProvider()
    supervisor = MissionSupervisor(
        agent="cargo_1", force="verte",
        planner=StaticPlanner([("goto", "cargo_1", (1.2, 2.0), 0.00002)]),
        providers={"navigation.goto": provider},
        objectives=ObjectiveFactory())
    supervisor.tick(view("verte", snapshot(0, {"cargo_1": (1.0, 2.0)})))
    assert [g.capability for g in provider.submitted] == ["navigation.goto"]
    supervisor.tick(view("verte", snapshot(1, {"cargo_1": (1.1, 2.0)})))
    assert len(provider.submitted) == 1


# ── Traduction des primitives → paramètres d'objectif ────────────────────────

def test_follow_target_primitive_carries_update_threshold_and_stop_distance():
    provider = FakeProvider()
    supervisor = MissionSupervisor(
        agent="escorte", force="bleue",
        planner=StaticPlanner([("follow_target", "escorte", "vedette_1", 0.00045)]),
        providers={"navigation.follow_target": provider},
        objectives=ObjectiveFactory(),
        update_threshold_deg=0.001)
    supervisor.tick(view("bleue", snapshot(0, {"escorte": (1.0, 2.0)})))
    goal = provider.submitted[0]
    assert goal.capability == "navigation.follow_target"
    assert goal.parameters["target_agent"] == "vedette_1"
    assert goal.parameters["update_threshold_deg"] == 0.001
    assert goal.parameters["stop_distance_deg"] == 0.00045


def test_attack_target_without_provider_fails_unsupported_without_crashing():
    supervisor = MissionSupervisor(
        agent="escorte", force="bleue",
        planner=StaticPlanner([("attack_target", "escorte", "vedette_1")]),
        providers={},  # engage.attack_target sans implémentation
        objectives=ObjectiveFactory())
    supervisor.tick(view("bleue", snapshot(0, {"escorte": (1.0, 2.0)})))
    assert supervisor.active_objective_id is None
    assert supervisor.last_terminal_update.status is ObjectiveStatus.FAILED
    assert supervisor.last_terminal_update.reason == "unsupported_capability"


# ── Routage des updates : terminal reçu → superviseur replanifie ─────────────

def test_terminal_update_from_provider_is_routed_back_and_clears_active():
    controller = _ormuz_controller()
    controller.start_initial_forces()
    controller.tick(snapshot(0, {"cargo_1": (26.5498, 56.3997), "escorte": (1.26, 56.40)}))
    cargo = controller.supervisor("verte", "cargo_1")
    assert cargo.active_objective_id is not None  # goto soumis
    # cargo_1 atteint sortie_ouest (26.557, 56.40) : le provider rapporte SUCCEEDED
    controller.tick(snapshot(1, {"cargo_1": (26.557, 56.40), "escorte": (1.26, 56.40)}))
    assert cargo.active_objective_id is None
    assert cargo.last_terminal_update.status is ObjectiveStatus.SUCCEEDED


def test_objective_events_log_transitions_only_never_in_progress_noise():
    events = []
    scenario = ormuz_scenario()
    controller = RunController(
        scenario=scenario, graph=compile_authored_graph(scenario),
        profile=profile_for_scenario(scenario), world_store=WorldStore(),
        white_cell=NoopWhiteCell(), transport=FakeTransport(),
        publish_event=events.append)
    controller.start_initial_forces()
    # goto de cargo_1 vers sortie_ouest (26.557, 56.40) : plusieurs ticks en
    # route (in_progress côté provider), puis arrivée.
    controller.tick(snapshot(0, {"cargo_1": (26.5498, 56.3997), "escorte": (1.26, 56.40)}))
    controller.tick(snapshot(1, {"cargo_1": (26.5520, 56.4000), "escorte": (1.26, 56.40)}))
    controller.tick(snapshot(2, {"cargo_1": (26.5540, 56.4000), "escorte": (1.26, 56.40)}))
    controller.tick(snapshot(3, {"cargo_1": (26.5570, 56.4000), "escorte": (1.26, 56.40)}))
    goal_id = controller.supervisor("verte", "cargo_1").last_terminal_update.objective_id
    trail = [(e["type"], e.get("status")) for e in events
             if e.get("objective_id") == goal_id]
    assert trail == [("objective_submitted", None),
                     ("objective_update", "accepted"),
                     ("objective_update", "succeeded")]


# ── Préflight refusé : RunStartError, zéro superviseur ───────────────────────

def test_incompatible_profile_raises_before_any_supervisor():
    scenario = scenario_forces(policy="omniscient", forces={"bleue": ("escorte",)})
    bad_profile = profile_for_scenario(scenario).__class__.from_dict({
        "version": 1, "name": "bad",
        "agents": {"escorte": {
            "fidelity": "kinematic",
            # transiter_vers_zone exige navigation.goto : absent ici
            "providers": {"lotusim.waypoint_follower": {
                "capabilities": ["navigation.follow_target"]}},
            "spawn": {"model": "wamv", "linear_velocity": [0.0, 5.0],
                      "angular_velocity_max": 0.05, "heading_deg": 0.0},
        }},
    })
    controller = RunController(
        scenario=scenario, graph=compile_authored_graph(scenario),
        profile=bad_profile, world_store=WorldStore(),
        white_cell=NoopWhiteCell(), transport=FakeTransport(),
        publish_event=lambda _: None)
    with pytest.raises(RunStartError, match="navigation.goto"):
        controller.start_initial_forces()
    with pytest.raises(KeyError):
        controller.supervisor("bleue", "escorte")


def test_failed_spawn_leaves_zero_supervisors():
    scenario = scenario_forces(policy="omniscient", forces={"bleue": ("escorte",)})

    class RenamingTransport(FakeTransport):
        def spawn_vessel(self, vessel, init_pos, model, linear_velocity,
                         angular_velocity_max, heading_deg):
            super().spawn_vessel(vessel, init_pos, model, linear_velocity,
                                 angular_velocity_max, heading_deg)
            return vessel + "_renamed"  # nom canonique ≠ demandé

    controller = RunController(
        scenario=scenario, graph=compile_authored_graph(scenario),
        profile=profile_for_scenario(scenario), world_store=WorldStore(),
        white_cell=NoopWhiteCell(), transport=RenamingTransport(),
        publish_event=lambda _: None)
    with pytest.raises(RunStartError):
        controller.start_initial_forces()
    with pytest.raises(KeyError):
        controller.supervisor("bleue", "escorte")


def test_invalid_end_condition_referent_raises_before_any_supervisor():
    # Amendement post-review Task 5 : {'type':'all_in_zone','force':''} est
    # l'état PAR DÉFAUT du bouton + Condition — sans ce garde, il passe
    # save+validate puis crashe le run (conditions.evaluate → KeyError).
    scenario = scenario_forces(policy="omniscient", forces={"verte": ("cargo_1",)})
    scenario = replace(scenario, end=replace(
        scenario.end,
        success=({"type": "all_in_zone", "force": "", "zone": "sortie"},)))
    controller = controller_with(scenario)
    with pytest.raises(RunStartError, match="force"):
        controller.start_initial_forces()
    with pytest.raises(KeyError):
        controller.supervisor("verte", "cargo_1")


# ── spawn_force : force différée créée à la demande, idempotente ─────────────

def test_deferred_force_supervisors_created_only_on_spawn_force():
    controller = _ormuz_controller()
    controller.start_initial_forces()
    with pytest.raises(KeyError):
        controller.supervisor("rouge", "vedette_1")  # rouge est différée
    controller.spawn_force("rouge")
    assert controller.supervisor("rouge", "vedette_1") is not None
    assert controller.supervisor("rouge", "vedette_2") is not None
    controller.spawn_force("rouge")  # idempotent : ne lève pas


# ── stop : annulation propre, ticks neutralisés ──────────────────────────────

def test_stop_cancels_active_objectives_and_neutralizes_ticks():
    transport = FakeTransport()
    controller = _ormuz_controller(transport)
    controller.start_initial_forces()
    controller.tick(snapshot(0, {"cargo_1": (26.5498, 56.3997), "escorte": (1.26, 56.40)}))
    cargo = controller.supervisor("verte", "cargo_1")
    assert cargo.active_objective_id is not None
    controller.stop("operator")
    assert cargo.active_objective_id is None
    assert "cargo_1" in transport.stopped
    before = len(transport.waypoints)
    controller.tick(snapshot(1, {"cargo_1": (26.5498, 56.3997), "escorte": (1.26, 56.40)}))
    assert len(transport.waypoints) == before  # tick neutralisé après stop


def _ormuz_controller(transport=None):
    scenario = ormuz_scenario()
    return RunController(
        scenario=scenario, graph=compile_authored_graph(scenario),
        profile=profile_for_scenario(scenario), world_store=WorldStore(),
        white_cell=NoopWhiteCell(), transport=transport or FakeTransport(),
        publish_event=lambda _: None)


# ── Task 6 : réaction du contrôleur au verdict de la cellule blanche ──────────

def test_terminal_verdict_publishes_verdict_event_and_neutralizes_ticks():
    scenario = ormuz_scenario(timeout="PT5S")
    store = WorldStore()
    transport = FakeTransport()
    events = []
    holder = {}
    cell = WhiteCell(
        scenario, ormuz_profile(), store,
        spawn_force=lambda force: holder["c"].spawn_force(force),
        delete_vessel=transport.delete_vessel,
        publish_event=lambda _e: None,
        stop=lambda reason: holder["c"].stop(reason))
    controller = RunController(
        scenario=scenario, graph=compile_authored_graph(scenario),
        profile=ormuz_profile(), world_store=store,
        white_cell=cell, transport=transport, publish_event=events.append)
    holder["c"] = controller
    controller.start_initial_forces()
    running = snapshot(0, {"cargo_1": (26.5498, 56.3997), "escorte": (1.26, 56.40)})
    controller.tick(running)
    assert transport.waypoints  # le run tourne : des waypoints ont été émis
    assert not any(e.get("type") == "verdict" for e in events)
    controller.tick(snapshot(5.0, {"cargo_1": (26.5498, 56.3997), "escorte": (1.26, 56.40)}))
    count = len(transport.waypoints)
    verdict_event = next(e for e in events if e.get("type") == "verdict")
    assert verdict_event["verdict"] == "timed_out"
    assert "reason" in verdict_event  # raison threadée pour record_verdict (Task 7)
    assert any(e.get("type") == "run_stop" for e in events)
    controller.tick(snapshot(6.0, {"cargo_1": (26.5499, 56.3997), "escorte": (1.26, 56.40)}))
    assert len(transport.waypoints) == count  # tick neutralisé après le verdict


# ── Perte adjugée = replanification épisodique (§4.1 : « changement d'état
# observé significatif ») : sans annulation des objectifs actifs, une
# poursuite non bornée bloque à jamais la bascule de branche doctrinale
# (le repli de vedette_2 après la perte de vedette_1, constaté au rig).

def test_casualty_triggers_episodic_replan_of_active_objectives():
    controller = _ormuz_controller()
    controller.start_initial_forces()
    controller.tick(snapshot(0, {"cargo_1": (26.5498, 56.3997), "escorte": (1.26, 56.40)}))
    cargo = controller.supervisor("verte", "cargo_1")
    first = cargo.active_objective_id
    assert first is not None
    controller.tick(snapshot(1, {"cargo_1": (26.5500, 56.3997), "escorte": (1.26, 56.40)},
                             destroyed={"vedette_1"}))
    # Annulation en tete de tick puis replanification au MEME tick : le
    # superviseur repart immediatement sur un objectif frais.
    assert cargo.active_objective_id is not None
    assert cargo.active_objective_id != first


def test_preflight_purges_every_observed_vessel_declared_or_stray(monkeypatch):
    # Le préflight purge TOUT navire observé : une vedette d'un run précédent
    # (ids stables — son respawn serait invisible, rig r-000006) comme un
    # artefact d'un autre scénario (drone1 : pollution de scène constatée).
    import tsm.execution.controller as controller_mod
    from tsm.domain.scenario import Position
    monkeypatch.setattr(controller_mod, '_PURGE_TIMEOUT_S', 0.05)
    transport = FakeTransport()
    controller = _ormuz_controller(transport)
    controller._world_store.update_poses(1.0, {
        'vedette_1': Position(26.553, 56.402),
        'drone1': Position(26.570, 56.420)})
    with pytest.raises(RunStartError):
        controller.start_initial_forces()  # la fake ne retire pas les poses
    assert 'vedette_1' in transport.deleted
    assert 'drone1' in transport.deleted


def test_destroyed_agent_reads_as_unavailable_so_retreat_branch_fires():
    # vedette_1 détruite ET supprimée (plus de pose) doit rester visible de la
    # doctrine comme available=False — sinon vedette_2 repart en poursuite au
    # lieu du repli (rig r-000007).
    transport = FakeTransport()
    controller = _ormuz_controller(transport)
    controller.start_initial_forces()
    controller.spawn_force("rouge")
    controller.tick(snapshot(1, {"cargo_1": (26.5520, 56.40), "escorte": (26.5518, 56.40),
                                 "vedette_1": (26.5530, 56.4020),
                                 "vedette_2": (26.5532, 56.4030)}))
    assert controller.supervisor("rouge", "vedette_2").active_objective_id is not None
    controller.tick(snapshot(2, {"cargo_1": (26.5520, 56.40), "escorte": (26.5518, 56.40),
                                 "vedette_2": (26.5532, 56.4030)},
                             destroyed={"vedette_1"}))
    # perte adjugée → replanification même tick → goto repli_nord
    assert ("vedette_2", 26.5530, 56.4060) in transport.waypoints


def test_destroyed_agent_supervisor_never_submits_again():
    # Un agent détruit n'a plus de supervision (N2) : sans ce guard, son
    # superviseur — objectif annulé par le replan de situation — replanifie
    # et resoumet à CHAQUE tick (436 soumissions post-mortem de vedette_2 au
    # rig r-000020, depuis que la doctrine générique en fait une cible
    # légitime de l'escorte).
    controller = _ormuz_controller()
    controller.start_initial_forces()
    controller.spawn_force("rouge")
    alive = {"cargo_1": (26.5520, 56.40), "escorte": (26.5518, 56.40),
             "vedette_1": (26.5530, 56.4020), "vedette_2": (26.5532, 56.4030)}
    controller.tick(snapshot(1, alive))
    supervisor = controller.supervisor("rouge", "vedette_2")
    assert supervisor.active_objective_id is not None
    without_v2 = {k: v for k, v in alive.items() if k != "vedette_2"}
    controller.tick(snapshot(2, without_v2, destroyed={"vedette_2"}))
    assert supervisor.active_objective_id is None  # annulé, pas resoumis
    controller.tick(snapshot(3, without_v2, destroyed={"vedette_2"}))
    assert supervisor.active_objective_id is None
