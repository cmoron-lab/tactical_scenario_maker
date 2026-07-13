# tests/test_reference_e2e_memory.py
"""Chaîne v3 complète (schéma → profil → WorldStore → cellule blanche →
contrôleur → superviseurs → providers) prouvée en mémoire, sans ROS : le
harnais InMemoryRuntimeHarness fait avancer le monde par snapshots injectés.

Le scénario nominal et ses variantes négatives sont verbatim du brief Task 8.
La séparation des vues de force et le refus de spawn sont couverts par
tests/test_reference_controller.py (test_force_view_hides_unobserved_agents…,
test_failed_spawn_leaves_zero_supervisors) — pas dupliqués ici.
"""
import pytest

from tests.reference_fixtures import in_memory_runtime
from tsm.execution.controller import RunStartError
from tsm.execution.white_cell import Verdict


def test_ormuz_full_chain_reaches_success_verdict():
    runtime, fake = in_memory_runtime("escorte_ormuz", "kinematic-ormuz")
    runtime.start()
    runtime.tick(fake.snapshot(0, {"cargo_1": (26.5500, 56.4000),
                                   "escorte": (26.5498, 56.3997)}))
    runtime.tick(fake.snapshot(10, {"cargo_1": (26.5520, 56.4000),
                                    "escorte": (26.5515, 56.4000)}))
    assert "rouge" in fake.spawned_forces
    # L'interception se joue DANS l'enveloppe d'engagement : escorte à
    # 0.0011 du cargo (< ENGAGE_ENVELOPE_DEG), au contact de vedette_1.
    runtime.tick(fake.snapshot(20, {"cargo_1": (26.5540, 56.4000),
                                    "escorte": (26.5544, 56.4010),
                                    "vedette_1": (26.5545, 56.4010),
                                    "vedette_2": (26.5532, 56.4030)}))
    runtime.tick(fake.snapshot(23, {"cargo_1": (26.5569, 56.4000),
                                    "escorte": (26.5544, 56.4010),
                                    "vedette_2": (26.5532, 56.4030)}))
    assert "vedette_1" in fake.deleted
    runtime.tick(fake.snapshot(30, {"cargo_1": (26.5570, 56.4000),
                                    "escorte": (26.5544, 56.4010),
                                    "vedette_2": (26.5530, 56.4060)}))
    assert runtime.verdict is Verdict.SUCCEEDED
    # L'échappée de vedette_2 fait partie du scénario de référence : au
    # moment du replan (perte de vedette_1), le cargo a filé — l'escorte est
    # hors enveloppe, elle revient au poste au lieu de chasser le fuyard.
    assert "vedette_2" not in fake.deleted


def test_ormuz_fails_when_cargo_is_destroyed():
    runtime, fake = in_memory_runtime("escorte_ormuz", "kinematic-ormuz")
    runtime.start()
    fake.destroy("cargo_1")
    runtime.tick(fake.snapshot(4, {"escorte": (26.5498, 56.3997)}))
    assert runtime.verdict is Verdict.FAILED


def test_ormuz_times_out_without_progress():
    runtime, fake = in_memory_runtime("escorte_ormuz", "kinematic-ormuz")
    runtime.start()
    runtime.tick(fake.snapshot(240, {"cargo_1": (26.5500, 56.4000),
                                     "escorte": (26.5498, 56.3997)}))
    assert runtime.verdict is Verdict.TIMED_OUT


def test_incompatible_profile_fails_before_any_spawn():
    runtime, fake = in_memory_runtime(
        "escorte_ormuz", "kinematic-ormuz",
        remove_capability=("vedette_1", "navigation.follow_target"))
    with pytest.raises(RunStartError, match="navigation.follow_target"):
        runtime.start()
    assert fake.spawned_agents == []
