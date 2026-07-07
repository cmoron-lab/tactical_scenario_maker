# Couvre : rentrer_a_la_base -> naviguer_vers_base -> aller_a_position.
# L'agent démarre à ~3 km de sa base déclarée ; le plan doit le ramener dessus.
AGENTS = {
    'eclaireur': {
        'x': 1.280,
        'y': 103.770,
        'model': 'wamv',
        'heading': 0.0,
        'linear_velocities_limits': (0.0, 5.0),
        'angular_velocities_limits': 0.05,
        'conditions': {'base_location': '1.260 103.750'},
        'mission': ('rentrer_a_la_base', 'eclaireur'),
    },
}
