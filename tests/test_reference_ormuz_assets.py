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

def _apply_facts(st):
    # Zones, forces et relations du Scenario Request réel — source unique,
    # injectées dans l'état comme le fait le superviseur (state.zones /
    # state.forces / state.relations, cf. controller._state_from_view).
    scenario = load_reference_scenario('escorte_ormuz')
    st.zones = {n: (z.lat, z.lon, z.radius_deg) for n, z in scenario.zones.items()}
    st.forces = {n: f.agents for n, f in scenario.forces.items()}
    st.relations = tuple((r.source, r.targets, r.attitude) for r in scenario.relations)
    return st


def _state(agents):
    st = type('State', (), {})()
    st.agents = agents
    return _apply_facts(st)


def test_goto_m_resolves_named_zone_to_position_and_radius():
    plan = methods.goto_m(_state({}), 'cargo_1', 'sortie_ouest')
    assert plan == [('goto', 'cargo_1', (26.5570, 56.4000), 0.00015)]


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


def test_repli_apres_perte_m_retreats_once_own_force_takes_a_loss():
    # « Perte » dérivée de state.forces : vedette_1 est de la MÊME force que
    # vedette_2 (rouge) — sa destruction déclenche le repli vers la zone
    # passée en argument de mission.
    state = _state({'vedette_1': {'available': False}, 'cargo_1': {'available': True}})
    plan = methods.repli_apres_perte_m(state, 'vedette_2', 'repli_nord')
    assert plan == [('goto', 'vedette_2', (26.5530, 56.4060), 0.00015)]


def test_repli_apres_perte_m_pursues_nearest_hostile_while_force_intact():
    # Branche nominale dérivée des relations : rouge est hostile à bleue et
    # verte — cargo_1 est le seul membre vivant observé, il est poursuivi.
    state = _state({'vedette_1': {'available': True}, 'cargo_1': {'available': True}})
    plan = methods.repli_apres_perte_m(state, 'vedette_2', 'repli_nord')
    assert plan == [('follow_target', 'vedette_2', 'cargo_1', None)]


# ── Garde de régression sur le câblage réel : register_builtin (méthodes
# Python) + declare_actions (primitives pures) doivent aboutir aux tuples
# primitifs exacts via le vrai Planner, pas seulement via les fonctions
# appelées à la main.

def test_find_plan_produces_primitive_tuples_through_real_registration():
    planner = Planner(doctrine.load(), actions=(goto, follow_target, attack_target))
    state = _apply_facts(gtpyhop.State('ormuz'))
    state.agents = {
        'cargo_1': {'available': True, 'pos': {'lat': 26.5520, 'lon': 56.4000}},
        'escorte': {'available': True, 'pos': {'lat': 26.5518, 'lon': 56.4000}},
        'vedette_1': {'available': True, 'pos': {'lat': 26.5530, 'lon': 56.4020}},
        'vedette_2': {'available': True, 'pos': {'lat': 26.5532, 'lon': 56.4030}},
    }
    # poursuivre : cible désignée par la mission (référent du scénario)
    assert planner.find_plan(state, ('poursuivre', 'vedette_1', 'cargo_1')) == \
        [('follow_target', 'vedette_1', 'cargo_1', None)]
    # escorter_convoi : menace = plus proche hostile au protégé (relations)
    assert planner.find_plan(state, ('escorter_convoi', 'escorte')) == [
        ('follow_target', 'escorte', 'vedette_1', 0.00045),
        ('attack_target', 'escorte', 'vedette_1'),
    ]
    # repli_apres_perte nominal : poursuite du plus proche hostile (cargo_1
    # est plus près de vedette_2 que l'escorte)
    assert planner.find_plan(state, ('repli_apres_perte', 'vedette_2', 'repli_nord')) == \
        [('follow_target', 'vedette_2', 'cargo_1', None)]
    # cible détruite : poursuivre devient inapplicable
    state.agents['cargo_1']['available'] = False
    assert planner.find_plan(state, ('poursuivre', 'vedette_1', 'cargo_1')) is False


# ── Poste tenu : un suivi borné déjà satisfait se décompose en [], sinon le
# superviseur (qui ne soumet que plan[0] et replanifie après chaque objectif
# terminal) resoumettrait follow_target à l'infini et l'attaque
# d'escorter_convoi ne serait jamais soumise (livelock).

def _planner_state(positions):
    state = _apply_facts(gtpyhop.State('ormuz_pos'))
    state.agents = {name: {'available': True, 'pos': {'lat': lat, 'lon': lon}}
                    for name, (lat, lon) in positions.items()}
    return state


def test_escorter_convoi_at_station_decomposes_to_attack_only():
    planner = Planner(doctrine.load(), actions=(goto, follow_target, attack_target))
    # 0.0001 <= stop_distance 0.00045 : le suivi est déjà satisfait
    state = _planner_state({'escorte': (26.5531, 56.4020), 'vedette_1': (26.5530, 56.4020)})
    assert planner.find_plan(state, ('escorter_convoi', 'escorte')) == \
        [('attack_target', 'escorte', 'vedette_1')]


def test_escorter_convoi_far_from_threat_still_follows_first():
    planner = Planner(doctrine.load(), actions=(goto, follow_target, attack_target))
    state = _planner_state({'escorte': (26.5500, 56.4000), 'vedette_1': (26.5530, 56.4020)})
    plan = planner.find_plan(state, ('escorter_convoi', 'escorte'))
    assert plan[0] == ('follow_target', 'escorte', 'vedette_1', 0.00045)


def test_follow_target_m_without_stop_distance_never_self_satisfies():
    # Poursuite pure (poursuivre) : même à distance nulle, le suivi
    # reste émis — seul un suivi borné (stop_distance) peut être « tenu ».
    state = _state({
        'vedette_2': {'available': True, 'pos': {'lat': 26.5530, 'lon': 56.4020}},
        'cargo_1': {'available': True, 'pos': {'lat': 26.5530, 'lon': 56.4020}},
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
                                'pos': {'lat': 26.5520, 'lon': 56.40}},
                    'escorte': {'available': True,
                                'pos': {'lat': 26.5500, 'lon': 56.40}}})
    plan = methods.escorter_convoi_m(state, 'escorte')
    assert plan == [('follow_target', 'escorte', 'cargo_1', None)]


def test_escorter_convoi_station_never_self_satisfies_even_at_contact():
    state = _state({'cargo_1': {'available': True,
                                'pos': {'lat': 26.5500, 'lon': 56.40}},
                    'escorte': {'available': True,
                                'pos': {'lat': 26.5500, 'lon': 56.40}}})
    plan = methods.escorter_convoi_m(state, 'escorte')
    assert plan == [('follow_target', 'escorte', 'cargo_1', None)]


def test_escorter_convoi_returns_to_station_after_threat_destroyed():
    state = _state({'vedette_1': {'available': False},
                    'cargo_1': {'available': True,
                                'pos': {'lat': 26.5550, 'lon': 56.40}},
                    'escorte': {'available': True,
                                'pos': {'lat': 26.5530, 'lon': 56.4020}}})
    plan = methods.escorter_convoi_m(state, 'escorte')
    assert plan == [('follow_target', 'escorte', 'cargo_1', None)]


def test_escorter_convoi_inapplicable_without_threat_nor_convoy():
    assert methods.escorter_convoi_m(_state({}), 'escorte') is False


def test_goto_self_satisfies_once_inside_the_zone():
    # Arrivé au point de repli, un goto réémis à chaque tick spammerait la
    # timeline à 5 Hz (rig r-000008) : zone atteinte ⇒ décomposition vide.
    state = _state({'vedette_2': {'available': True,
                                  'pos': {'lat': 26.5530, 'lon': 56.4060}}})
    assert methods.goto_m(state, 'vedette_2', 'repli_nord') == []
    state = _state({'vedette_2': {'available': True,
                                  'pos': {'lat': 26.5532, 'lon': 56.4030}}})
    assert methods.goto_m(state, 'vedette_2', 'repli_nord') == [
        ('goto', 'vedette_2', (26.5530, 56.4060), 0.00015)]
