AGENTS = {
    'Agent1': {
        'x': 1.26,
        'y': 103.75,
        'model': 'wamv',
        'heading': 0.0,
        'linear_velocities_limits': (0.0, 3.0),
        'angular_velocities_limits': 0.05,
        'conditions': {'role': 'patrol', 'base_location': '1.26 103.75'},
        'mission': ('veiller', 'Agent1'),
    },
    'Agent2': {
        'x': 1.265,
        'y': 103.745,
        'model': 'wamv',
        'heading': 0.0,
        'linear_velocities_limits': (0.0, 3.0),
        'angular_velocities_limits': 0.05,
        'conditions': {'role': 'patrol', 'base_location': '1.265 103.745', 'eviter_threshold': 0.0017966223499820337, 'cible': 'Agent1', 'commande': 'attaquer'},
        'mission': ('reagir_conditions', 'Agent2'),
    },
}
