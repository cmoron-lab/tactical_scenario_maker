AGENTS = {
    'test4': {
        'x': 0.002,
        'y': 0.002,
        'model': 'wamv',
        'linear_velocities_limits': (0.0, 5.0),
        'angular_velocities_limits': 0.05,
        'conditions': {},
        'mission': ('aller', 'test4', (1.0, 1.0)),
    },
    'azgetn2': {
        'x': 0.002,
        'y': 0.003,
        'model': 'wamv',
        'linear_velocities_limits': (0.0, 5.0),
        'angular_velocities_limits': 0.05,
        'conditions': {},
        'mission': ('suivre', 'azgetn2', 'test4'),
    },
}
