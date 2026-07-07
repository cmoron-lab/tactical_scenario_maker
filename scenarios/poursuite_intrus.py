# Couvre : suivre_agent — ses deux méthodes.
# "patrouilleur" démarre à ~2.3 km de l'intrus (> seuil 0.0045°) : la 1ère
# méthode ("suivre") s'applique et le rapproche à chaque replan. Une fois à
# moins de ~500 m, la 2e méthode prend le relais automatiquement
# (rentrer_a_la_base -> naviguer_vers_base -> aller_a_position), sans
# changement de scénario — juste en laissant tourner la simulation.
AGENTS = {
    'patrouilleur': {
        'x': 1.245,
        'y': 103.735,
        'model': 'wamv',
        'heading': 0.0,
        'linear_velocities_limits': (0.0, 5.0),
        'angular_velocities_limits': 0.05,
        'conditions': {'base_location': '1.245 103.735', 'cible': 'intrus'},
        'mission': ('suivre_agent', 'patrouilleur'),
    },
    'intrus': {
        'x': 1.260,
        'y': 103.750,
        'model': 'wamv',
        'heading': 0.0,
        'linear_velocities_limits': (0.0, 5.0),
        'angular_velocities_limits': 0.05,
        'conditions': {'role': 'intruder', 'is_intruder': True},
        'mission': ('veiller', 'intrus'),
    },
}
