# tests/test_doctrine_generique.py
"""La doctrine v3 est indépendante du scénario (P2, lsga-architecture-v3.md) :
les mêmes tâches escortent N'IMPORTE QUEL convoi. Aucun nom de l'Escorte
d'Ormuz ici — protégé, menace et perte se dérivent de state.forces /
state.relations, les référents désignés (cible, zone) passent en argument
de mission."""
from tsm.planning import methods


def _state(agents, forces, relations, zones=None):
    st = type('State', (), {})()
    st.agents = agents
    st.forces = forces
    st.relations = relations
    st.zones = zones or {}
    return st


_FORCES = {
    'coalition': ('fregate',),
    'commerce': ('tanker_a', 'tanker_b'),
    'corsaires': ('skiff_1', 'skiff_2'),
}
_RELATIONS = (
    ('corsaires', ('coalition', 'commerce'), 'hostile'),
    ('coalition', ('commerce',), 'protect'),
)


def test_escorte_intercepte_la_menace_la_plus_proche_du_scenario_renomme():
    state = _state({
        'fregate': {'available': True, 'pos': {'lat': 10.0, 'lon': 20.0}},
        'tanker_a': {'available': True, 'pos': {'lat': 10.001, 'lon': 20.0}},
        'skiff_1': {'available': True, 'pos': {'lat': 10.002, 'lon': 20.0}},
        'skiff_2': {'available': True, 'pos': {'lat': 10.010, 'lon': 20.0}},
    }, _FORCES, _RELATIONS)
    # La poursuite porte l'enveloppe : ancre = protégé le plus proche.
    assert methods.escorter_convoi_m(state, 'fregate') == [
        ('follow_target', 'fregate', 'skiff_1', methods.ENGAGE_STANDOFF_DEG,
         ('tanker_a', methods.ENGAGE_ENVELOPE_DEG)),
        ('attack_target', 'fregate', 'skiff_1'),
    ]


def test_escorte_hors_enveloppe_revient_au_poste_au_lieu_de_chasser():
    # L'escorte ne s'éloigne pas de sa charge : au-delà de l'enveloppe
    # d'engagement (distance escorte↔protégé), une menace visible n'est
    # plus chassée — retour au poste.
    state = _state({
        'fregate': {'available': True, 'pos': {'lat': 10.002, 'lon': 20.0}},
        'tanker_a': {'available': True, 'pos': {'lat': 10.0, 'lon': 20.0}},
        'skiff_1': {'available': True, 'pos': {'lat': 10.003, 'lon': 20.0}},
    }, _FORCES, _RELATIONS)
    assert methods.escorter_convoi_m(state, 'fregate') == [
        ('follow_target', 'fregate', 'tanker_a', None)]


def test_escorte_tient_le_poste_sur_le_protege_le_plus_proche_sans_menace():
    state = _state({
        'fregate': {'available': True, 'pos': {'lat': 10.0, 'lon': 20.0}},
        'tanker_a': {'available': True, 'pos': {'lat': 10.001, 'lon': 20.0}},
        'tanker_b': {'available': True, 'pos': {'lat': 10.005, 'lon': 20.0}},
    }, _FORCES, _RELATIONS)
    assert methods.escorter_convoi_m(state, 'fregate') == [
        ('follow_target', 'fregate', 'tanker_a', None)]


def test_escorte_ignore_un_hostile_qui_ne_vise_pas_son_protege():
    # skiff hostile à la seule coalition : pas une menace pour le convoi —
    # l'escorte reste au poste (les relations disent QUI menace QUI).
    relations = (('corsaires', ('coalition',), 'hostile'),
                 ('coalition', ('commerce',), 'protect'))
    state = _state({
        'fregate': {'available': True, 'pos': {'lat': 10.0, 'lon': 20.0}},
        'tanker_a': {'available': True, 'pos': {'lat': 10.001, 'lon': 20.0}},
        'skiff_1': {'available': True, 'pos': {'lat': 10.002, 'lon': 20.0}},
    }, _FORCES, relations)
    assert methods.escorter_convoi_m(state, 'fregate') == [
        ('follow_target', 'fregate', 'tanker_a', None)]


def test_repli_se_declenche_sur_une_perte_dans_sa_propre_force():
    zones = {'refuge': (11.0, 21.0, 0.0002)}
    state = _state({
        'skiff_1': {'available': False},
        'skiff_2': {'available': True, 'pos': {'lat': 10.010, 'lon': 20.0}},
        'tanker_a': {'available': True, 'pos': {'lat': 10.001, 'lon': 20.0}},
    }, _FORCES, _RELATIONS, zones)
    assert methods.repli_apres_perte_m(state, 'skiff_2', 'refuge') == [
        ('goto', 'skiff_2', (11.0, 21.0), 0.0002)]


def test_repli_ignore_une_perte_dans_une_force_adverse():
    zones = {'refuge': (11.0, 21.0, 0.0002)}
    state = _state({
        'fregate': {'available': False},  # perte ADVERSE : pas un repli
        'skiff_2': {'available': True, 'pos': {'lat': 10.010, 'lon': 20.0}},
        'tanker_a': {'available': True, 'pos': {'lat': 10.001, 'lon': 20.0}},
    }, _FORCES, _RELATIONS, zones)
    assert methods.repli_apres_perte_m(state, 'skiff_2', 'refuge') == [
        ('follow_target', 'skiff_2', 'tanker_a', None)]


def test_poursuivre_prend_sa_cible_en_argument_de_mission():
    state = _state({'tanker_b': {'available': True}}, _FORCES, _RELATIONS)
    assert methods.poursuivre_m(state, 'skiff_1', 'tanker_b') == [
        ('follow_target', 'skiff_1', 'tanker_b', None)]


def test_doctrine_sans_forces_ni_relations_reste_inapplicable_pas_de_crash():
    # État legacy (v1) sans faits doctrinaux : les tâches v3 sont simplement
    # inapplicables — jamais d'AttributeError ni de nom Ormuz par défaut.
    st = type('State', (), {})()
    st.agents = {'x': {'available': True, 'pos': {'lat': 0.0, 'lon': 0.0}}}
    assert methods.escorter_convoi_m(st, 'x') is False
    assert methods.repli_apres_perte_m(st, 'x', 'nulle_part') is False
