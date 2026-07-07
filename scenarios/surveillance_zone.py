# Couvre : surveiller_zone — ses 3 méthodes, dans l'ordre où elles
# s'enchaînent naturellement pendant la simulation :
#   1) "patrouilleur_zone" démarre à ~4 km de la zone (> seuil 0.01°)
#      -> aller_a_agent vers __zone__.
#   2) Une fois arrivé, "guetteur" est à portée (< 0.01°) -> reconnaissance,
#      qui (pas de drone ici) bascule sur suivre_agent et part le pourchasser.
#   3) "guetteur" s'éloigne ensuite (mission aller_a_position) ; une fois
#      hors de portée et la zone reformée sans contact -> repli sur veiller.
AGENTS = {
    'patrouilleur_zone': {
        'x': 1.230,
        'y': 103.720,
        'model': 'wamv',
        'heading': 0.0,
        'linear_velocities_limits': (0.0, 5.0),
        'angular_velocities_limits': 0.05,
        'conditions': {'base_location': '1.230 103.720', 'zone': 'zone_nord', 'cible': 'guetteur'},
        'mission': ('surveiller_zone', 'patrouilleur_zone'),
    },
    'zone_nord': {
        'x': 1.260,
        'y': 103.750,
        'model': 'cube',
        'heading': 0.0,
        'linear_velocities_limits': (0.0, 0.0),
        'angular_velocities_limits': 0.0,
        'conditions': {'role': 'zone', 'is_zone': True},
        'mission': ('veiller', 'zone_nord'),
    },
    'guetteur': {
        'x': 1.261,
        'y': 103.751,
        'model': 'wamv',
        'heading': 0.0,
        'linear_velocities_limits': (0.0, 5.0),
        'angular_velocities_limits': 0.05,
        'conditions': {'role': 'intruder', 'is_intruder': True},
        'mission': ('aller_a_position', 'guetteur', (1.300, 103.800)),
    },
}
