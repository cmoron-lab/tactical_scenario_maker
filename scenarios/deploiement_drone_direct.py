AGENTS = {
    'commandant': {
        'x': 1.26,
        'y': 103.75,
        'model': 'wamv',
        'heading': 0.0,
        'linear_velocities_limits': (0.0, 5.0),
        'angular_velocities_limits': 0.05,
        'conditions': {'drone': 'drone2'},
        'mission': ('deploiement_drone', 'commandant'),
    },
    'drone2': {
        'x': 1.2605,
        'y': 103.7505,
        'model': 'x500',
        'heading': 0.0,
        'linear_velocities_limits': (0.0, 8.0),
        'angular_velocities_limits': 0.05,
        'conditions': {},
        'mission': ('veiller', 'drone2'),
    },
}
