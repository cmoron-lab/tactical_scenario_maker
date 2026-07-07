AGENTS = {
    'agent1': {
        'x': 1.26,
        'y': 103.75,
        'model': 'wamv',
        'heading': 0.0,
        'linear_velocities_limits': (0.0, 3.0),
        'angular_velocities_limits': 0.05,
        'conditions': {'role': 'patrol', 'base_location': '1.26 103.75'},
        'mission': ('veiller', 'agent1'),
    },
    'agent2': {
        'x': 1.27,
        'y': 103.75,
        'model': 'wamv',
        'heading': 0.0,
        'linear_velocities_limits': (0.0, 3.0),
        'angular_velocities_limits': 0.05,
        'conditions': {'role': 'patrol', 'base_location': '1.27 103.75', 'eviter_threshold': 0.0008983111749910168, 'cible': 'agent1'},
        'mission': ('eviter', 'agent2'),
    },
}
