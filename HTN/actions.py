# actions.py — Actions primitives LOTUSim
# Chaque fonction = une commande envoyée au simulateur.
# RÈGLE : modifier state ET ajouter à state.trace (anti-idempotence GTPyhop).
# app.py se charge de declare_actions() — ne pas l'appeler ici.

def patrouiller_zone(state, agent, zone):
    """Envoie l'agent en patrouille en boucle sur les waypoints d'une zone."""
    wps = state.zones.get(zone, {}).get("waypoints", [])
    state.phase[agent] = "patrouille"
    state.waypoints_courants[agent] = {"points": [tuple(w) for w in wps], "loop": True}
    state.trace.append(("patrouiller_zone", agent, zone))
    return state


def aller_vers_agent(state, agent, cible):
    """Navigue vers la position courante d'un autre agent."""
    if cible not in state.x:
        return None  # cible inconnue → action échoue
    state.phase[agent] = "interception"
    state.waypoints_courants[agent] = {
        "points": [(state.x[cible], state.y[cible])],
        "loop": False
    }
    state.trace.append(("aller_vers_agent", agent, cible))
    return state


def naviguer_vers_point(state, agent, x, y):
    """Navigue vers des coordonnées fixes (mètres, repère local)."""
    state.phase[agent] = "transit"
    state.waypoints_courants[agent] = {"points": [(float(x), float(y))], "loop": False}
    state.trace.append(("naviguer_vers_point", agent, x, y))
    return state


def stopper(state, agent):
    """Arrête l'agent sur place."""
    state.phase[agent] = "arret"
    state.waypoints_courants[agent] = {"points": [], "loop": False}
    state.trace.append(("stopper", agent))
    return state


def suivre_agent(state, agent, cible):
    """Suit un agent en continu (re-ciblage géré par le moniteur)."""
    if cible not in state.x:
        return None
    state.phase[agent] = "suivi"
    state.waypoints_courants[agent] = {
        "points": [(state.x[cible], state.y[cible])],
        "loop": False
    }
    state.trace.append(("suivre_agent", agent, cible))
    return state


def spawn_agent(state, nom, modele, x, y):
    """Crée un nouvel agent dans l'état (équivalent MASCmd CREATE)."""
    state.x[nom]    = float(x)
    state.y[nom]    = float(y)
    state.modele[nom] = modele
    state.dispo[nom]  = 1
    state.phase[nom]  = "spawne"
    state.waypoints_courants[nom] = {"points": [], "loop": False}
    state.trace.append(("spawn_agent", nom, modele, x, y))
    return state
