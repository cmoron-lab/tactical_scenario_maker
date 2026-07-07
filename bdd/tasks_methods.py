import json
from pathlib import Path

import gtpyhop
from bdd.utils import in_zone, MIN_MOVE_DEG, distance_deg

_KB_PATH = Path(__file__).parent / 'knowledge_base.json'


# ── Préconditions ─────────────────────────────────────────────────────────────

def _check(cond, agent, state):
    t   = cond['type']
    v   = cond.get('value', '')
    var = cond.get('variable', '')
    ag  = state.agents.get(agent, {})

    # ── Generic variable checks (new format) ──────────────────────────────
    if t == 'state_equals':
        cur = ag.get(var)
        v_lo = str(v).lower()
        if v_lo in ('true', 'false'):           # boolean comparison
            return bool(cur) == (v_lo == 'true')
        return str(cur) == str(v)

    if t == 'state_below':
        try:    return float(ag.get(var) or 0) < float(v or 0)
        except: return False

    if t == 'state_above':
        try:    return float(ag.get(var) or 0) > float(v or 0)
        except: return False

    if t == 'state_present':
        return ag.get(var) not in (None, '', False)

    # ── Legacy aliases (backwards compat with old KB files) ───────────────
    if t == 'drone_available':  return bool(ag.get('drone_available'))
    if t == 'drone_absent':     return not bool(ag.get('drone_available'))
    if t == 'weather_equals':   return ag.get('weather') == v
    if t == 'intruder_nearby':  return bool(ag.get('intruder_nearby'))
    if t == 'agent_present':    return bool(v) and v in state.agents and state.agents[v].get('available', True)
    if t == 'agent_absent':     return bool(v) and v not in state.agents
    return True


# ── Résolution des arguments ──────────────────────────────────────────────────

_resolve_tokens: dict = {}   # populated by load_kb() from KB resolve_tokens section


def _nearest_agent(state, agent, candidates):
    """
    Several agents can match the same pattern (e.g. several intruders) — prefer
    whichever is closest to the asking agent rather than an arbitrary dict-order
    pick, so "__intruder__" means "the nearest threat", not "the first one found".
    """
    if not candidates:
        return None
    if len(candidates) == 1 or not agent:
        return candidates[0]
    self_pos = state.agents.get(agent, {}).get('pos')
    if not self_pos:
        return candidates[0]

    def _dist(name):
        pos = state.agents.get(name, {}).get('pos')
        return distance_deg(self_pos, pos) if pos else float('inf')

    return min(candidates, key=_dist)


def _find_agent_by_pattern(state, pattern, agent=None):
    if not pattern:
        return None
    target = str(pattern).strip()
    norm = target.strip('_').lower()

    if target in state.agents:
        return target

    candidates = []
    for name, data in state.agents.items():
        if target and target.lower() in name.lower():
            candidates.append(name)
            continue
        role = str(data.get('role', '')).strip().lower()
        kind = str(data.get('kind', '')).strip().lower()
        if role and (role == norm or norm in role):
            candidates.append(name)
        elif kind and (kind == norm or norm in kind):
            candidates.append(name)

    if not candidates:
        # Generic marker convention: ANY token "__xxx__" can be attached to an agent
        # via a boolean condition "is_xxx" (e.g. "__vip__" -> conditions: {is_vip: true})
        # — no code change needed here to support a new token or several matching agents.
        marker_key = f'is_{norm}'
        candidates = [name for name, data in state.agents.items() if data.get(marker_key)]

    return _nearest_agent(state, agent, candidates)


def _resolve(arg, agent, state):
    if arg == '__self__':
        return agent

    def _parse_location(value):
        if isinstance(value, (list, tuple)) and len(value) == 2:
            try:
                return float(value[0]), float(value[1])
            except (TypeError, ValueError):
                return None
        if isinstance(value, str):
            parts = value.strip().split()
            if len(parts) == 2:
                try:
                    return float(parts[0]), float(parts[1])
                except ValueError:
                    return None
        return None

    if arg in ('__base_position__', '__base_location__'):
        # Check current agent's own conditions first
        agent_data = state.agents.get(agent, {})
        loc = agent_data.get('base_location') or agent_data.get('base_pos') or agent_data.get('base_position')
        parsed = _parse_location(loc)
        if parsed:
            return parsed

        # Fallback: look in any agent data
        for data in state.agents.values():
            loc = data.get('base_location') or data.get('base_pos') or data.get('base_position')
            parsed = _parse_location(loc)
            if parsed:
                return parsed

        base_agent = _find_agent_by_pattern(state, '__base__', agent)
        if base_agent:
            pos = state.agents.get(base_agent, {}).get('pos')
            if pos is not None:
                return pos['lat'], pos['lon']

        return arg.strip('_') if arg.startswith('__') and arg.endswith('__') else arg

    if arg in _resolve_tokens:
        pattern = _resolve_tokens[arg]
        resolved = _find_agent_by_pattern(state, pattern, agent)
        if resolved:
            return resolved
        return arg.strip('_') if arg.startswith('__') and arg.endswith('__') else arg

    # Bare dunder token not registered in resolve_tokens (e.g. "__intruder__",
    # "__base__") — try resolving it directly by role/kind/marker.
    if arg.startswith('__') and arg.endswith('__'):
        resolved = _find_agent_by_pattern(state, arg, agent)
        if resolved:
            return resolved
        return arg.strip('_')

    return arg


# ── Génération dynamique de méthodes ─────────────────────────────────────────

def _make_method(preconditions, subtasks):
    def method(state, agent):
        for cond in preconditions:
            if not _check(cond, agent, state):
                return False
        return [
            tuple([st['task']] + [_resolve(a, agent, state) for a in st.get('args', [])])
            for st in subtasks
        ]
    return method


# ── Chargement depuis knowledge_base.json ────────────────────────────────────

def load_kb():
    global _resolve_tokens
    with open(_KB_PATH, encoding='utf-8') as f:
        kb = json.load(f)

    # Load resolve tokens (e.g. {'__intruder__': 'intru'})
    _resolve_tokens = dict(kb.get('resolve_tokens', {}))

    for task_name, task_def in kb['tasks'].items():
        methods = []
        for i, m in enumerate(task_def['methods']):
            fn = _make_method(m['preconditions'], m['subtasks'])
            fn.__name__ = f'm_{task_name}_{i}'
            methods.append(fn)
        if methods:
            gtpyhop.declare_task_methods(task_name, *methods)

    return kb


# ── Méthodes feuilles (locked — logique de mouvement) ────────────────────────

def aller_a_agent_m(state, agent, target):
    pos = state.agents.get(target, {}).get('pos')
    if pos is None:
        return False
    last = state.agents[agent].get('last_waypoint')
    if last and in_zone({'lat': last[0], 'lon': last[1]}, pos, MIN_MOVE_DEG):
        return False
    return [('aller_a', agent, (pos['lat'], pos['lon']))]


def suivre_m(state, agent, target):
    pos = state.agents.get(target, {}).get('pos')
    if pos is None:
        return False
    last = state.agents[agent].get('last_waypoint')
    if last and in_zone({'lat': last[0], 'lon': last[1]}, pos, MIN_MOVE_DEG):
        return False
    return [('aller_a', agent, (pos['lat'], pos['lon']))]


def maintenir_contact_m(state, agent, target):
    pos = state.agents.get(target, {}).get('pos')
    if pos is None:
        return False
    follow_pos = (pos['lat'] + 0.0009, pos['lon'])
    last = state.agents[agent].get('last_waypoint')
    if last and in_zone({'lat': last[0], 'lon': last[1]},
                        {'lat': follow_pos[0], 'lon': follow_pos[1]}, MIN_MOVE_DEG):
        return False
    return [('aller_a', agent, follow_pos)]


def standby_m(state, agent):
    order = getattr(state, 'orders', {}).get(agent)
    if order is None:
        return False
    if state.agents[agent].get('last_waypoint') == order:
        return False
    return [('aller_a', agent, order)]


def aller_m(state, agent, pos):
    return [('aller_a', agent, pos)]

def aller_a_position_m(state, agent, pos):
    return [('aller_a', agent, pos)]

# ── Action de coordination ────────────────────────────────────────────────────

def ordonner_intercept(state, agent, target):
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

gtpyhop.declare_task_methods('aller_a_agent',       aller_a_agent_m)
gtpyhop.declare_task_methods('suivre',              suivre_m)
gtpyhop.declare_task_methods('maintenir_contact',   maintenir_contact_m)
gtpyhop.declare_task_methods('standby',             standby_m)
gtpyhop.declare_task_methods('aller',               aller_m)
gtpyhop.declare_task_methods('aller_a_position',    aller_a_position_m)
gtpyhop.declare_actions(ordonner_intercept)

load_kb()
