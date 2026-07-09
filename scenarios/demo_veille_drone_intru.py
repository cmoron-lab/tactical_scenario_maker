# Démo compacte (agents proches, ~1km d'écart) pour voir l'effet tout de
# suite : 'veilleur' reste passif ("veiller"), 'drone1' est positionné juste
# à côté de lui et suit directement l'intrus ("suivre_agent"), 'intrus' se
# déplace en ligne droite vers une destination fixe ("aller_a_position").
# Distance initiale drone1 <-> intrus (~950m) > seuil de capture de
# "suivre_agent" (0.0045° ~ 500m), donc le drone poursuit réellement avant
# de rattraper — pas déjà "à portée" dès le départ.
AGENTS = {
    'veilleur': {
        'x': 1.260,
        'y': 103.750,
        'model': 'wamv',
        'heading': 0.0,
        'linear_velocities_limits': (0.0, 5.0),
        'angular_velocities_limits': 0.05,
        'conditions': {'role': 'patrol', 'base_location': '1.260 103.750'},
        'mission': ('veiller', 'veilleur'),
    },
    'drone1': {
        'x': 1.2603,
        'y': 103.7503,
        'model': 'x500',
        'heading': 0.0,
        'linear_velocities_limits': (0.0, 8.0),
        'angular_velocities_limits': 0.05,
        'conditions': {'role': 'drone', 'base_location': '1.2603 103.7503', 'cible': 'intrus'},
        'mission': ('suivre_agent', 'drone1'),
    },
    'intrus': {
        'x': 1.266,
        'y': 103.756,
        'model': 'wamv',
        'heading': 45.0,
        'linear_velocities_limits': (0.0, 4.0),
        'angular_velocities_limits': 0.05,
        'conditions': {'role': 'intruder', 'is_intruder': True, 'base_location': '1.266 103.756'},
        'mission': ('aller_a_position', 'intrus', (1.280, 103.770)),
    },
}
