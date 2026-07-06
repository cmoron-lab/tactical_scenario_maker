import gtpyhop
from bdd.utils import in_zone, MIN_MOVE_DEG


# ── veille ────────────────────────────────────────────────────────────────────
#
# Préconditions scénario :
#   (aucune — intruder_nearby est calculé automatiquement par main.py)

def veille_m(state, agent):
    """Attend que l'intruder soit détecté, puis déclenche respond_to_intruder."""
    if not state.agents[agent].get('intruder_nearby'):
        return False
    return [('respond_to_intruder', agent)]


# ── respond_to_intruder ───────────────────────────────────────────────────────
#
# Les méthodes sont essayées dans l'ordre ; la première dont les préconditions
# passent est choisie (logique HTN avec backtracking).
#
# Préconditions scénario pour chaque méthode :
#
#   M1 (coordonné) :
#     - equipement.drone = True
#     - equipement.weather = 'clear'
#     - un agent 'usv_intercept' avec available = True dans le scénario
#
#   M2 (drone seul, météo) :
#     - equipement.drone = True
#     - equipement.weather = 'clear'
#
#   M3 (backup sans drone) :
#     - equipement.drone = False  (ou absent)
#     - un agent 'usv_intercept' avec available = True dans le scénario
#
#   M4 (drone seul, sans contrainte météo) :
#     - equipement.drone = True
#
#   M5 (fallback, toujours applicable) :
#     - (aucune)

def respond_to_intruder_m1(state, agent):
    """M1 — Drone + météo claire + intercepteur dispo → déploiement coordonné."""
    if not state.agents[agent].get('drone_available'):
        return False
    if state.agents[agent].get('weather') != 'clear':
        return False
    if not state.agents.get('usv_intercept', {}).get('available'):
        return False
    return [
        ('deployer_drone', agent),
        ('ordonner_intercept', 'usv_intercept', 'intruder'),
        ('maintenir_contact', agent, 'intruder'),
    ]


def respond_to_intruder_m2(state, agent):
    """M2 — Drone + météo claire, pas d'intercepteur → drone + suivre."""
    if not state.agents[agent].get('drone_available'):
        return False
    if state.agents[agent].get('weather') != 'clear':
        return False
    return [
        ('deployer_drone', agent),
        ('suivre', agent, 'intruder'),
    ]


def respond_to_intruder_m3(state, agent):
    """M3 — Pas de drone, intercepteur dispo → suivre + interception coordonnée."""
    if state.agents[agent].get('drone_available'):
        return False
    if not state.agents.get('usv_intercept', {}).get('available'):
        return False
    target = 'intruder' if 'intruder' in state.agents else 'intru'
    return [
        ('suivre', agent, target),
        ('ordonner_intercept', 'usv_intercept', target),
    ]


def respond_to_intruder_m_deploy_drone(state, agent):
    """
    M-drone — USV équipé d'un drone ET agent 'drone' présent → USV reste sur place,
    le drone suit l'intruder via sa propre boucle veille.

    Préconditions scénario :
      - equipement.drone = True
      - un agent nommé 'drone' présent dans le scénario avec mission ('veille', 'drone')
    """
    if not state.agents[agent].get('drone_available'):
        return False
    if 'drone' not in state.agents:
        return False
    return []  # USV ne fait rien ; le drone gère la poursuite de son côté


def respond_to_intruder_m4(state, agent):
    """M4 — Drone disponible mais pas d'agent 'drone' dans le scénario → USV se déplace vers l'intruder."""
    if not state.agents[agent].get('drone_available'):
        return False
    target = 'intruder' if 'intruder' in state.agents else 'intru'
    return [('deployer_drone_vers', agent, target)]


def respond_to_intruder_m5(state, agent):
    """M5 — Fallback : suivre direct."""
    target = 'intruder' if 'intruder' in state.agents else 'intru'
    return [('suivre', agent, target)]


# ── deployer_drone ────────────────────────────────────────────────────────────

def deployer_drone_m(state, agent):
    """
    Préconditions scénario :
      - equipement.drone = True
    Cible implicite : 'intruder' ou 'intru' selon le scénario.
    """
    target = 'intruder' if 'intruder' in state.agents else 'intru'
    return [('deployer_drone_vers', agent, target)]


def deployer_drone_vers_m(state, agent, target):
    pos = state.agents.get(target, {}).get('pos')
    if pos is None:
        return False
    last = state.agents[agent].get('last_waypoint')
    if last and in_zone({'lat': last[0], 'lon': last[1]}, pos, MIN_MOVE_DEG):
        return False
    return [('send_mas_cmd', agent, (pos['lat'], pos['lon']))]


# ── suivre ────────────────────────────────────────────────────────────────────

def suivre_m(state, agent, target):
    pos = state.agents.get(target, {}).get('pos')
    if pos is None:
        return False
    last = state.agents[agent].get('last_waypoint')
    if last and in_zone({'lat': last[0], 'lon': last[1]}, pos, MIN_MOVE_DEG):
        return False
    return [('send_mas_cmd', agent, (pos['lat'], pos['lon']))]


# ── maintenir_contact ─────────────────────────────────────────────────────────

def maintenir_contact_m(state, agent, target):
    """
    Préconditions scénario : (aucune)
    Suit la cible avec un décalage de ~100m pour garder le contact sans collision.
    """
    pos = state.agents.get(target, {}).get('pos')
    if pos is None:
        return False
    follow_pos = (pos['lat'] + 0.0009, pos['lon'])
    last = state.agents[agent].get('last_waypoint')
    if last and in_zone({'lat': last[0], 'lon': last[1]},
                        {'lat': follow_pos[0], 'lon': follow_pos[1]}, MIN_MOVE_DEG):
        return False
    return [('send_mas_cmd', agent, follow_pos)]


# ── standby ───────────────────────────────────────────────────────────────────

def standby_m(state, agent):
    """
    Préconditions scénario : (aucune)
    Attend un ordre de coordination dans state.orders[agent].
    L'ordre est écrit par ordonner_intercept (action).
    """
    order = getattr(state, 'orders', {}).get(agent)
    if order is None:
        return False
    last = state.agents[agent].get('last_waypoint')
    if last == order:
        return False  # Ordre déjà exécuté, attend le prochain
    return [('send_mas_cmd', agent, order)]


# ── aller ─────────────────────────────────────────────────────────────────────

def aller_m(state, agent, pos):
    return [('send_mas_cmd', agent, pos)]


# ── Action de coordination : ordonner_intercept ───────────────────────────────

def ordonner_intercept(state, agent, target):
    """
    Action pure — calcule le point d'interception devant la cible
    et l'écrit dans state.orders[agent].

    Préconditions scénario :
      - un agent nommé 'agent' (ex: 'usv_intercept') présent dans le scénario
      - state.position_history alimenté automatiquement par main.py
    """
    pos = state.agents.get(target, {}).get('pos')
    if pos is None:
        return False
    history = getattr(state, 'position_history', {}).get(target, [])
    intercept = _predict_intercept(pos, history)
    if not hasattr(state, 'orders'):
        state.orders = {}
    state.orders[agent] = intercept
    return state


def _predict_intercept(pos, history, steps=5):
    if len(history) >= 2:
        prev = history[-1]
        dlat = pos['lat'] - prev['lat']
        dlon = pos['lon'] - prev['lon']
        return (pos['lat'] + dlat * steps, pos['lon'] + dlon * steps)
    return (pos['lat'] + 0.003, pos['lon'])


# ── Déclarations GTpyhop ──────────────────────────────────────────────────────

gtpyhop.declare_task_methods('veille', veille_m)

gtpyhop.declare_task_methods('respond_to_intruder',
                             respond_to_intruder_m1,
                             respond_to_intruder_m2,
                             respond_to_intruder_m3,
                             respond_to_intruder_m_deploy_drone,
                             respond_to_intruder_m4,
                             respond_to_intruder_m5)

gtpyhop.declare_task_methods('deployer_drone', deployer_drone_m)
gtpyhop.declare_task_methods('deployer_drone_vers', deployer_drone_vers_m)
gtpyhop.declare_task_methods('suivre', suivre_m)
gtpyhop.declare_task_methods('maintenir_contact', maintenir_contact_m)
gtpyhop.declare_task_methods('standby', standby_m)
gtpyhop.declare_task_methods('aller', aller_m)

gtpyhop.declare_actions(ordonner_intercept)
