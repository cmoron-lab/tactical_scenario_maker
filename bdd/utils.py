import math

DETECTION_RADIUS_DEG = 0.003
MIN_MOVE_DEG = 0.0003

# Origine du monde Gazebo (lotusim.world)
WORLD_ORIGIN = {'lat': 1.2421, 'lon': 103.7198}
# Rayon max autour de l'origine : au-delà, Gazebo perd en précision
WORLD_MAX_RADIUS_DEG = 0.5   # ~55 km

def in_zone(a, b, radius):
    return math.hypot(a['lat'] - b['lat'], a['lon'] - b['lon']) < radius

def in_world(lat, lon):
    """Retourne True si (lat, lon) est dans la zone valide du monde LOTUSim."""
    return math.hypot(lat - WORLD_ORIGIN['lat'], lon - WORLD_ORIGIN['lon']) <= WORLD_MAX_RADIUS_DEG
