"""Géométrie et conditions d'agent — port typé de bdd/utils.py."""
from __future__ import annotations

import math
from typing import Any

MIN_MOVE_DEG = 0.0003

def distance_deg(a: dict[str, float], b: dict[str, float]) -> float:
    """Distance in degrees between two {'lat':.., 'lon':..} positions."""
    return math.hypot(a['lat'] - b['lat'], a['lon'] - b['lon'])


def in_zone(a: dict[str, float], b: dict[str, float], radius: float) -> bool:
    return distance_deg(a, b) < radius


def agent_conditions(agent: dict[str, Any]) -> dict[str, Any]:
    """Return an agent's precondition-relevant state — prefers 'conditions', falls back to legacy 'equipement'."""
    if 'conditions' in agent:
        conditions: dict[str, Any] = agent['conditions']
        return conditions
    eq = agent.get('equipement', {})
    cond = {}
    if 'drone' in eq:
        cond['drone_available'] = bool(eq['drone'])
    if 'weather' in eq:
        cond['weather'] = eq['weather']
    return cond


def check_condition(cond: dict[str, Any], ag: dict[str, Any]) -> bool | None:
    """
    Evaluate one KB precondition against a flat agent-state dict. Returns True/False
    for the generic checks shared by the real planner (tasks_methods._check) and any
    preview/dry-run resolver; returns None for condition types that need cross-agent
    lookups (the caller decides how to handle those, e.g. against a full state).
    """
    t = cond.get('type')
    v = cond.get('value', '')
    var = cond.get('variable', '')

    if t == 'state_equals':
        cur = ag.get(var)
        v_lo = str(v).lower()
        if v_lo in ('true', 'false'):
            return bool(cur) == (v_lo == 'true')
        return str(cur) == str(v)

    if t == 'state_below':
        try:
            return float(ag.get(var) or 0) < float(v or 0)
        except (TypeError, ValueError):
            return False

    if t == 'state_above':
        try:
            return float(ag.get(var) or 0) > float(v or 0)
        except (TypeError, ValueError):
            return False

    if t == 'state_present':
        return ag.get(var) not in (None, '', False)

    return None
