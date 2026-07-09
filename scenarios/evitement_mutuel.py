# Couvre : eviter — 2 agents ORDINAIRES (pas d'intrus) qui s'évitent
# mutuellement. Ils démarrent à ~2.3 km l'un de l'autre (> seuil 0.01°) et
# s'approchent ; une fois à moins de ~1 km, la distance devient symétriquement
# < seuil pour les DEUX à la fois, donc les deux font demi-tour vers leur
# base au même moment. Une fois rentrés, la distance repasse au-dessus du
# seuil et ils se rapprochent de nouveau — comportement cyclique attendu
# d'une règle réévaluée en continu plutôt qu'une action ponctuelle.
#
# conditions.cible est explicite (chacun pointe sur l'autre) plutôt que de
# compter sur la résolution automatique "__cible__" -> "__any__" (agent non-
# zone le plus proche) — sans ambiguïté ici avec seulement 2 agents, mais
# suit la même convention que les autres scénarios de ce dossier.
AGENTS = {
    'agent1': {
        'x': 1.245,
        'y': 103.735,
        'model': 'wamv',
        'heading': 0.0,
        'linear_velocities_limits': (0.0, 5.0),
        'angular_velocities_limits': 0.05,
        'conditions': {'base_location': '1.245 103.735', 'cible': 'agent2'},
        'mission': ('eviter', 'agent1'),
    },
    'agent2': {
        'x': 1.260,
        'y': 103.750,
        'model': 'wamv',
        'heading': 0.0,
        'linear_velocities_limits': (0.0, 5.0),
        'angular_velocities_limits': 0.05,
        'conditions': {'base_location': '1.260 103.750', 'cible': 'agent1'},
        'mission': ('eviter', 'agent2'),
    },
}
