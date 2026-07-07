# Couvre : surveiller_zone assignée directement à DEUX drones indépendants
# qui surveillent la même zone en parallèle (redondance) — pas de patrouilleur
# de surface, pas de relation compagnon (pas de "reconnaissance"/"deploiement_drone").
#
# Les deux partent d'côtés opposés de la zone (> seuil 0.01° l'un de l'autre ET
# de la zone), donc la 1ère méthode (aller_a_agent vers __zone__) s'applique aux
# deux au démarrage. Mais aller_a_agent vise les coordonnées EXACTES de
# "zone_z" : une fois arrivés, drone_a et drone_b finissent au même point, donc
# à distance ~0 l'un de l'autre. Sans pré-remplissage explicite, la détection
# de contact ("distance_below __any__") — le plus proche AUTRE agent, sans
# filtre de rôle — se mettrait alors à désigner l'autre drone au lieu du
# vrai contact. D'où conditions.any = 'contact' (comme conditions.zone et
# conditions.cible) sur les deux : ambiguïté non pas théorique mais garantie
# ici par construction, contrairement aux autres scénarios de ce dossier où
# elle ne pouvait que ponctuellement se produire selon les positions.
AGENTS = {
    'zone_z': {
        'x': 1.260,
        'y': 103.750,
        'model': 'cube',
        'heading': 0.0,
        'linear_velocities_limits': (0.0, 0.0),
        'angular_velocities_limits': 0.0,
        'conditions': {'role': 'zone', 'is_zone': True},
        'mission': ('veiller', 'zone_z'),
    },
    'drone_a': {
        'x': 1.230,
        'y': 103.720,
        'model': 'x500',
        'heading': 0.0,
        'linear_velocities_limits': (0.0, 8.0),
        'angular_velocities_limits': 0.05,
        'conditions': {
            'role': 'drone', 'zone': 'zone_z', 'cible': 'contact', 'any': 'contact',
            'base_location': '1.230 103.720',
        },
        'mission': ('surveiller_zone', 'drone_a'),
    },
    'drone_b': {
        'x': 1.290,
        'y': 103.780,
        'model': 'x500',
        'heading': 0.0,
        'linear_velocities_limits': (0.0, 8.0),
        'angular_velocities_limits': 0.05,
        'conditions': {
            'role': 'drone', 'zone': 'zone_z', 'cible': 'contact', 'any': 'contact',
            'base_location': '1.290 103.780',
        },
        'mission': ('surveiller_zone', 'drone_b'),
    },
    'contact': {
        'x': 1.261,
        'y': 103.751,
        'model': 'wamv',
        'heading': 0.0,
        'linear_velocities_limits': (0.0, 5.0),
        'angular_velocities_limits': 0.05,
        'conditions': {'role': 'intruder', 'is_intruder': True},
        'mission': ('aller_a_position', 'contact', (1.320, 103.820)),
    },
}
