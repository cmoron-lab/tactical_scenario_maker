# "Agent 1 : ne fais rien" / "Agent 2 : va vers agent 1 et quand il est à
# environ 100m de distance, il fait des cercles autour" — mission asymétrique :
# agent1 passif ("veiller"), agent2 approche puis orbite réellement autour
# d'agent1 une fois à ~100m (tâche "encercler" -> leaf "orbiter", cf.
# bdd/tasks_methods.py::orbiter_m — position qui tourne autour de la cible,
# pas un simple aller-retour comme "eviter").
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
        'conditions': {
            'role': 'patrol', 'base_location': '1.27 103.75',
            'cible': 'agent1', 'encercler_threshold': 0.0009,
        },
        'mission': ('encercler', 'agent2'),
    },
}
