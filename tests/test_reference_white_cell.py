# tests/test_reference_white_cell.py
import pytest

from tests.reference_fixtures import objective, ormuz_profile, ormuz_scenario, snapshot
from tsm.domain.reference import ReferenceScenario
from tsm.domain.scenario import Position, ScenarioError
from tsm.execution.controller import RunStartError
from tsm.execution.objectives import ObjectiveStatus
from tsm.execution.white_cell import Verdict, WhiteCell, WhiteCellEvent
from tsm.execution.world import WorldStore


def _cell(scenario=None, profile=None, store=None, *, spawn_force=None,
          delete_vessel=None, publish_event=None, stop=None):
    return WhiteCell(
        scenario if scenario is not None else ormuz_scenario(),
        profile if profile is not None else ormuz_profile(),
        store if store is not None else WorldStore(),
        spawn_force=spawn_force or (lambda _: None),
        delete_vessel=delete_vessel or (lambda _: None),
        publish_event=publish_event or (lambda _: None),
        stop=stop or (lambda _: None))


# ── Step 1 : triggers (verbatim du brief) ────────────────────────────────────

def test_trigger_spawns_red_once_when_cargo_enters_chokepoint():
    spawned = []
    store = WorldStore()
    cell = WhiteCell(ormuz_scenario(), ormuz_profile(), store,
                     spawn_force=spawned.append, delete_vessel=lambda _: None,
                     publish_event=lambda _: None, stop=lambda _: None)
    cell.tick(snapshot(0, {"cargo_1": (26.5500, 56.4000)}))
    cell.tick(snapshot(1, {"cargo_1": (26.5520, 56.4000)}))
    cell.tick(snapshot(2, {"cargo_1": (26.5521, 56.4000)}))
    assert spawned == ["rouge"]


def test_end_state_uses_sim_time_and_returns_timeout_once():
    store = WorldStore()
    cell = WhiteCell(ormuz_scenario(timeout="PT10S"), ormuz_profile(), store,
                     spawn_force=lambda _: None, delete_vessel=lambda _: None,
                     publish_event=lambda _: None, stop=lambda _: None)
    assert cell.tick(snapshot(0, {})) is Verdict.PENDING
    assert cell.tick(snapshot(9.9, {})) is Verdict.PENDING
    assert cell.tick(snapshot(10.0, {})) is Verdict.TIMED_OUT


# ── Step 2 : adjudication (verbatim du brief) ────────────────────────────────

def test_adjudicated_attack_deletes_target_and_succeeds_after_duration():
    world = snapshot(0, {"escorte": (1.0, 2.0), "vedette_1": (1.0001, 2.0)})
    deleted = []
    store = WorldStore()
    store.update_poses(0, {"escorte": Position(1.0, 2.0),
                           "vedette_1": Position(1.0001, 2.0)})
    cell = WhiteCell(ormuz_scenario(), ormuz_profile(), store,
                     spawn_force=lambda _: None, delete_vessel=deleted.append,
                     publish_event=lambda _: None, stop=lambda _: None)
    accepted = cell.submit_attack(
        objective("g-000001", "escorte", "engage.attack_target",
                  {"target_agent": "vedette_1"}, deadline_sim_time_s=10), world)
    assert accepted.status is ObjectiveStatus.ACCEPTED
    assert cell.tick(snapshot(2.1, {"escorte": (1.0, 2.0), "vedette_1": (1.0001, 2.0)}))
    assert deleted == ["vedette_1"]
    assert "vedette_1" in store.snapshot().destroyed


# ── submit_attack : rejets explicites, jamais silencieux ─────────────────────

def test_attack_out_of_range_is_failed_not_deferred():
    world = snapshot(0, {"escorte": (1.0, 2.0), "vedette_1": (1.02, 2.0)})
    accepted = []
    cell = _cell(delete_vessel=accepted.append)
    update = cell.submit_attack(
        objective("g-1", "escorte", "engage.attack_target",
                  {"target_agent": "vedette_1"}), world)
    assert update.status is ObjectiveStatus.FAILED
    assert update.reason == "out_of_range"
    # Aucune complétion en attente : le rejet n'a pas armé d'adjudication.
    cell.tick(snapshot(5.0, {"escorte": (1.0, 2.0), "vedette_1": (1.02, 2.0)}))
    assert accepted == []


def test_attack_rejected_when_relation_not_hostile():
    # escorte (bleue) vise cargo_1 (verte) : bleue protège verte, aucune hostilité.
    world = snapshot(0, {"escorte": (1.0, 2.0), "cargo_1": (1.0001, 2.0)})
    cell = _cell()
    update = cell.submit_attack(
        objective("g-1", "escorte", "engage.attack_target",
                  {"target_agent": "cargo_1"}), world)
    assert update.status is ObjectiveStatus.FAILED
    assert update.reason == "relation_not_hostile"


def test_attack_missing_pose_is_failed():
    world = snapshot(0, {"escorte": (1.0, 2.0)})  # vedette_1 non observée
    cell = _cell()
    update = cell.submit_attack(
        objective("g-1", "escorte", "engage.attack_target",
                  {"target_agent": "vedette_1"}), world)
    assert update.status is ObjectiveStatus.FAILED
    assert update.reason == "missing_pose"


def test_attack_on_destroyed_target_is_failed():
    world = snapshot(0, {"escorte": (1.0, 2.0), "vedette_1": (1.0001, 2.0)},
                     destroyed={"vedette_1"})
    cell = _cell()
    update = cell.submit_attack(
        objective("g-1", "escorte", "engage.attack_target",
                  {"target_agent": "vedette_1"}), world)
    assert update.status is ObjectiveStatus.FAILED
    assert update.reason == "target_destroyed"


def test_accepted_attack_drains_a_single_succeeded_update():
    world = snapshot(0, {"escorte": (1.0, 2.0), "vedette_1": (1.0001, 2.0)})
    store = WorldStore()
    cell = _cell(store=store)
    cell.submit_attack(
        objective("g-7", "escorte", "engage.attack_target",
                  {"target_agent": "vedette_1"}), world)
    assert cell.drain_attack_updates() == []  # pas encore dû
    cell.tick(snapshot(2.0, {"escorte": (1.0, 2.0), "vedette_1": (1.0001, 2.0)}))
    drained = cell.drain_attack_updates()
    assert [(u.objective_id, u.status) for u in drained] == [
        ("g-7", ObjectiveStatus.SUCCEEDED)]
    assert cell.drain_attack_updates() == []  # file vidée


def test_cancel_attack_emits_cancelled_and_disarms_adjudication():
    world = snapshot(0, {"escorte": (1.0, 2.0), "vedette_1": (1.0001, 2.0)})
    deleted = []
    cell = _cell(delete_vessel=deleted.append)
    cell.submit_attack(
        objective("g-9", "escorte", "engage.attack_target",
                  {"target_agent": "vedette_1"}), world)
    cancelled = cell.cancel_attack("g-9", world)
    assert cancelled.status is ObjectiveStatus.CANCELLED
    cell.tick(snapshot(5.0, {"escorte": (1.0, 2.0), "vedette_1": (1.0001, 2.0)}))
    assert deleted == []  # l'adjudication a bien été désarmée


# ── Verdict : succès avant échec, terminal une seule fois ────────────────────

def _dueling_scenario() -> ReferenceScenario:
    # success et failure portent la MÊME condition : quand elle est vraie, la
    # règle "succès avant échec" doit trancher SUCCEEDED.
    return ReferenceScenario.from_dict({
        "version": 2, "information_policy": "omniscient",
        "forces": {"bleue": {"agents": ["a"]}},
        "relations": [], "triggers": [],
        "zones": {"z": {"center": {"lat": 1.0, "lon": 2.0}, "radius_deg": 0.001}},
        "agents": {"a": {"platform": "surface_vessel",
                         "position": {"lat": 1.0, "lon": 2.0},
                         "mission": {"task": "transiter_vers_zone", "args": ["a", "z"]},
                         "conditions": {}}},
        "end": {"success": [{"type": "in_zone", "agent": "a", "zone": "z"}],
                "failure": [{"type": "in_zone", "agent": "a", "zone": "z"}],
                "timeout": "PT60S"},
    })


def test_success_is_evaluated_before_failure():
    cell = _cell(scenario=_dueling_scenario())
    assert cell.tick(snapshot(0, {"a": (1.0, 2.0)})) is Verdict.SUCCEEDED


def test_verdict_is_terminal_and_triggers_stop_after_it():
    spawned = []
    cell = _cell(scenario=ormuz_scenario(timeout="PT5S"), spawn_force=spawned.append)
    cell.tick(snapshot(0, {}))
    assert cell.tick(snapshot(5.0, {})) is Verdict.TIMED_OUT
    # Une fois terminal : le verdict est figé et les triggers ne s'arment plus.
    assert cell.tick(snapshot(6.0, {"cargo_1": (26.5520, 56.4000)})) is Verdict.TIMED_OUT
    assert spawned == []


def test_empty_success_list_never_auto_succeeds():
    scenario = ormuz_scenario()
    # Scénario dont la liste de succès est vide : pas d'auto-succès au tick 0.
    scenario = ReferenceScenario.from_dict({
        **scenario.to_dict(),
        "end": {"success": [], "failure": [], "timeout": "PT60S"},
    })
    cell = _cell(scenario=scenario)
    assert cell.tick(snapshot(0, {})) is Verdict.PENDING


# ── Injections : spawn indisponible → verdict FAILED(spawn_unavailable) ───────

def test_spawn_unavailable_forces_failed_verdict():
    events = []

    def failing_spawn(_force):
        raise RunStartError("service de spawn indisponible")

    cell = _cell(spawn_force=failing_spawn, publish_event=events.append)
    cell.tick(snapshot(0, {"cargo_1": (26.5500, 56.4000)}))  # hors passe
    verdict = cell.tick(snapshot(1, {"cargo_1": (26.5520, 56.4000)}))  # trigger
    assert verdict is Verdict.FAILED
    assert cell.verdict_reason == "spawn_unavailable"  # exposé au contrôleur
    verdict_events = [e for e in events if e.kind == "verdict"]
    assert verdict_events[-1].fields["reason"] == "spawn_unavailable"


def test_same_tick_verdict_freezes_adjudication_no_zombie_delete():
    # Une attaque due au tick T où une injection rate : le verdict FAILED gèle
    # l'arbitrage — aucun delete_vessel, aucun SUCCEEDED sur un run déjà perdu.
    deleted = []

    def failing_spawn(_force):
        raise RunStartError("service de spawn indisponible")

    cell = _cell(spawn_force=failing_spawn, delete_vessel=deleted.append)
    cell.submit_attack(
        objective("g-1", "escorte", "engage.attack_target",
                  {"target_agent": "vedette_1"}),
        snapshot(0, {"escorte": (1.0, 2.0), "vedette_1": (1.0001, 2.0)}))
    # t=2.5 : attaque due (PT2S) ET cargo_1 dans la passe → trigger → spawn rate.
    verdict = cell.tick(snapshot(2.5, {"escorte": (1.0, 2.0),
                                       "vedette_1": (1.0001, 2.0),
                                       "cargo_1": (26.5520, 56.4000)}))
    assert verdict is Verdict.FAILED
    assert deleted == []
    assert cell.drain_attack_updates() == []


# ── Actions de trigger inconnues : échec sonore, pas de skip silencieux ───────

def test_unknown_trigger_action_raises_scenario_error():
    scenario = ReferenceScenario.from_dict({
        "version": 2, "information_policy": "omniscient",
        "forces": {"bleue": {"agents": ["a"]}}, "relations": [],
        "zones": {"z": {"center": {"lat": 1.0, "lon": 2.0}, "radius_deg": 0.001}},
        "agents": {"a": {"platform": "surface_vessel",
                         "position": {"lat": 1.0, "lon": 2.0},
                         "mission": {"task": "transiter_vers_zone", "args": ["a", "z"]},
                         "conditions": {}}},
        "triggers": [{"id": "t", "when": {"type": "in_zone", "agent": "a", "zone": "z"},
                      "do": [{"type": "detonate"}]}],
        "end": {"success": [{"type": "in_zone", "agent": "a", "zone": "z"}],
                "failure": [], "timeout": "PT60S"},
    })
    cell = _cell(scenario=scenario)
    with pytest.raises(ScenarioError):
        cell.tick(snapshot(0, {"a": (1.0, 2.0)}))


def test_publish_emits_whitecellevent_instances():
    events = []
    cell = _cell(publish_event=events.append)
    cell.tick(snapshot(0, {"cargo_1": (26.5500, 56.4000)}))
    cell.tick(snapshot(1, {"cargo_1": (26.5520, 56.4000)}))  # trigger fires
    assert any(isinstance(e, WhiteCellEvent) and e.kind == "trigger_fired"
               for e in events)
