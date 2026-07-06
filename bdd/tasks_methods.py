import json
from pathlib import Path

import gtpyhop
from bdd.utils import in_zone, MIN_MOVE_DEG

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


def _find_agent_by_pattern(state, pattern):
    if not pattern:
        return None
    target = str(pattern).strip()
    norm = target.strip('_').lower()

    for name, data in state.agents.items():
        if name == target:
            return name
        if target and target.lower() in name.lower():
            return name
        role = str(data.get('role', '')).strip().lower()
        kind = str(data.get('kind', '')).strip().lower()
        if role and (role == norm or norm in role):
            return name
        if kind and (kind == norm or norm in kind):
            return name

    for name, data in state.agents.items():
        if data.get('is_intruder') and norm in {'intruder', 'intru', 'intruderagent', 'intrud'}:
            return name
        if data.get('is_base') and norm in {'base', 'port', 'dock', 'harbor'}:
            return name
        if str(data.get('role', '')).strip().lower() == 'base' and norm in {'base', 'port', 'dock', 'harbor'}:
            return name
        if 'base' in str(name).lower() and norm in {'base', 'port', 'dock', 'harbor'}:
            return name

    return None


def _resolve(arg, agent, state):
    if arg == '__self__':
        return agent
    if arg in _resolve_tokens:
        pattern = _resolve_tokens[arg]
        resolved = _find_agent_by_pattern(state, pattern)
        if resolved:
            return resolved
        return arg.strip('_') if arg.startswith('__') and arg.endswith('__') else arg
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
