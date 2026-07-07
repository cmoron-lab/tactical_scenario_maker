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
}

_MISSION_KEYWORDS = [
    'patrouil', 'patrol', 'surveill', 'garde', 'guard', 'chasse', 'chase', 'base',
    'defend', 'defen', 'suivre', 'follow', 'poursuit', 'pursue', 'zone', 'secteur',
    'drone', 'reconnaissance', 'recon', 'rentr', 'retour', 'return',
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


def _strip_accents(text: str) -> str:
    return unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('ascii')


def _has_actionable_signal(description: str) -> bool:
    """
    True if the description gives at least one concrete, checkable fact to build
    a scenario from (an agent count, a named agent, an intruder, or a known mission
    keyword). If none of these are present, the text is too vague to trust the LLM
    with — it tends to hallucinate a plausible-looking scenario instead of admitting
    it doesn't know, so we ask the user directly rather than call it at all.
    """
    if _expected_agent_count(description) is not None:
        return True
    if _mentions_intruder(description):
        return True
    text = _strip_accents(description.lower())
    if re.search(r'\bagent\d+\b', text):
        return True
    return any(kw in text for kw in _MISSION_KEYWORDS)


def _is_intruder_agent(agent_data: Dict[str, Any]) -> bool:
    role = str(agent_data.get('role', '')).strip().lower()
    conditions = agent_data.get('conditions', {}) or {}
    return role == 'intruder' or bool(conditions.get('is_intruder'))


def _is_drone_agent(agent_data: Dict[str, Any]) -> bool:
    """A companion drone that tracks the cible on its own (mission "suivre_agent")."""
    return str(agent_data.get('role', '')).strip().lower() == 'drone'


def _is_zone_agent(agent_data: Dict[str, Any]) -> bool:
    """A "__zone__" landmark — a fixed position + radius, not a moving contact."""
    role = str(agent_data.get('role', '')).strip().lower()
    conditions = agent_data.get('conditions', {}) or {}
    return role == 'zone' or bool(conditions.get('is_zone'))


def _is_auxiliary_agent(agent_data: Dict[str, Any]) -> bool:
    """True for agents that don't count toward the user-requested acting-agent count."""
    return _is_intruder_agent(agent_data) or _is_drone_agent(agent_data) or _is_zone_agent(agent_data)


def _normalize_mission(value: Any) -> Optional[str]:
    """Keep only the top-level task name if the LLM gave a full mission string."""
    if not isinstance(value, str) or not value.strip():
        return None
    task_name = value.strip().split()[0]
    return task_name if task_name in _TOP_LEVEL_MISSIONS else None


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
11. If you genuinely cannot model this scenario — even with a new task above, e.g. it needs a
   capability with no matching leaf task (weapons, communications, sensors beyond distance/position,
   etc.) — do NOT invent something wrong or approximate. Output ONLY:
   {{"cannot_model": true, "reason": "explication concise en français de ce qui manque"}}
12. Do NOT output any text outside the JSON object.
{feedback_block}"""


def _parse_scenario_from_description(
    description: str
) -> Tuple[Dict[str, Any], List[str]]:
    """
    Parse natural language description into structured scenario, self-correcting
    once if the acting-agent count doesn't match what the text clearly states.

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

        agents = parsed.get("agents") or []
        acting = [a for a in agents if not _is_auxiliary_agent(a)]
        intruders = [a for a in agents if _is_intruder_agent(a)]

        count_wrong = expected_count is not None and len(acting) != expected_count
        intruder_count_wrong = intruder_count > 0 and len(intruders) != intruder_count
        drone_without_cible = any(
            _is_drone_agent(a) and not intruders for a in agents
        )
        bad_mission = any(
            not _is_auxiliary_agent(a) and _normalize_mission(a.get('mission')) is None
            for a in acting
        )

        if (count_wrong or intruder_count_wrong or drone_without_cible or bad_mission) \
                and attempt < MAX_RETRIES:
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
                problems.append(
                    f"every acting agent's \"mission\" must be exactly one of "
                    f"{list(_TOP_LEVEL_MISSIONS)} followed by \" __self__\" — fix any agent "
                    f"whose mission doesn't match"
                )
            feedback = "; ".join(problems) + ". Regenerate the full JSON now with the exact counts stated above."
            continue

        break

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


def _enrich_kb_with_methods(kb: Dict[str, Any], parsed: Dict[str, Any]) -> Dict[str, Any]:
    """
    Add new tasks and methods to KB based on parsed suggestions.
    Returns a summary of what was added.
    """
    updates = {
        "added_tasks": [],
        "added_methods": []
    }

    for suggestion in parsed.get("suggested_methods", []):
        task_name = suggestion.get("task", "").strip()
        if not task_name:
            continue

        method = {
            "name": f"{task_name}_suggested_m",
            "preconditions": suggestion.get("preconditions", []),
            "subtasks": suggestion.get("subtasks", [])
        }

        tasks = kb.setdefault("tasks", {})
        is_new_task = task_name not in tasks

        task_def = tasks.setdefault(task_name, {
            "label": suggestion.get("description", task_name),
            "methods": [],
            "subtasks": suggestion.get("subtasks", [])
        })

        if is_new_task:
            updates["added_tasks"].append(task_name)

        method_names = [m.get("name") for m in task_def.get("methods", [])]
        if method["name"] not in method_names:
            task_def.setdefault("methods", []).append(method)
            updates["added_methods"].append({
                "task": task_name,
                "method": method["name"]
            })

        if not task_def.get("label"):
            task_def["label"] = suggestion.get("description", task_name)

        if not task_def.get("subtasks"):
            task_def["subtasks"] = suggestion.get("subtasks", [])

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

    try:
        expected_count = _expected_agent_count(description)
        intruder_count = _expected_intruder_count(description)

        parsed, retry_warnings = _parse_scenario_from_description(description)
        warnings.extend(retry_warnings)

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
                mission_task = _normalize_mission(agent_data.get("mission")) or "veiller"
                agent_entry["mission"] = f"{mission_task} __self__"
                agent_entry["resolved_task"] = [mission_task]

            agents[name] = agent_entry
            _ensure_agent_exists(kb, name, role)

        # Enrich KB with new methods/tasks
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
