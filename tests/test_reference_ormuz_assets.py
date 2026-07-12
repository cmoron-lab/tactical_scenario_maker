# tests/test_reference_ormuz_assets.py
"""Artefacts de référence de l'Escorte d'Ormuz : scénario v2 + profil
cinématique + doctrine locale (KB, méthodes, actions v3)."""
from tsm.domain import doctrine
from tsm.domain.profile import load_profile
from tsm.domain.reference import load_reference_scenario
from tsm.execution.actions import attack_target, follow_target, goto
from tsm.planning import methods
from tsm.planning.planner import Planner
from tsm.vendor import gtpyhop


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


def test_repli_apres_perte_m_delegates_to_poursuivre_cargo_while_vedette_1_lives():
    # poursuivre_cargo est déclaratif (doctrine/knowledge_base.json) : la
    # méthode Python délègue la poursuite à la tâche KB, elle n'émet pas la
    # primitive elle-même — la décomposition complète est couverte par le
    # test Planner ci-dessous.
    state = _state({'vedette_1': {'available': True}, 'cargo_1': {'available': True}})
    plan = methods.repli_apres_perte_m(state, 'vedette_2')
    assert plan == [('poursuivre_cargo', 'vedette_2')]


# ── Garde de régression sur le câblage réel : register_builtin (méthodes
# Python) + register_kb (poursuivre_cargo déclaratif) + declare_actions
# (primitives pures) doivent aboutir aux tuples primitifs exacts via le
# vrai Planner, pas seulement via les fonctions appelées à la main.

def test_find_plan_produces_primitive_tuples_through_real_registration():
    planner = Planner(doctrine.load(), actions=(goto, follow_target, attack_target))
    state = gtpyhop.State('ormuz')
    state.agents = {
        'cargo_1': {'available': True},
        'escorte': {'available': True},
        'vedette_1': {'available': True},
        'vedette_2': {'available': True},
    }
    # Déclaratif (KB) : poursuivre_cargo -> follow_target cargo_1
    assert planner.find_plan(state, ('poursuivre_cargo', 'vedette_1')) == \
        [('follow_target', 'vedette_1', 'cargo_1', None)]
    # Python (register_builtin) : escorter_convoi -> follow puis attack
    assert planner.find_plan(state, ('escorter_convoi', 'escorte')) == [
        ('follow_target', 'escorte', 'vedette_1', 0.00045),
        ('attack_target', 'escorte', 'vedette_1'),
    ]
    # Chaîne mixte Python -> KB : repli délègue à poursuivre_cargo
    assert planner.find_plan(state, ('repli_apres_perte', 'vedette_2')) == \
        [('follow_target', 'vedette_2', 'cargo_1', None)]
    # cargo_1 détruit : la précondition agent_present de la KB rend
    # poursuivre_cargo inapplicable
    state.agents['cargo_1']['available'] = False
    assert planner.find_plan(state, ('poursuivre_cargo', 'vedette_1')) is False


# ── Poste tenu : un suivi borné déjà satisfait se décompose en [], sinon le
# superviseur (qui ne soumet que plan[0] et replanifie après chaque objectif
# terminal) resoumettrait follow_target à l'infini et l'attaque
# d'escorter_convoi ne serait jamais soumise (livelock).

def _planner_state(positions):
    state = gtpyhop.State('ormuz_pos')
    state.agents = {name: {'available': True, 'pos': {'lat': lat, 'lon': lon}}
                    for name, (lat, lon) in positions.items()}
    return state


def test_escorter_convoi_at_station_decomposes_to_attack_only():
    planner = Planner(doctrine.load(), actions=(goto, follow_target, attack_target))
    # 0.0001 <= stop_distance 0.00045 : le suivi est déjà satisfait
    state = _planner_state({'escorte': (1.2631, 103.7520), 'vedette_1': (1.2630, 103.7520)})
    assert planner.find_plan(state, ('escorter_convoi', 'escorte')) == \
        [('attack_target', 'escorte', 'vedette_1')]


def test_escorter_convoi_far_from_threat_still_follows_first():
    planner = Planner(doctrine.load(), actions=(goto, follow_target, attack_target))
    state = _planner_state({'escorte': (1.2600, 103.7500), 'vedette_1': (1.2630, 103.7520)})
    plan = planner.find_plan(state, ('escorter_convoi', 'escorte'))
    assert plan[0] == ('follow_target', 'escorte', 'vedette_1', 0.00045)


def test_follow_target_m_without_stop_distance_never_self_satisfies():
    # Poursuite pure (poursuivre_cargo) : même à distance nulle, le suivi
    # reste émis — seul un suivi borné (stop_distance) peut être « tenu ».
    state = _state({
        'vedette_2': {'available': True, 'pos': {'lat': 1.2630, 'lon': 103.7520}},
        'cargo_1': {'available': True, 'pos': {'lat': 1.2630, 'lon': 103.7520}},
    })
    plan = methods.follow_target_m(state, 'vedette_2', 'cargo_1')
    assert plan == [('follow_target', 'vedette_2', 'cargo_1', None)]


# ── Poste d'escorte : sans menace visible, escorter_convoi tient la station
# sur le convoi (§8.2 « station de l'escorte ») — sinon l'escorte reste
# immobile pendant le transit et l'interception devient une chasse arrière
# perdue (vedette 8 m/s > escorte 6 m/s, constaté au rig, run r-000004).

def test_escorter_convoi_holds_station_on_convoy_when_no_threat_in_sight():
    # Station NON bornée : une station plus serrée que le rayon de giration
    # (v/om = 120 m) ne devient jamais terminale (rig r-000005) — c'est la
    # replanification sur changement de situation qui fait basculer.
    state = _state({'cargo_1': {'available': True,
                                'pos': {'lat': 1.2620, 'lon': 103.75}},
                    'escorte': {'available': True,
                                'pos': {'lat': 1.2600, 'lon': 103.75}}})
    plan = methods.escorter_convoi_m(state, 'escorte')
    assert plan == [('follow_target', 'escorte', 'cargo_1', None)]


def test_escorter_convoi_station_never_self_satisfies_even_at_contact():
    state = _state({'cargo_1': {'available': True,
                                'pos': {'lat': 1.2600, 'lon': 103.75}},
                    'escorte': {'available': True,
                                'pos': {'lat': 1.2600, 'lon': 103.75}}})
    plan = methods.escorter_convoi_m(state, 'escorte')
    assert plan == [('follow_target', 'escorte', 'cargo_1', None)]


def test_escorter_convoi_returns_to_station_after_threat_destroyed():
    state = _state({'vedette_1': {'available': False},
                    'cargo_1': {'available': True,
                                'pos': {'lat': 1.2650, 'lon': 103.75}},
                    'escorte': {'available': True,
                                'pos': {'lat': 1.2630, 'lon': 103.7520}}})
    plan = methods.escorter_convoi_m(state, 'escorte')
    assert plan == [('follow_target', 'escorte', 'cargo_1', None)]


def test_escorter_convoi_inapplicable_without_threat_nor_convoy():
    assert methods.escorter_convoi_m(_state({}), 'escorte') is False
