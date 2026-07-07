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
        'x': 1.275,
        'y': 103.75,
        'model': 'wamv',
        'heading': 0.0,
        'linear_velocities_limits': (0.0, 3.0),
        'angular_velocities_limits': 0.05,
        'conditions': {'role': 'patrol', 'base_location': '1.275 103.75', 'cible': 'agent1'},
        'mission': ('encercler', 'agent2'),
    },
}
