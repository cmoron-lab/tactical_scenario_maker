# methods.py — Méthodes HTN
# Une méthode = une façon de décomposer une tâche en sous-tâches.
# Retourne une liste de sous-tâches (tuples) ou None si préconditions non satisfaites.
# GTPyhop essaie les méthodes dans l'ordre déclaré dans tasks.py.
# app.py se charge de declare_task_methods() — ne pas l'appeler ici.

import math


# ══════════════════════════════════════════════════════════════════════
#  TÂCHE : patrouiller(agent, zone)
# ══════════════════════════════════════════════════════════════════════

def methode_patrouille_standard(state, agent, zone):
    """Patrouille en boucle si l'agent est disponible et la zone existe."""
    if state.dispo.get(agent) != 1:
        return None
    if zone not in state.zones:
        return None
    return [
        ("patrouiller_zone", agent, zone)
    ]


# ══════════════════════════════════════════════════════════════════════
#  TÂCHE : intercepter(agent, cible)
# ══════════════════════════════════════════════════════════════════════

def methode_deployer_drone(state, agent, cible):
    """
    Méthode prioritaire : cherche un drone x500 disponible (liaison),
    le spawne depuis la position de l'agent, et l'envoie vers la cible.
    Si aucun drone dispo → retourne None → GTPyhop essaie la méthode suivante.
    """
    if state.dispo.get(agent) != 1:
        return None

    # Chercher un drone disponible parmi les agents connus
    drone = None
    for nom in state.x:
        if (state.modele.get(nom) == "x500"
                and state.dispo.get(nom, 0) == 1
                and nom != agent
                and nom != cible):
            drone = nom
            break

    if drone is None:
        return None  # pas de drone → méthode suivante

    x_dep = state.x[agent]
    y_dep = state.y[agent]

    return [
        ("spawn_agent",     drone, "x500", x_dep, y_dep),
        ("aller_vers_agent", drone, cible)
    ]


def methode_interception_directe(state, agent, cible):
    """Fallback : l'agent va directement vers la cible."""
    if state.dispo.get(agent) != 1:
        return None
    if cible not in state.x:
        return None
    return [
        ("aller_vers_agent", agent, cible)
    ]


# ══════════════════════════════════════════════════════════════════════
#  TÂCHE : engager(agent, cible)
# ══════════════════════════════════════════════════════════════════════

def methode_engagement_direct(state, agent, cible):
    """Approche la cible puis stoppe (engagement à courte distance)."""
    if state.dispo.get(agent) != 1:
        return None
    if cible not in state.x:
        return None
    return [
        ("aller_vers_agent", agent, cible),
        ("stopper",          agent)
    ]


# ══════════════════════════════════════════════════════════════════════
#  TÂCHE : escorter(agent, convoi)
# ══════════════════════════════════════════════════════════════════════

def methode_escorte_rapprochee(state, agent, convoi):
    """Suit le convoi en continu."""
    if state.dispo.get(agent) != 1:
        return None
    if convoi not in state.x:
        return None
    return [
        ("suivre_agent", agent, convoi)
    ]


# ══════════════════════════════════════════════════════════════════════
#  TÂCHE : rechercher_zone(agent, zone)
# ══════════════════════════════════════════════════════════════════════

def methode_recherche_systematique(state, agent, zone):
    """Parcourt la zone en boucle pour la rechercher."""
    if state.dispo.get(agent) != 1:
        return None
    if zone not in state.zones:
        return None
    return [
        ("patrouiller_zone", agent, zone)
    ]
