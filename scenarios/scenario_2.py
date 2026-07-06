"""
Scénario 2 : Zone Maritime Critique
- usv_patrol  : patrouilleur avec drone, météo favorable
- usv_intercept : intercepteur en standby, attend un ordre de coordination
- intruder    : intrus rapide qui tente de traverser la zone

Les 4 méthodes de respond_to_intruder se déclenchent selon les combinaisons
de préconditions définies dans tasks_methods.py.
"""

AGENTS = {
    "usv_patrol": {
        'x': 1.2605794416293148,
        'y': 103.7516212463379,
        'model': 'wamv',
        'linear_velocities_limits': (0, 5),
        'angular_velocities_limits': 0.05,
        'equipement': {
            'drone': True,
            'weather': 'clear',   # 'clear' ou 'storm'
        },
        'mission': ('veille', 'usv_patrol'),
    },
    "usv_intercept": {
        'x': 1.2575794416293148,
        'y': 103.7486212463379,
        'model': 'wamv',
        'linear_velocities_limits': (0, 5),
        'angular_velocities_limits': 0.05,
        'equipement': {'drone': False},
        'mission': ('standby', 'usv_intercept'),
    },
    "intruder": {
        'x': 1.2605794, 'y': 103.7456212,
        'model': 'wamv',
        'linear_velocities_limits': (0, 8),
        'angular_velocities_limits': 0.05,
        'equipement': {},
        'is_intruder': True,
        'mission': ('aller', 'intruder', (1.2605794, 103.7566212)),
    },
}
