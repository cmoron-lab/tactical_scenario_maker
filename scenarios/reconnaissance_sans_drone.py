AGENTS = {
    'veilleur2': {
        'x': 1.26,
        'y': 103.75,
        'model': 'wamv',
        'heading': 0.0,
        'linear_velocities_limits': (0.0, 5.0),
        'angular_velocities_limits': 0.05,
        'conditions': {'drone_available': True, 'base_location': '1.260 103.750', 'drone': 'cible2', 'cible': 'cible2'},
        'mission': ('reconnaissance', 'veilleur2'),
    },
    'cible2': {
        'x': 1.278,
        'y': 103.77,
        'model': 'wamv',
        'heading': 0.0,
        'linear_velocities_limits': (0.0, 5.0),
        'angular_velocities_limits': 0.05,
        'conditions': {},
        'mission': ('veiller', 'cible2'),
    },
}
