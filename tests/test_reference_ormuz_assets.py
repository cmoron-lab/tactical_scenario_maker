# tests/test_reference_ormuz_assets.py
"""Artefacts de référence de l'Escorte d'Ormuz : scénario v2 + profil
cinématique + doctrine locale (KB, méthodes, actions v3)."""
from tsm.domain.profile import load_profile
from tsm.domain.reference import load_reference_scenario
from tsm.planning import methods


def test_ormuz_has_three_forces_and_deferred_red_force():
    scenario = load_reference_scenario("escorte_ormuz")
    assert scenario.forces["rouge"].spawn == "deferred"
    assert set(scenario.forces) == {"bleue", "rouge", "verte"}


def test_ormuz_profile_declares_only_selected_backends():
    profile = load_profile("kinematic-ormuz")
    assert profile.agents["escorte"].fidelity == "kinematic"
    assert "navigation.follow_target" in profile.agents["vedette_1"].capabilities
    assert "engage.attack_target" in profile.agents["escorte"].capabilities


# ── Doctrine v3 : les feuilles émettent exactement les tuples primitifs
# attendus par le superviseur (Task 5) — pas de couverture GTPyhop end-to-end
# ici (le state v3 n'existe pas encore), juste les fonctions elles-mêmes.

def _state(agents):
    st = type('State', (), {})()
    st.agents = agents
    return st


def test_goto_m_resolves_named_zone_to_position_and_radius():
    plan = methods.goto_m(_state({}), 'cargo_1', 'sortie_ouest')
    assert plan == [('goto', 'cargo_1', (1.2670, 103.7500), 0.00015)]


def test_goto_m_unknown_zone_is_inapplicable():
    assert methods.goto_m(_state({}), 'cargo_1', 'zone_inconnue') is False


def test_follow_target_m_emits_primitive_tuple():
    state = _state({'cargo_1': {'available': True}})
    plan = methods.follow_target_m(state, 'vedette_1', 'cargo_1')
    assert plan == [('follow_target', 'vedette_1', 'cargo_1', None)]


def test_follow_target_m_inapplicable_when_target_destroyed():
    state = _state({'cargo_1': {'available': False}})
    assert methods.follow_target_m(state, 'vedette_1', 'cargo_1') is False


def test_escorter_convoi_m_chains_follow_then_attack():
    state = _state({'vedette_1': {'available': True}})
    plan = methods.escorter_convoi_m(state, 'escorte')
    assert plan == [
        ('follow_target', 'escorte', 'vedette_1', 0.00045),
        ('attack_target', 'escorte', 'vedette_1'),
    ]


def test_repli_apres_perte_m_retreats_once_vedette_1_destroyed():
    state = _state({'vedette_1': {'available': False}, 'cargo_1': {'available': True}})
    plan = methods.repli_apres_perte_m(state, 'vedette_2')
    assert plan == [('goto', 'vedette_2', (1.2630, 103.7560), 0.00015)]


def test_repli_apres_perte_m_pursues_cargo_while_vedette_1_lives():
    state = _state({'vedette_1': {'available': True}, 'cargo_1': {'available': True}})
    plan = methods.repli_apres_perte_m(state, 'vedette_2')
    assert plan == [('follow_target', 'vedette_2', 'cargo_1', None)]
