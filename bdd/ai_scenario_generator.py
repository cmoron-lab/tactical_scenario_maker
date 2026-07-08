#!/usr/bin/env python3
"""
AI Scenario Generator — Create scenarios from natural language using Ollama.
Uses local LLM to parse requirements and generate agents, tasks, methods, conditions.
"""
import json
import re
import unicodedata
import requests
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

OLLAMA_URL = "http://localhost:11434/api/generate"
KB_PATH = Path(__file__).parent / "knowledge_base.json"

MAX_RETRIES = 1  # extra LLM calls allowed to self-correct an agent-count mismatch

_NUMBER_WORDS = {
    'un': 1, 'une': 1, 'deux': 2, 'trois': 3, 'quatre': 4, 'cinq': 5, 'six': 6,
    'sept': 7, 'huit': 8, 'neuf': 9, 'dix': 10,
    'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5,
    'seven': 7, 'eight': 8, 'nine': 9, 'ten': 10,
}
_AGENT_NOUNS = r'(?:agents?|bateaux?|navires?|drones?|usvs?|vaisseaux?|boats?|vessels?|robots?)'
_INTRUDER_KEYWORDS = [
    'intrus', 'intru', 'ennemi', 'ennemie', 'cible', 'menace', 'adversaire',
    'envahisseur', 'hostile', 'intruder', 'enemy', 'target', 'threat', 'trespasser',
]
_NEGATION_WORDS = r'\b(?:pas|aucun\w*|sans|jamais|ni|no|not|without|never|none)\b'

DEFAULT_MODEL = 'wamv'
# Spawnable vessel models (src/LOTUSim/assets/models/) — "landscape" and "seabed"
# are environment assets, not agents, so they're excluded on purpose. "cube" is
# used as a plain landmark model (e.g. a "__zone__" marker with no motion).
VALID_MODELS = {
    'wamv', 'fremm', 'pha', 'bluerov2_heavy', 'lrauv', 'x500', 'x500_base',
    'commando', 'dtmb_hull', 'mine', 'cube',
}

# Valid LOTUSim world zone (also documented in the prompt) — the LLM occasionally
# hallucinates a coordinate way outside this box (e.g. lat 4.89 instead of ~1.26),
# so every position is clamped into it rather than trusted verbatim.
LAT_RANGE = (1.20, 1.35)
LON_RANGE = (103.70, 103.85)

# The only top-level missions an acting agent can be assigned directly — every
# other task in knowledge_base.json (naviguer_vers_base, aller_a_agent, etc.) is
# an internal building block, not a meaningful scenario-level mission on its own.
_TOP_LEVEL_MISSIONS = {
    "veiller": "Veille passive, aucune action particulière.",
    "rentrer_a_la_base": "Retourne immédiatement à sa base.",
    "suivre_agent": "Suit/poursuit la cible ; rentre à la base une fois à moins de ~500m d'elle. "
                     "Nécessite un agent \"cible\" (role: \"intruder\") ailleurs dans le scénario.",
    "reconnaissance": "Identique à \"suivre_agent\", mais délègue à un drone compagnon si "
                       "conditions.drone_available=true et qu'un agent role:\"drone\" existe.",
    "surveiller_zone": "Se rend au centre d'une zone puis réagit (reconnaissance) si un contact "
                        "apparaît dans la zone, sinon veille. Nécessite un agent role:\"zone\".",
    "deploiement_drone": "Déploie directement le drone compagnon (rarement utilisé seul — "
                          "\"reconnaissance\" s'en charge déjà automatiquement).",
    "eviter": "S'approche de la cible puis, une fois trop proche (~1km), fait demi-tour vers sa "
              "base. Pour un évitement mutuel entre deux agents ordinaires, assigner \"eviter\" "
              "aux deux, chacun ayant l'autre comme \"cible\" (conditions.cible) — contrairement à "
              "\"suivre_agent\", ne nécessite PAS un agent role:\"intruder\".",
    "encercler": "S'approche de la cible puis, une fois assez proche (~1km), tourne en cercle "
                 "autour d'elle au lieu de faire demi-tour — pour \"tourne autour\"/\"fait des "
                 "cercles\"/\"orbite\". Même mécanique que \"eviter\" (conditions.cible, pas besoin "
                 "de role:\"intruder\") mais réaction différente une fois proche.",
}

_MISSION_KEYWORDS = [
    'patrouil', 'patrol', 'surveill', 'garde', 'guard', 'chasse', 'chase', 'base',
    'defend', 'defen', 'suivre', 'follow', 'poursuit', 'pursue', 'zone', 'secteur',
    'drone', 'reconnaissance', 'recon', 'rentr', 'retour', 'return', 'eviter', 'evite',
    'avoid', 'demi-tour', 'demi tour', 'recule', 'reculer', 'cercle', 'cercl', 'encercl',
    'orbit', 'tourne autour', 'circle',
]


def _clamp_coord(value: Tuple[float, float]) -> Tuple[float, float]:
    lat = max(LAT_RANGE[0], min(LAT_RANGE[1], value[0]))
    lon = max(LON_RANGE[0], min(LON_RANGE[1], value[1]))
    return lat, lon


def _normalize_model(value: Any) -> str:
    key = str(value or '').strip().lower()
    return key if key in VALID_MODELS else DEFAULT_MODEL


def _query_ollama(prompt: str, model: str = "mistral") -> str:
    """
    Query Ollama locally. Falls back gracefully if unavailable.
    Forces JSON-mode output and a low temperature for deterministic parsing.
    """
    try:
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.15},
            },
            timeout=90
        )
        response.raise_for_status()
        data = response.json()
        return data.get("response", "").strip()
    except requests.exceptions.ConnectionError:
        raise Exception(
            "Ollama not running. Install: https://ollama.ai\n"
            "Then: ollama serve\n"
            "Then download a model: ollama pull mistral"
        )
    except Exception as e:
        raise Exception(f"Ollama error: {str(e)}")


def _load_kb() -> Dict[str, Any]:
    """Load current knowledge base."""
    if KB_PATH.exists():
        with open(KB_PATH) as f:
            return json.load(f)
    return {
        "tasks": {},
        "leaf_tasks": {},
        "resolve_tokens": {},
    }


def _save_kb(kb: Dict[str, Any]) -> None:
    """Save updated knowledge base."""
    with open(KB_PATH, 'w') as f:
        json.dump(kb, f, indent=2)


def _extract_json_from_response(text: str) -> Dict[str, Any]:
    """
    Safely extract JSON from LLM response (which may contain extra text or markdown).
    """
    # Strip markdown code fences
    text = re.sub(r'```(?:json)?\s*', '', text).strip()

    # Find the first balanced { ... } block
    start = text.find('{')
    if start != -1:
        depth = 0
        for i, ch in enumerate(text[start:], start):
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except json.JSONDecodeError:
                        break

    # Last resort: try the whole text
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}


def _sanitize_parsed(parsed: Dict[str, Any], warnings: List[str]) -> None:
    """
    Mutates `parsed` in place so every downstream consumer (validation,
    agent-building, KB enrichment) can assume "agents" and "suggested_methods"
    are lists of dicts, never anything else — a 7B local model at low
    temperature still occasionally returns a list of bare strings instead of
    objects (e.g. "suggested_methods": ["eviter"]) for a freeform field like
    this one. Dropping the malformed entries (with a warning) keeps the rest
    of a still-usable response instead of crashing the whole generation on
    one bad field.
    """
    for key in ("agents", "suggested_methods"):
        raw = parsed.get(key)
        if not isinstance(raw, list):
            if raw is not None:
                warnings.append(f'IA : champ "{key}" invalide (attendu une liste) — ignoré.')
                parsed[key] = []
            continue
        kept = [item for item in raw if isinstance(item, dict)]
        if len(kept) != len(raw):
            warnings.append(
                f'IA : {len(raw) - len(kept)} élément(s) mal formé(s) dans "{key}" ignoré(s).'
            )
            parsed[key] = kept


def _ensure_agent_exists(kb: Dict[str, Any], agent_name: str, role: str = "") -> None:
    """Ensure agent is in resolve_tokens mapping."""
    if agent_name not in kb.get("resolve_tokens", {}):
        kb.setdefault("resolve_tokens", {})[agent_name] = agent_name
        if role and f"__{role}__" not in kb["resolve_tokens"]:
            kb["resolve_tokens"][f"__{role}__"] = agent_name


# ── Deterministic heuristics (don't rely on the LLM to count/detect) ─────────

def _expected_agent_count(description: str) -> Optional[int]:
    """
    Best-effort deterministic count of *acting* agents mentioned in the text
    (the intruder/target is not counted — it is handled separately).
    Returns None if the count can't be inferred confidently.
    """
    text = description.lower()

    named = set(re.findall(r'\b(?:agent|bateau|drone|usv|navire)[\s_]?(\d+)\b', text))
    if len(named) >= 2:
        return len(named)

    m = re.search(rf'\b(\d+)\s+{_AGENT_NOUNS}\b', text)
    if m:
        return int(m.group(1))

    for word, n in _NUMBER_WORDS.items():
        if re.search(rf'\b{word}\s+{_AGENT_NOUNS}\b', text):
            return n

    return None


def _mentions_intruder(description: str) -> bool:
    """
    True only if the text has at least one NON-negated intruder/threat mention.
    A plain substring search would treat "aucun intrus" or "sans menace" as
    requiring an intruder — checking for a negation word right before the
    keyword avoids forcing one into a scenario that explicitly says there isn't one.
    """
    text = description.lower()
    for kw in _INTRUDER_KEYWORDS:
        for m in re.finditer(re.escape(kw), text):
            window = text[max(0, m.start() - 30):m.start()]
            if not re.search(_NEGATION_WORDS, window):
                return True
    return False


_PASSIVE_AGENT_PATTERN = re.compile(
    # "ne fait/fais rien" (conjugated) AND "ne rien faire" (infinitive) — both
    # common orderings in French for "does/do nothing".
    r"ne\s+fai(?:s|t)\s+rien|ne\s+rien\s+fai(?:re|s|t)|ne\s+fait\s+aucune|"
    r"reste\s+(?:immobile|en\s+place|passif|sur\s+place)|"
    r"n['\s]agit\s+pas|ne\s+bouge\s+pas|(?<!\w)inactif|(?<!\w)passif|standby|"
    r"does\s+nothing|stays?\s+(?:put|still|idle)",
    re.IGNORECASE,
)


def _mentions_passive_agent(description: str) -> bool:
    """True if the text explicitly says at least one agent does nothing / stays put."""
    return bool(_PASSIVE_AGENT_PATTERN.search(description))


# Movement shapes/patterns with NO matching leaf task (bdd/tasks_methods.py) —
# "suggested_methods" can only SEQUENCE existing leaf tasks (aller_a_agent,
# aller_a_position, suivre, maintenir_contact, creation_agent, orbiter); it
# cannot invent a genuinely new motion primitive requiring live geometry (a
# square/spiral/zigzag path relative to a moving target), since JSON args are
# static tokens, not expressions — that needs real Python code (see
# orbiter_m). "cercle"/"circle"/"orbite" are deliberately NOT listed here —
# "encercler" already covers those.
_UNSUPPORTED_SHAPE_KEYWORDS = [
    'carre', 'carré', 'square', 'spirale', 'spiral', 'zigzag', 'triangle',
    'rectangle', 'etoile', 'étoile', 'star', 'figure en huit', 'figure-eight',
]


def _mentions_unsupported_shape(description: str) -> Optional[str]:
    """Returns the first unsupported shape keyword found, or None."""
    text = _strip_accents(description.lower())
    for kw in _UNSUPPORTED_SHAPE_KEYWORDS:
        if _strip_accents(kw) in text:
            return kw
    return None


_INTRUDER_NOUN_PATTERN = (
    r'(?:intrus\w*|ennemis?|cibles?|menaces?|adversaires?|envahisseurs?|'
    r'intruders?|enem(?:y|ies)|targets?|threats?|trespassers?)'
)


def _expected_intruder_count(description: str) -> int:
    """
    How many intruder/threat agents the text implies. 0 if none mentioned,
    otherwise at least 1 — reads an explicit count ("deux intrus", "3 enemy
    boats") the same way _expected_agent_count does for acting agents.
    """
    if not _mentions_intruder(description):
        return 0
    text = description.lower()
    m = re.search(rf'\b(\d+)\s+{_INTRUDER_NOUN_PATTERN}\b', text)
    if m:
        return max(1, int(m.group(1)))
    for word, n in _NUMBER_WORDS.items():
        if re.search(rf'\b{word}\s+{_INTRUDER_NOUN_PATTERN}\b', text):
            return n
    return 1


_METERS_PER_DEGREE = 111_320  # good enough at this world's latitude for a UI-level threshold

_DISTANCE_PATTERN = re.compile(
    r'(\d+(?:[.,]\d+)?)\s*(kilom[eè]tres?|km|m[eè]tres?|m)(?![a-zàâäéèêëïîôöùûüç])'
)


def _expected_avoid_distance_deg(description: str) -> Optional[float]:
    """
    Best-effort extraction of an explicit distance threshold from the text
    (e.g. "100m", "moins de 100 m", "500 mètres", "1km") — numeric precision
    is where the LLM is least reliable (same reasoning as _clamp_coord for
    positions), so this is computed deterministically from the raw text
    instead of trusted from the model's JSON output. Returns degrees, or
    None if no distance is mentioned.
    """
    m = _DISTANCE_PATTERN.search(description.lower().replace(',', '.'))
    if not m:
        return None
    value = float(m.group(1))
    unit = m.group(2)
    meters = value * 1000 if unit.startswith('k') else value
    return meters / _METERS_PER_DEGREE


def _strip_accents(text: str) -> str:
    return unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('ascii')


# "si <var> = <valeur> : <comportement>" / "if <var> = <value>: <behavior>" —
# one bullet per branch. Captured globally (not scoped to a specific agent
# name) since the LLM's own agent naming is what decides who's who; the
# caller matches branches to whichever acting agent isn't the passive one.
_BRANCH_LINE_PATTERN = re.compile(
    r'(?:^|[-*]\s*)(?:si|if)\s+(\w+)\s*=\s*(\S+?)\s*:\s*([^\n]+)',
    re.IGNORECASE | re.MULTILINE,
)

# Keyword -> built-in mission, used ONLY to map each branch's freeform
# behavior text to a mission that's known to actually work — matches
# _MISSION_KEYWORDS in spirit but resolves to a specific mission name instead
# of just "some keyword matched". First match wins; order matters (more
# specific phrases before generic ones sharing a substring).
_BRANCH_MISSION_KEYWORDS = [
    ('encercler', ['cercle', 'cercl', 'encercl', 'orbit', 'tourne autour']),
    ('eviter', ['demi-tour', 'demi tour', 'recule', 'eviter', 'evite', 'esquiv']),
    ('rentrer_a_la_base', ['retour a la base', 'rentre a la base', 'rentrer a la base', 'rentre a sa base']),
    ('suivre_agent', ['suit ', 'suivre', 'poursuit', 'pourchasse', 'chasse']),
    ('reconnaissance', ['reconnaissance', 'recon']),
    ('surveiller_zone', ['surveille la zone', 'surveiller la zone', 'surveille une zone']),
    ('deploiement_drone', ['deploie le drone', 'deploiement du drone', 'deploie son drone']),
    ('veiller', ['ne rien faire', 'rien faire', 'ne fait rien', 'reste immobile', 'reste sur place', 'veille']),
]


def _match_mission_for_branch_text(text: str) -> Optional[str]:
    norm = _strip_accents(text.lower())
    for mission, keywords in _BRANCH_MISSION_KEYWORDS:
        if any(_strip_accents(kw) in norm for kw in keywords):
            return mission
    return None


def _detect_conditional_mission_branches(
    description: str,
) -> Optional[Tuple[str, List[Tuple[str, str]]]]:
    """
    Deterministic detection of 2+ "si <var> = <valeur>: <comportement>"
    branches that ALL map to a known, working mission — the LLM is unreliable
    at spontaneously building this structure even when explicitly instructed
    (rule 10bis), consistently collapsing it to a single mission instead. So
    it's parsed and built here directly instead of trusted to the model, the
    same reasoning as _expected_agent_count/_expected_avoid_distance_deg.

    Returns (variable_name, [(value, mission_name), ...]), or None if fewer
    than 2 branches were found, they reference different variables (not one
    coherent branch set), or ANY branch's text doesn't map to a known
    mission — a partially-understood branch set is worse to guess at than to
    fall through to the normal LLM/refusal path (_mentions_unsupported_shape
    already refuses cleanly when a branch names an unsupported shape).
    """
    matches = _BRANCH_LINE_PATTERN.findall(description)
    if len(matches) < 2:
        return None
    variables = {m[0].strip().lower() for m in matches}
    if len(variables) != 1:
        return None
    branches = []
    for _, value, text in matches:
        mission = _match_mission_for_branch_text(text)
        if mission is None:
            return None
        branches.append((value.strip().lower(), mission))
    return next(iter(variables)), branches


def _has_actionable_signal(description: str) -> bool:
    """
    True only if the description says something about WHAT the agents should
    DO (a known mission keyword, or an intruder/threat to react to) — a bare
    agent count or name ("agent 1", "agent1") on its own says nothing about
    behavior and used to count as "signal", which let something like
    "test\nagent 1\nagent 2" (no behavior at all, just two numbered labels)
    through to the LLM. With nothing real to ground itself on, it invents a
    plausible-looking scenario anyway (and, given how much prompt real estate
    a mission like "eviter"/"encercler" occupies with worked examples, tends
    to anchor on whichever mission the prompt discusses most, regardless of
    fit) instead of admitting it doesn't know — so ask the user directly
    rather than call it at all whenever there's no behavioral signal.
    """
    if _mentions_intruder(description):
        return True
    text = _strip_accents(description.lower())
    return any(kw in text for kw in _MISSION_KEYWORDS)


def _is_intruder_agent(agent_data: Any) -> bool:
    if not isinstance(agent_data, dict):
        return False
    role = str(agent_data.get('role', '')).strip().lower()
    conditions = agent_data.get('conditions') or {}
    if not isinstance(conditions, dict):
        conditions = {}
    return role == 'intruder' or bool(conditions.get('is_intruder'))


def _is_drone_agent(agent_data: Any) -> bool:
    """A companion drone that tracks the cible on its own (mission "suivre_agent")."""
    if not isinstance(agent_data, dict):
        return False
    return str(agent_data.get('role', '')).strip().lower() == 'drone'


def _is_zone_agent(agent_data: Any) -> bool:
    """A "__zone__" landmark — a fixed position + radius, not a moving contact."""
    if not isinstance(agent_data, dict):
        return False
    role = str(agent_data.get('role', '')).strip().lower()
    conditions = agent_data.get('conditions') or {}
    if not isinstance(conditions, dict):
        conditions = {}
    return role == 'zone' or bool(conditions.get('is_zone'))


def _is_auxiliary_agent(agent_data: Dict[str, Any]) -> bool:
    """True for agents that don't count toward the user-requested acting-agent count."""
    return _is_intruder_agent(agent_data) or _is_drone_agent(agent_data) or _is_zone_agent(agent_data)


def _normalize_mission(value: Any, extra_valid_tasks: Optional[set] = None) -> Optional[str]:
    """
    Keep only the top-level task name if the LLM gave a full mission string —
    valid if it's one of the 6 built-in missions, OR (extra_valid_tasks) one of
    THIS SAME response's own "suggested_methods" task names (rule 10 in the
    prompt explicitly tells the LLM to assign the new task as the agent's
    mission directly; rejecting anything outside the fixed 6 would silently
    discard that and downgrade the agent to "veiller" even when the LLM did
    exactly what was asked).
    """
    if not isinstance(value, str) or not value.strip():
        return None
    task_name = value.strip().split()[0]
    if task_name in _TOP_LEVEL_MISSIONS:
        return task_name
    if extra_valid_tasks and task_name in extra_valid_tasks:
        return task_name
    return None


# ── Prompt construction & LLM parsing ─────────────────────────────────────────

def _build_prompt(description: str, expected_count: Optional[int],
                   intruder_count: int, feedback: Optional[str] = None) -> str:
    mission_list_str = "\n".join(f'  - "{k}": {v}' for k, v in _TOP_LEVEL_MISSIONS.items())

    count_rule = (
        f"The description clearly refers to exactly {expected_count} ACTING agent(s) "
        f"(this does NOT include the intruder/target, any companion drone, or a zone marker). "
        f"You MUST output exactly {expected_count} agent object(s) with role not in "
        f"(\"intruder\", \"drone\", \"zone\")."
        if expected_count is not None else
        "Count the acting agents mentioned in the description carefully — include EVERY one, "
        "no more, no less (do not count the intruder/target, a companion drone, or a zone "
        "marker as acting agents)."
    )

    if intruder_count > 0:
        intruder_rule = (
            f"The description describes {intruder_count} intruder/target/cible agent(s) that "
            f"other agents track. You MUST add EXACTLY {intruder_count} extra agent "
            f"object(s) for them (each a separate agent, uniquely named), each with \"role\": "
            f"\"intruder\" and \"conditions\": {{\"is_intruder\": true}}. Give each its own "
            f"\"mission\" (e.g. \"aller_a_position __self__ <lat> <lon>\") so it moves through the zone, "
            f"or \"veiller __self__\" if it stays still."
        )
    else:
        intruder_rule = (
            "If the description implies one or more intruders/targets/threats to track, add "
            "one extra agent PER threat, each with \"role\": \"intruder\" and \"conditions\": "
            "{\"is_intruder\": true}."
        )

    feedback_block = ""
    if feedback:
        feedback_block = f"\nCORRECTION NEEDED — your previous answer was wrong: {feedback}\n"

    return f"""You are a tactical scenario builder. Output ONLY a single valid JSON object — no prose, no markdown.

Scenario description: {description}

If — and only if — the description is too vague to safely build a scenario (e.g. it gives
no way at all to know how many agents are involved or what they should do), output instead:
{{
  "needs_clarification": true,
  "clarification_questions": ["question 1 in French", "question 2 in French"]
}}

Otherwise output this exact JSON structure (this shows the SHAPE only — every value below is a
placeholder to replace; do NOT copy these example values, they belong to an unrelated example scenario):
{{
  "scenario_name": "2_to_4_snake_case_words_describing_THIS_scenario",
  "agents": [
    {{"name": "<name>", "role": "patrol", "x": 1.260, "y": 103.750, "model": "wamv", "heading": 0,
      "velocity": 3, "conditions": {{}}, "mission": "veiller __self__"}}
  ],
  "mission": "veiller __self__"
}}

Rules (follow strictly):
1. scenario_name: 2-4 snake_case words describing WHAT HAPPENS in THIS specific scenario.
2. agents: {count_rule}
3. {intruder_rule}
4. mission: for EACH acting agent, pick EXACTLY ONE of these missions — never invent another
   task name, never combine several:
{mission_list_str}
   "__self__" is a placeholder for the agent's own name; every mission above is written exactly
   as "<task_name> __self__".
   - If mission is "reconnaissance", set this agent's "conditions": {{"drone_available": true}}
     ONLY if the description implies a companion drone should take over — and in that case ALSO
     add a separate agent object with "role": "drone", "mission": "suivre_agent __self__", and
     no "conditions" (it automatically tracks the same cible). If no drone is implied, omit
     "drone_available" and this agent behaves exactly like "suivre_agent".
   - If mission is "surveiller_zone", ALSO add a separate agent object with "role": "zone",
     "conditions": {{"is_zone": true}}, "model": "cube", "mission": "veiller __self__", positioned
     (x/y) at the center of the zone/area described. (The surveillance radius itself is a fixed
     system setting, not adjustable per scenario yet — position the zone agent sensibly, but do
     not try to encode a custom radius.)
   - "suivre_agent" and "reconnaissance" both require at least one "intruder" agent to exist in
     the scenario (see rule 3) — do not assign either mission if there is no cible to track.
   - "eviter" does NOT need an "intruder" agent — it tracks whichever other agent is nearest by
     default. For MUTUAL avoidance between two ordinary agents (both approach and both turn back),
     assign "eviter" to both. For ONE-SIDED avoidance (one agent explicitly does nothing / stays
     put, only the OTHER approaches and turns back), assign "eviter" ONLY to the one that moves —
     the passive one gets "veiller", never "eviter". Example: "Agent 1: ne fait rien. Agent 2: va
     vers agent 1 et fait demi-tour si trop proche." → agent1 mission "veiller __self__", agent2
     mission "eviter __self__". Do NOT give the passive agent "eviter" just because it's the other
     agent's target.
   - "encercler" works exactly like "eviter" (same "does NOT need intruder" / "one-sided vs mutual"
     / "passive agent gets veiller, never the active mission" rules above) — use it INSTEAD of
     "eviter" whenever the description says the moving agent circles/orbits/turns around the other
     once close, rather than turning back away from it. Never invent a new task for this — it
     already exists.
5. "conditions" is a free per-agent state dict — for acting agents, leave it {{}} empty UNLESS
   rule 4 says to set "drone_available".
6. Give each agent a unique x/y position (lat 1.25-1.30, lon 103.74-103.80).
7. model: pick the vessel type that best matches the description, from this exact list only —
   {sorted(VALID_MODELS)}. "wamv" (surface catamaran) is the default for anything not clearly a
   submarine/ROV (bluerov2_heavy, lrauv), a frigate (fremm), a helicopter carrier (pha), a
   quadcopter drone (x500, x500_base), or a static landmark (cube). Never invent a model name
   outside this list.
8. heading: compass heading in degrees (0=East, 90=North), only if the description implies a
   direction of travel; otherwise 0.
9. Never reuse the placeholder agent count, names, roles or coordinates verbatim — they must come
   from the actual description above.
10. If the description asks for behavior that genuinely doesn't fit ANY mission in rule 4 — do NOT
   force the closest-looking one — design a new task instead, via a top-level "suggested_methods"
   array (sibling of "agents"):
   [{{"task": "nom_de_la_tache", "description": "ce que ça fait", "preconditions": [...],
      "subtasks": [{{"task": "...", "args": ["__self__", ...]}}]}}, ...]
   You may add several entries (e.g. one task calling another). Every "subtasks[].task" must
   eventually reach one of: {", ".join(_TOP_LEVEL_MISSIONS)}, aller_a_agent, aller_a_position,
   suivre, maintenir_contact, creation_agent. Give this
   agent's own "mission" the new task's name directly (e.g. "nom_de_la_tache __self__").
   Preconditions can use ANY of these types:
   - {{"type": "state_equals", "variable": "x", "value": "y"}} — a condition you set yourself on
     this agent (in its own "conditions") equals y.
   - {{"type": "state_below"/"state_above", "variable": "x", "value": 5}} — numeric comparison.
   - {{"type": "state_present", "variable": "x"}} — true if "x" is set at all, any value.
   - {{"type": "distance_below"/"distance_above", "target": "__cible__", "threshold": 0.003}} —
     true if this agent's live distance to the resolved target is below/above threshold (degrees).
     "target" accepts "__cible__"/"__base_location__"/"__zone__"/"__any__" or a literal agent
     name — no separate setup needed, it's evaluated fresh every time from real positions.
   10bis. If the description says the SAME agent's behavior should depend on a variable's value
   ("si commande = cercle: ...; si commande = carré: ..."), that IS supported — it's exactly how
   the built-in "reconnaissance" mission already works (one method with
   {{"type": "state_equals", "variable": "drone_available", "value": "true"}}, a second method
   with no precondition as the fallback). Do it the same way: output SEVERAL "suggested_methods"
   entries that all share the SAME "task" name, one per branch, each with its own
   "state_equals"/"distance_..." precondition — they become separate METHODS of that one task,
   tried in the order you list them (put the unconditional fallback, if any, LAST). Set this
   agent's own "conditions" to whichever branch value applies for THIS scenario (e.g.
   "conditions": {{"commande": "cercle"}}) — preconditions read from the agent's own conditions,
   never from some outside "current command" input. Do NOT collapse multiple branches into a
   single method or silently drop the branches you can't implement (see rule 11) — build every
   branch you can as its own method, and if EVERY branch is unbuildable, use rule 11 instead.
11. If you genuinely cannot model this scenario — even with a new task above, e.g. it needs a
   capability with no matching leaf task (weapons, communications, sensors beyond distance/position,
   etc.) — do NOT invent something wrong or approximate. Output ONLY:
   {{"cannot_model": true, "reason": "explication concise en français de ce qui manque"}}
12. Do NOT output any text outside the JSON object.
{feedback_block}"""


def _parse_scenario_from_description(
    description: str, kb: Dict[str, Any], ignore_suggestion_validation: bool = False
) -> Tuple[Dict[str, Any], List[str]]:
    """
    Parse natural language description into structured scenario, self-correcting
    once if the acting-agent count doesn't match what the text clearly states.

    ignore_suggestion_validation: True when the caller already deterministically
    detected a "si <var> = X: ...; si <var> = Y: ..." branch set
    (_detect_conditional_mission_branches) that it's going to build itself,
    overriding whatever mission this response assigns — so whatever the LLM
    ALSO proposes in "suggested_methods" for that same behavior is irrelevant
    and shouldn't block generation just because it's malformed.

    Returns: (parsed_json, warnings)
    parsed_json may contain {"needs_clarification": True, "clarification_questions": [...]}
    instead of a scenario if the description is too ambiguous.
    """
    expected_count = _expected_agent_count(description)
    intruder_count = _expected_intruder_count(description)
    warnings: List[str] = []
    feedback = None
    parsed: Dict[str, Any] = {}

    for attempt in range(MAX_RETRIES + 1):
        prompt = _build_prompt(description, expected_count, intruder_count, feedback)
        response = _query_ollama(prompt, model="mistral")
        parsed = _extract_json_from_response(response)
        parsed["_raw_response"] = response

        if parsed.get("needs_clarification") or parsed.get("cannot_model"):
            return parsed, warnings

        _sanitize_parsed(parsed, warnings)

        agents = parsed.get("agents") or []
        acting = [a for a in agents if not _is_auxiliary_agent(a)]
        intruders = [a for a in agents if _is_intruder_agent(a)]
        # Task names THIS SAME response also defines via "suggested_methods" (rule 10) —
        # a valid mission target even though it's not one of the 6 built-ins.
        suggested_task_names = {
            s.get('task', '').strip()
            for s in (parsed.get('suggested_methods') or [])
            if isinstance(s, dict) and s.get('task', '').strip()
        }

        count_wrong = expected_count is not None and len(acting) != expected_count
        intruder_count_wrong = intruder_count > 0 and len(intruders) != intruder_count
        drone_without_cible = any(
            _is_drone_agent(a) and not intruders for a in agents
        )
        bad_mission = any(
            not _is_auxiliary_agent(a) and _normalize_mission(a.get('mission'), suggested_task_names) is None
            for a in acting
        )
        # The description explicitly says at least one agent does nothing, but no
        # acting agent actually got "veiller" — most often the LLM giving every
        # acting agent the SAME active mission instead of singling one out as
        # passive (e.g. inventing a symmetric "suggested_methods" task applied to
        # both, ignoring which one was supposed to stay put).
        missing_passive_agent = (
            len(acting) >= 2
            and _mentions_passive_agent(description)
            and not any(_normalize_mission(a.get('mission'), suggested_task_names) == 'veiller' for a in acting)
        )
        # Structural problems in any proposed "suggested_methods" entry (see
        # _validate_suggested_method) — e.g. a precondition checking distance to
        # "__self__", or a subtask with the wrong arg count / an unresolvable
        # "__token__". Left uncaught, these get written to knowledge_base.json as
        # a task that LOOKS legitimate but silently never fires.
        suggestion_problems = {
            s.get('task', '').strip(): _validate_suggested_method(s, kb, suggested_task_names)
            for s in (parsed.get('suggested_methods') or [])
            if isinstance(s, dict) and s.get('task', '').strip()
        }
        bad_suggestion = not ignore_suggestion_validation and any(
            probs for probs in suggestion_problems.values()
        )

        if (count_wrong or intruder_count_wrong or drone_without_cible or bad_mission
                or missing_passive_agent or bad_suggestion) and attempt < MAX_RETRIES:
            problems = []
            if count_wrong:
                problems.append(
                    f"you produced {len(acting)} acting agent(s) but the description requires "
                    f"exactly {expected_count}"
                )
            if intruder_count_wrong:
                problems.append(
                    f"you produced {len(intruders)} intruder agent(s) but the description "
                    f"requires exactly {intruder_count}"
                )
            if drone_without_cible:
                problems.append(
                    "you added a \"role\": \"drone\" agent but no \"intruder\" agent exists for "
                    "it to track — add one, or remove the drone agent"
                )
            if bad_mission:
                allowed = list(_TOP_LEVEL_MISSIONS) + sorted(suggested_task_names)
                problems.append(
                    f"every acting agent's \"mission\" must be exactly one of "
                    f"{allowed} followed by \" __self__\" — fix any agent whose mission "
                    f"doesn't match (a name from your own \"suggested_methods\" is fine too, "
                    f"as long as it's spelled exactly the same)"
                )
            if missing_passive_agent:
                problems.append(
                    "the description explicitly says at least one agent does NOTHING, but "
                    "you gave every acting agent the same active mission — pick exactly which "
                    "agent is the passive one and give ONLY that agent \"mission\": "
                    "\"veiller __self__\"; give the other(s) their real active mission "
                    "(e.g. \"eviter __self__\" targeting the passive agent), never invent a "
                    "new symmetric task that applies to both"
                )
            if bad_suggestion:
                for task_name, probs in suggestion_problems.items():
                    for p in probs:
                        problems.append(f'"suggested_methods" task "{task_name}": {p}')
            feedback = "; ".join(problems) + ". Regenerate the full JSON now with the exact counts stated above."
            continue

        break

    # Still broken after exhausting every retry: refuse instead of silently
    # substituting a fallback behavior (e.g. an agent quietly downgraded to
    # "veiller" because its real mission never resolved to anything that
    # would actually work) — a scenario that LOOKS complete but secretly
    # doesn't do what was asked is worse than a clear "can't do this".
    # count_wrong/intruder_count_wrong are NOT included here: those get a
    # deterministic, behavior-preserving fix downstream (_pad_missing_agents /
    # _make_default_intruder clone/synthesize an agent to match a headcount —
    # not a guess about what it should DO), unlike the cases below, which are
    # all "the requested behavior itself doesn't work".
    if bad_mission or missing_passive_agent or bad_suggestion or drone_without_cible:
        reasons = []
        if bad_mission:
            reasons.append("au moins un agent n'a pas de mission exploitable (ni une mission "
                            "prédéfinie, ni une tâche personnalisée correctement définie)")
        if missing_passive_agent:
            reasons.append("la description indique qu'au moins un agent ne fait rien, mais "
                            "aucun agent généré n'a la mission \"veiller\"")
        if bad_suggestion:
            broken = ", ".join(sorted(t for t, p in suggestion_problems.items() if p))
            reasons.append(f"la tâche personnalisée proposée (\"{broken}\") est mal formée et ne "
                            f"fonctionnerait pas telle quelle")
        if drone_without_cible:
            reasons.append("un agent drone a été proposé sans intrus/cible à suivre")
        return {
            "cannot_model": True,
            "reason": (
                f"Je n'ai pas réussi à générer un scénario qui fonctionne réellement pour cette "
                f"description après {MAX_RETRIES + 1} tentative(s) : " + "; ".join(reasons) + "."
            ),
        }, warnings

    if not parsed.get("agents"):
        parsed["agents"] = []
    if "mission" not in parsed:
        parsed["mission"] = ""

    return parsed, warnings


def _pad_missing_agents(agents: List[Dict[str, Any]], expected_count: int) -> List[Dict[str, Any]]:
    """
    Deterministic last-resort safety net: if the LLM still didn't produce enough
    acting agents after retrying, clone the last one to reach the required count
    instead of silently returning an incomplete scenario.
    """
    acting = [a for a in agents if not _is_auxiliary_agent(a)]
    if not acting or len(acting) >= expected_count:
        return agents

    template = acting[-1]
    while len(acting) < expected_count:
        idx = len(acting) + 1
        clone = json.loads(json.dumps(template))  # deep copy
        clone['name'] = f"agent{idx}"
        clone['x'] = float(clone.get('x', 0)) + 0.003 * idx
        clone['y'] = float(clone.get('y', 0)) + 0.003 * idx
        acting.append(clone)
        agents.append(clone)

    return agents


def _make_default_intruder(agents: List[Dict[str, Any]], index: int = 1) -> Dict[str, Any]:
    """Synthesize a plausible intruder/cible agent from the acting agents' positions."""
    xs = [float(a.get('x', 0)) for a in agents] or [1.26]
    ys = [float(a.get('y', 0)) for a in agents] or [103.75]
    cx, cy = sum(xs) / len(xs) + 0.004 * (index - 1), sum(ys) / len(ys) + 0.004 * (index - 1)
    dest = (cx + 0.03, cy + 0.02)
    name = "intrus" if index == 1 else f"intrus{index}"
    return {
        "name": name,
        "role": "intruder",
        "x": cx,
        "y": cy,
        "model": DEFAULT_MODEL,
        "heading": 0,
        "velocity": 4,
        "conditions": {"is_intruder": True},
        "mission": f"aller_a_position __self__ {dest[0]} {dest[1]}",
    }


# Tokens with a well-defined resolution path (bdd/tasks_methods.py::_resolve /
# _resolve_agent_token) — "__self__" plus every entry from resolve_tokens are
# always safe. Anything else shaped like "__xxx__" either matches a role/kind/
# "is_xxx" marker at runtime (fine, but not statically checkable here) or
# silently resolves to nothing / a coincidental literal string — the two
# failure modes behind every broken "suggested_methods" task seen so far
# ("dance": distance to "__self__" is always 0 → precondition never true;
# "avoidance": "__agent1__"/"__agent2__" match no role/marker → precondition
# always false, and the literal fallback only rescues subtask ARGS, not
# precondition targets, so the two behave inconsistently for the same typo).
_KNOWN_SPECIAL_TOKENS = {
    '__self__', '__cible__', '__base_location__', '__base_position__',
    '__destination__', '__zone__', '__drone__', '__any__', '__intruder__',
}


def _validate_suggested_method(
    suggestion: Dict[str, Any], kb: Dict[str, Any], sibling_task_names: set
) -> List[str]:
    """
    Structural sanity checks on one LLM-proposed "suggested_methods" entry.
    Catches the recurring failure modes in practice — a precondition checking
    an agent's distance to itself, a subtask calling a task with the wrong
    number of args for its real arity, or referencing an unregistered
    "__made_up_token__" — BEFORE it's written to knowledge_base.json, instead
    of discovering it later as a task that silently never does anything.
    Returns a list of human-readable problems; empty means it looks sound.
    """
    problems: List[str] = []
    leaf_tasks = kb.get('leaf_tasks', {}) or {}
    composite_tasks = set(kb.get('tasks', {}) or {}) | sibling_task_names
    known_tokens = set(_KNOWN_SPECIAL_TOKENS) | set(kb.get('resolve_tokens', {}) or {})

    def _is_bad_token(value: Any) -> bool:
        return (
            isinstance(value, str) and value.startswith('__') and value.endswith('__')
            and value not in known_tokens
        )

    for cond in suggestion.get('preconditions', []) or []:
        if not isinstance(cond, dict):
            problems.append('a precondition is not an object')
            continue
        if cond.get('type') in ('distance_below', 'distance_above'):
            target = cond.get('target')
            if target == '__self__':
                problems.append(
                    'a distance precondition targets "__self__" — distance to itself is '
                    'always 0, never a useful trigger; target another agent (e.g. "__cible__")'
                )
            elif _is_bad_token(target):
                problems.append(
                    f'precondition target "{target}" is not a recognized token (use '
                    f'"__cible__"/"__zone__"/"__drone__"/"__any__"/"__base_location__", or a '
                    f'literal agent name)'
                )

    for st in suggestion.get('subtasks', []) or []:
        if not isinstance(st, dict):
            problems.append('a subtask is not an object')
            continue
        task_name = str(st.get('task', '')).strip()
        args = st.get('args', []) or []
        if not isinstance(args, list):
            problems.append(f'subtask "{task_name}" has non-list "args"')
            continue
        if task_name in leaf_tasks:
            expected = len(leaf_tasks[task_name].get('args', []) or [])
            if expected and len(args) != expected:
                problems.append(
                    f'subtask "{task_name}" is a leaf task expecting {expected} arg(s), got {len(args)}'
                )
        elif task_name in composite_tasks or task_name in _TOP_LEVEL_MISSIONS:
            if args != ['__self__']:
                problems.append(
                    f'subtask "{task_name}" is a composite task — it always takes exactly '
                    f'["__self__"] as args (its OWN preconditions/subtasks then resolve the '
                    f'real target), got {args!r}'
                )
        for arg in args:
            if _is_bad_token(arg):
                problems.append(f'subtask "{task_name}" arg "{arg}" is not a recognized token')

    return problems


def _enrich_kb_with_methods(kb: Dict[str, Any], parsed: Dict[str, Any]) -> Dict[str, Any]:
    """
    Add new tasks and methods to KB based on parsed suggestions.
    Returns a summary of what was added.
    """
    updates = {
        "added_tasks": [],
        "added_methods": []
    }

    sibling_task_names = {
        s.get('task', '').strip()
        for s in (parsed.get('suggested_methods') or [])
        if isinstance(s, dict) and s.get('task', '').strip()
    }

    for suggestion in parsed.get("suggested_methods", []):
        if not isinstance(suggestion, dict):
            continue
        task_name = suggestion.get("task", "").strip()
        if not task_name:
            continue
        # Defense in depth — _parse_scenario_from_description already filters
        # broken suggestions out via _validate_suggested_method, but never write
        # one to the KB regardless of caller (e.g. a future path passing its own
        # existing_kb straight to this function).
        if _validate_suggested_method(suggestion, kb, sibling_task_names):
            continue

        tasks = kb.setdefault("tasks", {})
        is_new_task = task_name not in tasks

        # A task only ever has "label"/"methods" — "preconditions"/"subtasks" belong
        # to each individual method, never the task itself (matches the schema
        # bdd/tasks_methods.py::load_kb() actually reads).
        task_def = tasks.setdefault(task_name, {
            "label": suggestion.get("description", task_name),
            "methods": [],
        })

        if is_new_task:
            updates["added_tasks"].append(task_name)

        # Several suggestions can share the same "task" name — each becomes a
        # separate METHOD of that one composite task, exactly like the
        # built-in "reconnaissance" has 2 methods (state_equals
        # drone_available=true first, unconditional fallback last): that's
        # how a mission branches on a state variable (e.g. "si commande = X:
        # ...; si commande = Y: ..."). Method names must be unique per task —
        # a fixed "<task>_suggested_m" name would collide the moment a SECOND
        # branch for the same task came in, silently dropping it.
        existing_names = {m.get("name") for m in task_def.get("methods", [])}
        idx = 1
        method_name = f"{task_name}_suggested_m{idx}"
        while method_name in existing_names:
            idx += 1
            method_name = f"{task_name}_suggested_m{idx}"

        method = {
            "name": method_name,
            "preconditions": suggestion.get("preconditions", []),
            "subtasks": suggestion.get("subtasks", [])
        }
        methods_list = task_def.setdefault("methods", [])
        if method["preconditions"]:
            # GTPyhop tries methods IN ORDER and stops at the first one whose
            # precondition succeeds. A conditional method appended AFTER an
            # existing unconditional one (e.g. "encercler"'s own built-in
            # fallback "Hors de portée — approche", preconditions: []) would
            # never actually be reached — insert it before the first
            # unconditional method instead, so it's tried first like it should
            # be. An unconditional method being ADDED still goes at the very
            # end (it's the new fallback), same as before.
            insert_at = next(
                (i for i, m in enumerate(methods_list) if not m.get("preconditions")),
                len(methods_list),
            )
            methods_list.insert(insert_at, method)
        else:
            methods_list.append(method)
        updates["added_methods"].append({
            "task": task_name,
            "method": method_name
        })

        if not task_def.get("label"):
            task_def["label"] = suggestion.get("description", task_name)

    return updates


def generate_scenario_from_description(
    description: str,
    existing_kb: Optional[Dict[str, Any]] = None
) -> Tuple[Optional[Dict[str, Any]], List[str], Dict[str, Any], Optional[List[str]], Optional[str]]:
    """
    Main entry point: Generate scenario + KB updates from natural language.

    Args:
        description: User's natural language scenario description
        existing_kb: KB to enrich (None = load from disk)

    Returns:
        (scenario_dict_or_None, warnings_list, kb_updates, clarification_questions_or_None,
         refusal_reason_or_None)
        scenario_dict is None whenever clarification_questions or refusal_reason is set.
        refusal_reason means the model was asked and explicitly declined — never guessed.
    """
    kb = existing_kb or _load_kb()
    warnings: List[str] = []

    if not _has_actionable_signal(description):
        # Too vague for the LLM to ground itself on — it tends to hallucinate a
        # plausible-looking scenario rather than admit it doesn't know. Ask instead.
        return None, warnings, {}, [
            "Combien d'agents faut-il créer, et quel est le rôle de chacun ?",
            "Que doivent-ils faire précisément (veille, suivi, reconnaissance, surveillance de zone...) ?",
        ], None

    # Known-impossible requests — refuse before even calling the LLM (faster,
    # and avoids the LLM silently picking whichever shape/behavior it CAN do
    # and dropping the rest). NOTE: branching a mission on a state variable
    # (e.g. "si commande = X") is NOT refused here — the KB precondition
    # system already supports exactly that (see "reconnaissance": method 1
    # fires on state_equals drone_available=true, method 2 is the fallback;
    # rule 10bis in the prompt below tells the LLM to build new tasks the
    # same way). Only a genuinely missing movement PRIMITIVE is a hard stop.
    unsupported_shape = _mentions_unsupported_shape(description)
    if unsupported_shape:
        return None, warnings, {}, None, (
            f"Je ne peux pas modéliser ce scénario : aucune primitive de mouvement ne sait "
            f"tracer la forme demandée (\"{unsupported_shape}\") — seul un déplacement direct "
            f"vers un point/agent, ou un cercle (\"encercler\"), sont disponibles."
        )

    try:
        expected_count = _expected_agent_count(description)
        intruder_count = _expected_intruder_count(description)
        avoid_distance_deg = _expected_avoid_distance_deg(description)
        # Computed early: when set, the target agent's mission gets overridden
        # with a deterministically-built branching task further down, so
        # whatever the LLM ALSO proposes in "suggested_methods" for that same
        # behavior is irrelevant — don't let it block generation just because
        # it's malformed (see _parse_scenario_from_description's docstring).
        branch_detection = _detect_conditional_mission_branches(description)

        parsed, retry_warnings = _parse_scenario_from_description(
            description, kb, ignore_suggestion_validation=branch_detection is not None
        )
        warnings.extend(retry_warnings)

        # Task names this response also defines via "suggested_methods" — a valid
        # mission target for an acting agent, in addition to the 6 built-ins
        # (see _normalize_mission).
        suggested_task_names = {
            s.get('task', '').strip()
            for s in (parsed.get('suggested_methods') or [])
            if isinstance(s, dict) and s.get('task', '').strip()
        }

        if parsed.get("cannot_model"):
            reason = parsed.get("reason") or "Le modèle n'a pas précisé la raison."
            return None, warnings, {}, None, reason

        if parsed.get("needs_clarification"):
            questions = parsed.get("clarification_questions") or []
            if questions:
                return None, warnings, {}, questions, None

        agents_raw = parsed.get("agents") or []

        if not agents_raw and expected_count is None:
            # Total failure with no deterministic signal to fall back on — ask instead of guessing.
            return None, warnings, {}, [
                "Combien d'agents faut-il créer, et quel est le rôle de chacun ?",
                "Que doivent-ils faire précisément (veille, suivi, reconnaissance, surveillance de zone...) ?",
            ], None

        if expected_count is not None:
            agents_raw = _pad_missing_agents(agents_raw, expected_count)

        current_intruders = [a for a in agents_raw if _is_intruder_agent(a)]
        if intruder_count > len(current_intruders):
            missing = intruder_count - len(current_intruders)
            for i in range(missing):
                agents_raw.append(_make_default_intruder(agents_raw, index=len(current_intruders) + i + 1))
            warnings.append(
                f"{missing} agent(s) cible(s) manquant(s) dans la réponse de l'IA — ajouté(s) automatiquement."
            )

        if not agents_raw:
            raw = parsed.get("_raw_response", "")
            warnings.append(f"LLM returned no agents. Raw response (first 400 chars): {raw[:400]}")

        # Build agents dict
        agents = {}
        for agent_data in agents_raw:
            name = agent_data.get("name", "").strip()
            if not name:
                warnings.append("Skipped agent with no name")
                continue

            role = agent_data.get("role", "patrol") or "patrol"
            conditions = dict(agent_data.get("conditions", {}) or {})
            if role == "intruder":
                conditions.setdefault("is_intruder", True)
            if role == "zone":
                conditions.setdefault("is_zone", True)
            conditions.setdefault("role", role)

            x, y = _clamp_coord((float(agent_data.get("x", 0)) or 0.0, float(agent_data.get("y", 0)) or 0.0))
            conditions.setdefault("base_location", f"{x} {y}")

            try:
                heading = float(agent_data.get("heading", 0)) % 360
            except (TypeError, ValueError):
                heading = 0.0

            default_model = 'cube' if role == 'zone' else DEFAULT_MODEL
            agent_entry = {
                "role": role,
                "x": x,
                "y": y,
                "z": 0.0,
                # Only known LOTUSim assets are spawnable — anything else the LLM
                # invents (e.g. "boat") silently fails to spawn, so it's normalized here.
                "model": _normalize_model(agent_data.get("model") or default_model),
                "heading": heading,
                "velocity": float(agent_data.get("velocity", 5)) or 5.0,
                "conditions": conditions,
            }

            if _is_intruder_agent(agent_data):
                # Numeric destinations are where the LLM is least reliable — always
                # compute the escape mission ourselves instead of trusting its output,
                # unless the LLM explicitly said this cible stays still.
                if _normalize_mission(agent_data.get("mission")) == "veiller":
                    agent_entry["mission"] = "veiller __self__"
                    agent_entry["resolved_task"] = ["veiller"]
                else:
                    agent_entry["mission"] = f"aller_a_position __self__ {x + 0.03:.6f} {y + 0.02:.6f}"
                    agent_entry["resolved_task"] = ["aller_a_position"]
            elif _is_zone_agent(agent_data):
                agent_entry["mission"] = "veiller __self__"
                agent_entry["resolved_task"] = ["veiller"]
            elif _is_drone_agent(agent_data):
                agent_entry["mission"] = "suivre_agent __self__"
                agent_entry["resolved_task"] = ["suivre_agent"]
            else:
                mission_task = _normalize_mission(agent_data.get("mission"), suggested_task_names)
                if mission_task is None:
                    # Should be unreachable: _parse_scenario_from_description already
                    # refuses (cannot_model) whenever any acting agent's mission
                    # doesn't resolve. No silent "veiller" substitute here — surface
                    # it as a bug rather than quietly generating the wrong behavior.
                    raise Exception(
                        f'Agent "{name}" a une mission non résolue ("{agent_data.get("mission")}") — '
                        f'ceci ne devrait jamais arriver ici (bad_mission aurait dû être détecté plus tôt).'
                    )
                agent_entry["mission"] = f"{mission_task} __self__"
                agent_entry["resolved_task"] = [mission_task]
                # Description gave an explicit distance (e.g. "100m") — apply it to
                # this agent's "eviter"/"encercler" threshold instead of the KB-wide
                # default; never trust the LLM's own JSON for this number (see
                # _expected_avoid_distance_deg).
                if mission_task == "eviter" and avoid_distance_deg is not None:
                    conditions.setdefault("eviter_threshold", avoid_distance_deg)
                elif mission_task == "encercler" and avoid_distance_deg is not None:
                    conditions.setdefault("encercler_threshold", avoid_distance_deg)

            agents[name] = agent_entry
            _ensure_agent_exists(kb, name, role)

        # Pre-fill explicit "__cible__"/"__drone__"/"__zone__" resolution whenever
        # unambiguous (exactly one candidate) — left unset, the automatic
        # nearest-agent fallback (bdd/tasks_methods.py::_find_agent_by_pattern) can
        # latch onto an unrelated nearby agent (e.g. a drone's own companion patrol)
        # purely because of proximity, instead of the intended target. With more
        # than one candidate of a given role, the pairing is genuinely ambiguous
        # from the description alone, so it's left to the automatic resolver.
        intruder_names = [n for n, a in agents.items() if a['role'] == 'intruder']
        drone_names = [n for n, a in agents.items() if a['role'] == 'drone']
        zone_names = [n for n, a in agents.items() if a['role'] == 'zone']
        for aname, a in agents.items():
            mission_task = (a.get('resolved_task') or [None])[0]
            if mission_task in ('suivre_agent', 'reconnaissance') and len(intruder_names) == 1:
                a['conditions'].setdefault('cible', intruder_names[0])
            if mission_task in ('reconnaissance', 'deploiement_drone') and len(drone_names) == 1:
                a['conditions'].setdefault('drone', drone_names[0])
            if mission_task == 'surveiller_zone' and len(zone_names) == 1:
                a['conditions'].setdefault('zone', zone_names[0])
            if mission_task in ('eviter', 'encercler'):
                # Both target an ORDINARY agent, not a role-marked one — so their
                # "unambiguous" case is "exactly one other agent in the whole
                # scenario", computed per-agent (excluding itself and zone markers).
                others = [n for n in agents if n != aname and n not in zone_names]
                if len(others) == 1:
                    a['conditions'].setdefault('cible', others[0])

        # "si <var> = X: ...; si <var> = Y: ..." — the LLM reliably collapses this
        # to a single mission even when explicitly told how to build the
        # branching structure (rule 10bis), so it's constructed here directly
        # (branch_detection computed earlier, before the LLM call).  Applied to
        # whichever acting agent ISN'T the passive one — matches every example
        # seen so far (one passive agent, one branching agent); skipped (not
        # guessed at) if that pairing isn't unambiguous.
        branch_task_name = None
        if branch_detection is not None:
            variable, branches = branch_detection
            active_agents = [
                n for n, a in agents.items()
                if (a.get('resolved_task') or [None])[0] != 'veiller' and n not in zone_names
            ]
            if len(active_agents) == 1:
                target_name = active_agents[0]
                target = agents[target_name]
                branch_task_name = f"reagir_{variable}"
                methods = [
                    {
                        "name": f"{branch_task_name}_{value}",
                        "preconditions": [
                            {"type": "state_equals", "variable": variable, "value": value}
                        ],
                        "subtasks": [{"task": mission, "args": ["__self__"]}],
                    }
                    for value, mission in branches
                ]
                kb.setdefault("tasks", {})[branch_task_name] = {
                    "label": f"Réagit selon \"{variable}\" ("
                             + ", ".join(f"{v}→{m}" for v, m in branches) + ")",
                    "methods": methods,
                }
                target["mission"] = f"{branch_task_name} __self__"
                target["resolved_task"] = [branch_task_name]
                # Default to the first branch — "conditions.<var>" is a plain
                # per-scenario value (like eviter_threshold), not something that
                # changes live during a run; edit it in the scenario/KB editor to
                # switch which branch this agent actually takes.
                target["conditions"].setdefault(variable, branches[0][0])
                others = [n for n in agents if n != target_name and n not in zone_names]
                branch_missions = {m for _, m in branches}
                if len(others) == 1 and branch_missions & {
                    'eviter', 'encercler', 'suivre_agent', 'reconnaissance'
                }:
                    target["conditions"].setdefault('cible', others[0])
                if avoid_distance_deg is not None:
                    if 'eviter' in branch_missions:
                        target["conditions"].setdefault('eviter_threshold', avoid_distance_deg)
                    if 'encercler' in branch_missions:
                        target["conditions"].setdefault('encercler_threshold', avoid_distance_deg)

        # Enrich KB with new methods/tasks — skipped when the deterministic branch
        # builder above already handled this description: the LLM tends to ALSO
        # propose its own (redundant, sometimes clumsier) suggested_methods for
        # the very same "si commande = X" behavior, which would just clutter
        # built-in tasks like "encercler" with extra state_equals methods no
        # other scenario needs.
        if branch_task_name:
            kb_updates = {"added_tasks": [branch_task_name], "added_methods": []}
        else:
            kb_updates = _enrich_kb_with_methods(kb, parsed)
        _save_kb(kb)

        # Every acting agent already carries its own resolved mission (set above) —
        # this scenario-level field is only a display fallback, never LLM-authored.
        mission_list = ["veiller __self__"]

        # Use LLM-generated name if provided, otherwise build a fallback slug
        llm_name = parsed.get("scenario_name", "").strip()
        if llm_name:
            slug = re.sub(r'[^a-z0-9_]', '_', llm_name.lower()).strip('_')
        else:
            # Fallback: normalize accents then extract significant words
            def _normalize(text):
                return unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('ascii')
            _stop = {'le','la','les','un','une','des','de','du','et','ou','en','au','aux',
                     'qui','que','se','si','il','ils','elle','elles','je','tu','on','veux',
                     'veut','aimerais','souhaite','demande','faire','avoir','avec',
                     'the','a','an','of','in','to','for','with','and','or','is','are'}
            normalized = _normalize(description.lower())
            words = [w for w in re.sub(r'[^a-z0-9 ]', ' ', normalized).split()
                     if w not in _stop and len(w) > 2]
            slug = '_'.join(words[:4]) or 'scenario_ia'

        # Build scenario
        scenario = {
            "name": slug,
            "agents": agents,
            "mission": mission_list
        }

        return scenario, warnings, kb_updates, None, None

    except Exception as e:
        raise Exception(f"Scenario generation failed: {str(e)}")


def validate_scenario_completeness(
    scenario: Dict[str, Any],
    kb: Optional[Dict[str, Any]] = None
) -> Dict[str, List[str]]:
    """
    Check if all tasks/methods in scenario exist in KB.
    Returns: {missing_tasks, missing_methods, issues}
    """
    kb = kb or _load_kb()
    issues = {
        "missing_tasks": [],
        "missing_methods": [],
        "warnings": []
    }

    all_tasks = set(kb.get("tasks", {}).keys()) | set(kb.get("leaf_tasks", {}).keys())

    # Check mission — extract only the task name (first token), ignore args
    for mission_item in scenario.get("mission", []):
        if isinstance(mission_item, str):
            task_name = mission_item.strip().split()[0] if mission_item.strip() else ""
        elif isinstance(mission_item, (list, tuple)):
            task_name = mission_item[0] if mission_item else ""
        else:
            task_name = str(mission_item)
        if task_name and task_name not in all_tasks:
            issues["missing_tasks"].append(task_name)

    issues["missing_tasks"] = list(set(issues["missing_tasks"]))

    return issues


if __name__ == "__main__":
    # Quick test
    test_desc = "Un agent surveille une zone. Un drone prend le relais s'il repère un contact."
    print(f"Generating scenario from: {test_desc}\n")

    try:
        scenario, warnings, kb_updates, clarification, refusal = generate_scenario_from_description(test_desc)
        if refusal:
            print("✗ Refused:", refusal)
        elif clarification:
            print("? Clarification needed:", clarification)
        else:
            print("✓ Scenario generated:")
            print(json.dumps(scenario, indent=2))
            if warnings:
                print(f"\n⚠ Warnings: {warnings}")

            issues = validate_scenario_completeness(scenario)
            if issues["missing_tasks"]:
                print(f"\n⚠ Missing tasks: {issues['missing_tasks']}")

    except Exception as e:
        print(f"✗ Error: {e}")
