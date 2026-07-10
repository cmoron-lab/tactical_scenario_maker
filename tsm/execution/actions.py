"""Actions HTN pures + factory des commands liées au client LOTUSim.

Les actions pures mutent l'état de planification sans toucher au ROS
(utilisées par la préview de plan web). Les commands sortent de
make_commands(client, logs) : GTPyhop appelle les actions avec
(state, *args) uniquement, la closure porte les dépendances.
"""
from __future__ import annotations

from typing import Any


def aller_a(state: Any, agent: str, pos: Any) -> Any:
    """Action pure : met à jour le state (simulation, pas de ROS)."""
    state.agents[agent]['pos'] = {'lat': pos[0], 'lon': pos[1]}
    state.agents[agent]['last_waypoint'] = pos
    return state


def creation_agent(state, agent, drone):
    """
    Marks that `agent` has activated its companion drone `drone`.

    NOTE — this does NOT spawn a new ROS entity. In this architecture the
    companion (e.g. a drone) is pre-declared in the scenario from the start,
    with its own standing mission (typically "suivre_agent __self__") —
    because main.py runs exactly one planning thread per agent, fixed at
    startup from the scenario file; there is currently no mechanism to spawn a
    brand-new ROS entity *and* its own planning thread mid-plan. This action is
    the hook to extend later if true runtime spawning is built (it would call
    spawn_vessel() here instead of just setting a flag).

    `drone` is resolved from the "__drone__" token (bdd/tasks_methods.py) —
    either an explicit per-agent override (scenario editor's "Agent «drone»"
    dropdown) or, absent that, whichever agent carries role/kind "drone" or a
    truthy "is_drone" condition.
    """
    state.agents[agent]['drone_deployed'] = True
    state.agents[agent]['deployed_drone'] = drone
    if drone in state.agents:
        state.agents[drone]['drone_deployed'] = True
    return state


def make_commands(client: Any, logs: Any) -> tuple[Any, ...]:
    def c_aller_a(state: Any, agent: str, pos: Any) -> Any:
        """Command : envoie le waypoint à LOTUSim et met à jour le state."""
        client.set_waypoints(agent, pos[0], pos[1])
        logs.log_waypoint(agent, pos[0], pos[1])
        state.agents[agent]['pos'] = {'lat': pos[0], 'lon': pos[1]}
        state.agents[agent]['last_waypoint'] = pos
        return state

    return (c_aller_a,)
