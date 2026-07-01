AGENTS = {
    "usv": {
        'x': 1.2605794416293148,
        'y': 103.7516212463379,
        'model': 'wamv',
        'linear_velocities_limits': (0, 5),
        'angular_velocities_limits': 0.05,
        'mission': {
            'task': ('veille', 'usv'),
            'on_complete': None,
            'on_interrupt': {
                'intruder_detected': {
                    'task': ('suivre', 'usv', 'intru'),
                    'loop_interval': 3.0,
                    'on_complete': None,
                    'on_interrupt': {},
                }
            }

        }
    },
    "intru": {
        'x': 1.2605794, 'y': 103.7476212,
        'model': 'wamv',
        'linear_velocities_limits': (0, 5),
        'angular_velocities_limits': 0.05,
        'mission': {
            'task': ('aller', 'intru', (1.2605794, 103.7526212)),
            'on_complete': None,
            'on_interrupt': {},
        }
    },
}