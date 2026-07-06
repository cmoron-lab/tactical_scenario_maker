AGENTS = {
    "usv": {
        'x': 1.2605794416293148,
        'y': 103.7516212463379,
        'model': 'wamv',
        'linear_velocities_limits': (0, 5),
        'angular_velocities_limits': 0.05,
        'equipement': {'drone': True},
        'mission': ('veille', 'usv'),
    },
    "drone": {
        'x': 1.2605794416293148,   # Spawne à la position de usv
        'y': 103.7516212463379,
        'model': 'wamv',
        'linear_velocities_limits': (0, 8),
        'angular_velocities_limits': 0.05,
        'equipement': {},
        'mission': ('veille', 'drone'),  # Suit intru dès détection
    },
    "intru": {
        'x': 1.2575794, 'y': 103.7516212,   # Démarre au sud de usv
        'model': 'wamv',
        'linear_velocities_limits': (0, 5),
        'angular_velocities_limits': 0.05,
        'equipement': {},
        'mission': ('aller', 'intru', (1.2645794, 103.7516212)),  # Passe dans la zone de détection et remonte au nord
    },
}
