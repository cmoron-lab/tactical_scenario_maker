import json
import math
from pathlib import Path

import gtpyhop
from bdd.utils import in_zone, MIN_MOVE_DEG, distance_deg, check_condition

_KB_PATH = Path(__file__).parent.parent / 'doctrine' / 'knowledge_base.json'


# ── Préconditions ─────────────────────────────────────────────────────────────

def _check(cond, agent, state):
    ag = state.agents.get(agent, {})
    result = check_condition(cond, ag)
    if result is not None:
        return result

    t = cond['type']
    v = cond.get('value', '')

    # ── Live distance preconditions — no separate "trigger" pass needed:
    # distance to the resolved target is computed straight from current positions
    # at the moment the precondition is checked. "target" accepts the same generic
    # tokens as subtask args (__intruder__, __base__, __protege__...) or a literal
    # agent name set directly on this agent/scenario.
    if t in ('distance_below', 'distance_above'):
        target_name = _resolve_agent_token(state, agent, cond.get('target', ''))
        if not target_name:
            return False
        self_pos = ag.get('pos')
        target_pos = state.agents.get(target_name, {}).get('pos')
        if not self_pos or not target_pos:
            return False
        # "threshold_var" (optional): this agent's own conditions can override the
        # KB's default distance via a named field (e.g. conditions.eviter_threshold),
        # for scenarios needing a specific distance (e.g. "moins de 100m") that the
        # KB-wide default doesn't match. Falls back to the literal "threshold" when
        # unset — existing methods without "threshold_var" are unaffected.
        threshold_var = cond.get('threshold_var')
        raw_threshold = cond.get('threshold', 0)
        if threshold_var and ag.get(threshold_var) not in (None, ''):
            raw_threshold = ag.get(threshold_var)
        try:
            threshold = float(raw_threshold)
        except (TypeError, ValueError):
            return False
        dist = distance_deg(self_pos, target_pos)
        return dist < threshold if t == 'distance_below' else dist > threshold

    # ── Legacy aliases needing cross-agent lookups (backwards compat) ─────
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

    # "N'importe quel agent" wildcard — no role/marker filter at all, just the
    # nearest OTHER agent. Useful for a generic proximity check ("is anything
    # nearby") that doesn't depend on a specific role being assigned. Landmarks
    # (e.g. a "__zone__" marker) are excluded — they're a reference point, not
    # a "contact" to react to.
    if norm in ('any', 'n_importe_quel_agent', 'anyone'):
        return _nearest_agent(state, agent, [
            n for n in state.agents if n != agent and not state.agents[n].get('is_zone')
        ])

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


def _resolve_agent_token(state, agent, token):
    """
    Resolve a "__token__" (precondition target or subtask arg) to a concrete
    agent name, for the ASKING agent specifically. Checks, in order:

    1. An explicit per-agent override — this agent's own conditions has a
       literal field named after the token (e.g. conditions.cible = "agent2"),
       set via the scenario editor's "sélectionner un agent" dropdown. Always
       wins — it's a direct, scenario-specific wiring, not a guess.
    2. The KB's resolve_tokens mapping (e.g. "__cible__" -> "__any__") resolved
       generically via role/kind/marker or nearest-agent proximity
       (_find_agent_by_pattern) — the automatic fallback when no override is set.
    """
    if not token:
        return None
    norm = str(token).strip('_')
    ag = state.agents.get(agent, {}) if agent else {}
    override = ag.get(norm)
    if isinstance(override, str) and override in state.agents:
        return override
    pattern = _resolve_tokens.get(token, token)
    return _find_agent_by_pattern(state, pattern, agent)


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

    if arg == '__destination__':
        agent_data = state.agents.get(agent, {})
        parsed = _parse_location(agent_data.get('destination'))
        if parsed:
            return parsed
        return arg.strip('_')

    # Any other "__token__" (registered in resolve_tokens or not, e.g.
    # "__cible__", "__zone__", "__intruder__") — per-agent override first,
    # then the generic role/kind/marker/proximity fallback.
    if arg.startswith('__') and arg.endswith('__'):
        resolved = _resolve_agent_token(state, agent, arg)
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
        # gtpyhop.declare_task_methods() ACCUMULATES across calls by design (its
        # own docstring: "can be called several times to declare MORE methods
        # for the same task") — meant for spreading declarations across files,
        # not for reloading. But load_kb() gets called again on every KB save
        # (app.py's /api/kb handler, and every AI-generated scenario), so
        # without clearing the previous registration first, each reload piled
        # a duplicate copy of every method onto the ones already registered —
        # silently multiplying preconditions/subtasks and shifting method
        # order with every single edit made through the KB tab.
        gtpyhop.current_domain._task_method_dict.pop(task_name, None)
        methods = []
        for i, m in enumerate(task_def['methods']):
            fn = _make_method(m['preconditions'], m['subtasks'])
            fn.__name__ = f'm_{task_name}_{i}'
            methods.append(fn)
        if methods:
            gtpyhop.declare_task_methods(task_name, *methods)

    return kb


# ── Cibles à surveiller pour la replanification événementielle ───────────────

def collect_watched_tokens(kb, task_name, visited=None):
    """
    Recursively collect every "__token__" that this task's reachable methods
    might depend on — both distance-precondition targets and subtask-arg
    references — across ALL methods (not just whichever currently matches),
    since which branch is active can change over time. "__self__" is excluded
    (it's the agent's own position, always implicitly watched).
    """
    if visited is None:
        visited = set()
    if task_name in visited:
        return set()
    visited.add(task_name)
    task_def = kb.get('tasks', {}).get(task_name)
    if not task_def:
        return set()

    tokens = set()
    for method in task_def.get('methods', []):
        for cond in method.get('preconditions', []):
            if cond.get('type') in ('distance_below', 'distance_above') and cond.get('target'):
                tokens.add(cond['target'])
        for st in method.get('subtasks', []):
            for arg in st.get('args', []):
                if isinstance(arg, str) and arg.startswith('__') and arg.endswith('__') and arg != '__self__':
                    tokens.add(arg)
            tokens |= collect_watched_tokens(kb, st.get('task', ''), visited)
    return tokens


def resolve_watched_agents(state, agent, tokens):
    """Resolve a set of '__token__' patterns to concrete agent names, for `agent`."""
    resolved = set()
    for tok in tokens:
        if tok in ('__base_location__', '__base_position__', '__destination__'):
            continue  # fixed positions, not another live agent to watch
        name = _find_agent_by_pattern(state, tok, agent)
        if name:
            resolved.add(name)
    return resolved


# ── Méthodes feuilles (locked — logique de mouvement) ────────────────────────
#
# Idempotency guard convention: once the same waypoint has already been sent
# (agent's last_waypoint is still within MIN_MOVE_DEG of the intended target),
# these return [] — an empty-but-SUCCESSFUL decomposition — never False.
# GTPyhop treats the two very differently (gtpyhop.py::_refine_task_and_continue:
# "subtasks != False and subtasks != None" is what counts as applicable): False
# means "this method doesn't apply, try the task's NEXT method" and can cascade
# into a sibling method firing instead (e.g. suivre_agent's 2nd method — chase —
# taking over every other cycle because its 1st method — return to base —
# looked like it "failed" merely because the base waypoint was already in
# flight), producing a visible oscillation instead of a boat that just keeps
# going where it was already told to go. Only a genuinely missing target
# (pos is None) is a real failure and stays False.

def aller_a_agent_m(state, agent, target):
    pos = state.agents.get(target, {}).get('pos')
    if pos is None:
        return False
    last = state.agents[agent].get('last_waypoint')
    if last and in_zone({'lat': last[0], 'lon': last[1]}, pos, MIN_MOVE_DEG):
        return []
    return [('aller_a', agent, (pos['lat'], pos['lon']))]


def suivre_m(state, agent, target):
    pos = state.agents.get(target, {}).get('pos')
    if pos is None:
        return False
    last = state.agents[agent].get('last_waypoint')
    if last and in_zone({'lat': last[0], 'lon': last[1]}, pos, MIN_MOVE_DEG):
        return []
    return [('aller_a', agent, (pos['lat'], pos['lon']))]


def maintenir_contact_m(state, agent, target):
    pos = state.agents.get(target, {}).get('pos')
    if pos is None:
        return False
    follow_pos = (pos['lat'] + 0.0009, pos['lon'])
    last = state.agents[agent].get('last_waypoint')
    if last and in_zone({'lat': last[0], 'lon': last[1]},
                        {'lat': follow_pos[0], 'lon': follow_pos[1]}, MIN_MOVE_DEG):
        return []
    return [('aller_a', agent, follow_pos)]


def aller_a_position_m(state, agent, pos):
    # Same idempotency guard as aller_a_agent_m/suivre_m/maintenir_contact_m —
    # without it, this was the one movement method that re-issued the SAME
    # waypoint on every replan cycle, since the calling agent always watches
    # its OWN position (main.py) and re-plans on every tiny move while it's
    # actually en route. Resending an identical waypoint list repeatedly
    # resets the LOTUSim waypoint-follower's progress each time instead of
    # letting it complete the leg — visible as the vessel "spinning in place"
    # rather than ever reaching the target (e.g. rentrer_a_la_base never
    # actually arriving at base).
    last = state.agents[agent].get('last_waypoint')
    if last and in_zone({'lat': last[0], 'lon': last[1]}, {'lat': pos[0], 'lon': pos[1]}, MIN_MOVE_DEG):
        return []
    return [('aller_a', agent, pos)]


# Angle advanced per replan cycle — with the event-driven replanning loop
# (main.py) re-checking roughly every REPLAN_SAFETY_TIMEOUT (~5s) or whenever
# the target actually moves, this gives a slow, visible orbit rather than a
# barely-perceptible creep or a dizzying spin.
ORBIT_ANGULAR_STEP = math.radians(35)
# Fallback orbit radius if the agent has no "encercler_threshold" of its own
# (matches surveiller_zone's contact-detection scale).
DEFAULT_ORBIT_RADIUS_DEG = 0.01


# Orbit strictly inside the "close enough to orbit" trigger radius, not AT it —
# a radius exactly equal to the precondition's threshold sits right on the
# float-rounding boundary of "distance_below", so cos/sin rounding would
# occasionally push the computed distance a hair over it, flip the precondition
# to "too far", and snap the agent straight to the target's exact position for
# one cycle before it resumes orbiting. 90% leaves enough margin to never flirt
# with that boundary.
ORBIT_RADIUS_MARGIN = 0.9


def orbiter_m(state, agent, target):
    """
    Circles `target` at roughly a fixed radius — unlike suivre_m/aller_a_agent_m
    (a single waypoint, re-issued only if the target moves), this ALWAYS
    advances to a new point on the circle each time it's replanned, tracked via
    a persistent "orbit_angle" on the agent's own state. The radius is a margin
    below this agent's own "encercler_threshold" (conditions.eviter_threshold
    twin, used by the "encercler" task's precondition — see
    knowledge_base.json), so it orbits comfortably inside the distance that
    triggered orbiting rather than teetering right on its edge.
    """
    pos = state.agents.get(target, {}).get('pos')
    if pos is None:
        return False
    ag = state.agents[agent]
    try:
        trigger_radius = float(ag.get('encercler_threshold') or DEFAULT_ORBIT_RADIUS_DEG)
    except (TypeError, ValueError):
        trigger_radius = DEFAULT_ORBIT_RADIUS_DEG
    radius = trigger_radius * ORBIT_RADIUS_MARGIN
    angle = (ag.get('orbit_angle') or 0.0) + ORBIT_ANGULAR_STEP
    ag['orbit_angle'] = angle
    next_pos = (pos['lat'] + radius * math.cos(angle), pos['lon'] + radius * math.sin(angle))
    return [('aller_a', agent, next_pos)]


# How far along the threat→protégé segment to stand: 0.5 = exact midpoint.
INTERPOSE_FRACTION = 0.5


def interposer_m(state, agent, threat, protege):
    """
    Positions `agent` on the straight line between `threat` and `protege`'s
    CURRENT positions, at INTERPOSE_FRACTION of the way from protégé to
    threat (0.5 = the midpoint) — recomputed fresh each time either one
    moves, same idempotency guard as the other movement leaves (no new
    command once already at the right spot).
    """
    threat_pos = state.agents.get(threat, {}).get('pos')
    protege_pos = state.agents.get(protege, {}).get('pos')
    if threat_pos is None or protege_pos is None:
        return False
    pos = (
        protege_pos['lat'] + (threat_pos['lat'] - protege_pos['lat']) * INTERPOSE_FRACTION,
        protege_pos['lon'] + (threat_pos['lon'] - protege_pos['lon']) * INTERPOSE_FRACTION,
    )
    last = state.agents[agent].get('last_waypoint')
    if last and in_zone({'lat': last[0], 'lon': last[1]}, {'lat': pos[0], 'lon': pos[1]}, MIN_MOVE_DEG):
        return []
    return [('aller_a', agent, pos)]


# ── Déclarations GTpyhop ──────────────────────────────────────────────────────

gtpyhop.declare_task_methods('aller_a_agent',       aller_a_agent_m)
gtpyhop.declare_task_methods('suivre',              suivre_m)
gtpyhop.declare_task_methods('maintenir_contact',   maintenir_contact_m)
gtpyhop.declare_task_methods('aller_a_position',    aller_a_position_m)
gtpyhop.declare_task_methods('orbiter',             orbiter_m)
gtpyhop.declare_task_methods('interposer',          interposer_m)

load_kb()
