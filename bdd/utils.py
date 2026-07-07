import math

DETECTION_RADIUS_DEG = 0.003
MIN_MOVE_DEG = 0.0003

# Origine du monde Gazebo (lotusim.world)
WORLD_ORIGIN = {'lat': 1.2421, 'lon': 103.7198}
# Rayon max autour de l'origine : au-delà, Gazebo perd en précision
WORLD_MAX_RADIUS_DEG = 0.5   # ~55 km

def distance_deg(a, b):
    """Distance in degrees between two {'lat':.., 'lon':..} positions."""
    return math.hypot(a['lat'] - b['lat'], a['lon'] - b['lon'])


def in_zone(a, b, radius):
    return distance_deg(a, b) < radius

def in_world(lat, lon):
    """Retourne True si (lat, lon) est dans la zone valide du monde LOTUSim."""
    return math.hypot(lat - WORLD_ORIGIN['lat'], lon - WORLD_ORIGIN['lon']) <= WORLD_MAX_RADIUS_DEG


def agent_conditions(agent):
    """Return an agent's precondition-relevant state — prefers 'conditions', falls back to legacy 'equipement'."""
    if 'conditions' in agent:
        return agent['conditions']
    eq = agent.get('equipement', {})
    cond = {}
    if 'drone' in eq:
        cond['drone_available'] = bool(eq['drone'])
    if 'weather' in eq:
        cond['weather'] = eq['weather']
    return cond


def is_intruder_agent(agent):
    """True if the agent is marked as the intruder/target, via conditions or legacy flags."""
    cond = agent_conditions(agent)
    if cond.get('is_intruder') or str(cond.get('role', '')).strip().lower() == 'intruder':
        return True
    return bool(agent.get('is_intruder')) or str(agent.get('role', '')).strip().lower() == 'intruder'
