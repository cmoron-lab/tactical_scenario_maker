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
_ENCIRCLE_ROLE_HINTS = {
    'blockade': ['bloque', 'blocage', 'devant', 'avant', 'front', 'block'],
    'flank': ['flanc', 'côté', 'cote', 'flank', 'side'],
    'rear_guard': ['derrière', 'derriere', 'arrière', 'arriere', 'rear', 'behind'],
}

DEFAULT_MODEL = 'wamv'
# Spawnable vessel models (src/LOTUSim/assets/models/) — "landscape" and "seabed"
# are environment assets, not agents, so they're excluded on purpose.
VALID_MODELS = {
    'wamv', 'fremm', 'pha', 'bluerov2_heavy', 'lrauv', 'x500', 'x500_base',
    'commando', 'dtmb_hull', 'mine', 'cube',
}


def _normalize_model(value: Any) -> str:
    key = str(value or '').strip().lower()
    return key if key in VALID_MODELS else DEFAULT_MODEL

# Default KB structure for new items
DEFAULT_TASK_TEMPLATE = {
    "label": "",
    "subtasks": [],
    "methods": []
}

DEFAULT_METHOD_TEMPLATE = {
    "name": "",
    "preconditions": [],
    "subtasks": []
}

DEFAULT_LEAF_TASK = {
    "label": "",
    "type": "leaf"
}


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
        "event_triggers": []
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


_MISSION_KEYWORDS = [
    'patrouil', 'patrol', 'encercl', 'encircle', 'intercept', 'proteg', 'protect',
    'surveill', 'garde', 'guard', 'chasse', 'chase', 'base', 'defend', 'defen',
    'escort', 'suivre', 'follow', 'bloqu', 'block', 'flanc', 'flank',
]


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


def _guess_encircle_role(description: str, index: int, used_roles: List[str]) -> Optional[str]:
    """Guess an agent's encircle role from positional wording, falling back to index order."""
    text = description.lower()
    for role, hints in _ENCIRCLE_ROLE_HINTS.items():
        if role not in used_roles and any(h in text for h in hints):
            return role
    order = ['blockade', 'flank', 'rear_guard']
    for role in order:
        if role not in used_roles:
            return role
    return None


def _is_intruder_agent(agent_data: Dict[str, Any]) -> bool:
    role = str(agent_data.get('role', '')).strip().lower()
    conditions = agent_data.get('conditions', {}) or {}
    return role == 'intruder' or bool(conditions.get('is_intruder'))


_ROLE_ALIASES = {
    'blockade': 'blockade', 'block': 'blockade', 'front': 'blockade', 'blocking': 'blockade',
    'flank': 'flank', 'flanking': 'flank', 'side': 'flank',
    'rear_guard': 'rear_guard', 'rear': 'rear_guard', 'rear_blockade': 'rear_guard',
    'behind': 'rear_guard', 'back': 'rear_guard',
}


def _normalize_encircle_role(value: Any) -> Optional[str]:
    if not value:
        return None
    return _ROLE_ALIASES.get(str(value).strip().lower())


def _is_encircler(agent_data: Dict[str, Any]) -> bool:
    return str((agent_data.get('conditions') or {}).get('role_tactique', '')).strip().lower() == 'encercleur'


def _count_distinct_position_hints(description: str) -> int:
    """How many distinct encircling positions (front/flank/rear) the text mentions."""
    text = description.lower()
    return sum(1 for hints in _ENCIRCLE_ROLE_HINTS.values() if any(h in text for h in hints))


def _fix_encircle_roles(agents_raw: List[Dict[str, Any]], description: str) -> None:
    """Ensure agents with role_tactique="encercleur" get a unique, valid encircle_role."""
    encircle_agents = [a for a in agents_raw if not _is_intruder_agent(a) and _is_encircler(a)]
    if not encircle_agents:
        return

    used: List[str] = []
    for a in encircle_agents:
        cond = a.setdefault('conditions', {})
        role = _normalize_encircle_role(cond.get('encircle_role'))
        if role and role not in used:
            cond['encircle_role'] = role
            used.append(role)
        else:
            cond.pop('encircle_role', None)

    for a in encircle_agents:
        cond = a.setdefault('conditions', {})
        if not cond.get('encircle_role'):
            guessed = _guess_encircle_role(description, 0, used)
            if guessed:
                cond['encircle_role'] = guessed
                used.append(guessed)


# ── Prompt construction & LLM parsing ─────────────────────────────────────────

def _build_prompt(description: str, kb: Dict[str, Any], expected_count: Optional[int],
                   intruder_count: int, feedback: Optional[str] = None) -> str:
    existing_tasks = list(kb.get("tasks", {}).keys())
    existing_leaf = list(kb.get("leaf_tasks", {}).keys())
    task_labels = {k: v.get("label", k) for k, v in kb.get("tasks", {}).items()}
    task_list_str = "\n".join(f'  - "{k}": {task_labels[k]}' for k in existing_tasks)
    leaf_list_str = ", ".join(existing_leaf)

    count_rule = (
        f"The description clearly refers to exactly {expected_count} ACTING agent(s) "
        f"(this does NOT include the intruder/target). You MUST output exactly "
        f"{expected_count} agent object(s) with role != \"intruder\"."
        if expected_count is not None else
        "Count the acting agents mentioned in the description carefully — include EVERY one, "
        "no more, no less (do not count the intruder/target as an acting agent)."
    )

    if intruder_count > 0:
        intruder_rule = (
            f"The description describes {intruder_count} intruder/target/threat agent(s) that "
            f"the acting agents react to. You MUST add EXACTLY {intruder_count} extra agent "
            f"object(s) for them (each a separate agent, uniquely named), each with \"role\": "
            f"\"intruder\" and \"conditions\": {{\"is_intruder\": true}}. Give each its own "
            f"\"mission\" (e.g. \"aller __self__ <lat> <lon>\") so it moves through the zone."
        )
    else:
        intruder_rule = (
            "If the description implies one or more intruders/targets/threats, add one extra "
            "agent PER threat, each with \"role\": \"intruder\" and \"conditions\": "
            "{\"is_intruder\": true}."
        )

    feedback_block = ""
    if feedback:
        feedback_block = f"\nCORRECTION NEEDED — your previous answer was wrong: {feedback}\n"

    return f"""You are a tactical scenario builder. Output ONLY a single valid JSON object — no prose, no markdown.

Scenario description: {description}

REUSE these existing tasks (do not recreate them):
{task_list_str}

Available primitive subtasks: {leaf_list_str}

If — and only if — the description is too vague to safely build a scenario (e.g. it gives
no way at all to know how many agents are involved or what they should do), output instead:
{{
  "needs_clarification": true,
  "clarification_questions": ["question 1 in French", "question 2 in French"]
}}

Otherwise output this exact JSON structure (this shows the SHAPE only — the agent count,
names, roles and conditions are placeholders and must be replaced with what the actual
description above requires):
{{
  "scenario_name": "2_to_4_snake_case_words",
  "agents": [
    {{"name": "agent1", "role": "patrol", "x": 1.260, "y": 103.750, "model": "wamv", "heading": 0, "velocity": 3,
      "conditions": {{"role_tactique": "encercleur", "encircle_role": "blockade"}}, "mission": "operer __self__"}},
    {{"name": "agent2", "role": "patrol", "x": 1.265, "y": 103.755, "model": "wamv", "heading": 0, "velocity": 3,
      "conditions": {{"patrol_active": true}}, "mission": "operer __self__"}}
  ],
  "mission": "operer __self__"
}}

Rules (follow strictly):
1. scenario_name: describe WHAT happens, not the user request. Example: "patrouille_encerclement_port".
2. agents: {count_rule}
3. {intruder_rule}
4. mission: ALWAYS "operer __self__" for every acting agent — never any other task name.
   "operer" is the single generic entry point; the actual tactical behavior is chosen entirely
   through "conditions" (see rule 5). "__self__" is a placeholder for the agent's own name.
5. "conditions" is a free per-agent state dict merged into the agent at runtime. Set it to express
   what this agent actually does, based on what the description says — pick ONE case per agent:
   - Distinct positions around a target (one blocks the front, one takes a flank/side, one stays
     behind/rear) → {{"role_tactique": "encercleur", "encircle_role": "blockade"|"flank"|"rear_guard"}}
     matching the agent's described position.
   - Chase/pursue a target directly, no positioning → {{"role_tactique": "intercepteur"}}
   - Watch/observe a target without intervening → {{"role_tactique": "observateur"}}
   - Escort/protect another (non-intruder) agent → {{"soutien_requis": true}} — that other agent
     must exist among the acting agents (do not invent one).
   - Simple patrol/loop with no distinct roles → {{"patrol_active": true}}
   - Ordered to return to base from the start → {{"ordre_repli": true}}
   - Nothing else fits / passive watch only → {{}} (empty)
   Do not combine unrelated keys (e.g. don't set both "role_tactique" and "patrol_active" on the
   same agent unless the description genuinely describes both in sequence).
6. Give each agent a unique x/y position (lat 1.25-1.30, lon 103.74-103.80).
7. model: pick the vessel type that best matches the description, from this exact list only —
   {sorted(VALID_MODELS)}. "wamv" (surface catamaran) is the default for anything not clearly a
   submarine/ROV (bluerov2_heavy, lrauv), a frigate (fremm), a helicopter carrier (pha), or a
   quadcopter drone (x500, x500_base). Never invent a model name outside this list.
8. heading: compass heading in degrees (0=East, 90=North), only if the description implies a
   direction of travel; otherwise 0.
9. Never reuse the placeholder agent count, names, roles or coordinates verbatim — they must come
   from the actual description above.
10. Do NOT output any text outside the JSON object.
{feedback_block}"""


def _parse_scenario_from_description(
    description: str, kb: Dict[str, Any] = None
) -> Tuple[Dict[str, Any], List[str]]:
    """
    Parse natural language description into structured scenario, self-correcting
    once if the acting-agent count doesn't match what the text clearly states.

    Returns: (parsed_json, warnings)
    parsed_json may contain {"needs_clarification": True, "clarification_questions": [...]}
    instead of a scenario if the description is too ambiguous.
    """
    if kb is None:
        kb = _load_kb()

    expected_count = _expected_agent_count(description)
    intruder_count = _expected_intruder_count(description)
    warnings: List[str] = []
    feedback = None
    parsed: Dict[str, Any] = {}

    for attempt in range(MAX_RETRIES + 1):
        prompt = _build_prompt(description, kb, expected_count, intruder_count, feedback)
        response = _query_ollama(prompt, model="mistral")
        parsed = _extract_json_from_response(response)
        parsed["_raw_response"] = response

        if parsed.get("needs_clarification"):
            return parsed, warnings

        agents = parsed.get("agents") or []
        acting = [a for a in agents if not _is_intruder_agent(a)]
        intruders = [a for a in agents if _is_intruder_agent(a)]

        count_wrong = expected_count is not None and len(acting) != expected_count
        intruder_count_wrong = intruder_count > 0 and len(intruders) != intruder_count
        expected_encirclers = _count_distinct_position_hints(description)
        actual_encirclers = sum(1 for a in acting if _is_encircler(a))
        encircle_role_missing = expected_encirclers > 0 and actual_encirclers < expected_encirclers

        if (count_wrong or intruder_count_wrong or encircle_role_missing) and attempt < MAX_RETRIES:
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
            if encircle_role_missing:
                problems.append(
                    f"the description describes {expected_encirclers} distinct positions around a "
                    f"target (front/flank/rear) but only {actual_encirclers} of your agents has "
                    f"conditions.role_tactique=\"encercleur\" — assign it to EVERY agent described that way"
                )
            feedback = "; ".join(problems) + ". Regenerate the full JSON now with the exact counts stated above."
            continue

        break

    if not parsed.get("agents"):
        parsed["agents"] = []
    if "mission" not in parsed:
        parsed["mission"] = ""

    return parsed, warnings


def _pad_missing_agents(agents: List[Dict[str, Any]], expected_count: int,
                         description: str) -> List[Dict[str, Any]]:
    """
    Deterministic last-resort safety net: if the LLM still didn't produce enough
    acting agents after retrying, clone the last one to reach the required count
    instead of silently returning an incomplete scenario.
    """
    acting = [a for a in agents if not _is_intruder_agent(a)]
    if not acting or len(acting) >= expected_count:
        return agents

    used_roles = [a.get('conditions', {}).get('encircle_role') for a in acting if a.get('conditions')]
    used_roles = [r for r in used_roles if r]
    template = acting[-1]

    is_encircle = str(template.get('mission', '')).strip().split(' ')[0] == 'encircle_target'

    while len(acting) < expected_count:
        idx = len(acting) + 1
        clone = json.loads(json.dumps(template))  # deep copy
        clone['name'] = f"agent{idx}"
        clone['x'] = float(clone.get('x', 0)) + 0.003 * idx
        clone['y'] = float(clone.get('y', 0)) + 0.003 * idx
        if is_encircle:
            role = _guess_encircle_role(description, idx, used_roles)
            if role:
                clone.setdefault('conditions', {})['encircle_role'] = role
                used_roles.append(role)
        else:
            clone.get('conditions', {}).pop('encircle_role', None)
        acting.append(clone)
        agents.append(clone)

    return agents


def _make_default_intruder(agents: List[Dict[str, Any]], index: int = 1) -> Dict[str, Any]:
    """Synthesize a plausible intruder agent from the acting agents' positions."""
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
        "mission": f"aller __self__ {dest[0]} {dest[1]}",
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
) -> Tuple[Optional[Dict[str, Any]], List[str], Dict[str, Any], Optional[List[str]]]:
    """
    Main entry point: Generate scenario + KB updates from natural language.

    Args:
        description: User's natural language scenario description
        existing_kb: KB to enrich (None = load from disk)

    Returns:
        (scenario_dict_or_None, warnings_list, kb_updates, clarification_questions_or_None)
        scenario_dict is None exactly when clarification_questions is not None.
    """
    kb = existing_kb or _load_kb()
    warnings: List[str] = []

    if not _has_actionable_signal(description):
        # Too vague for the LLM to ground itself on — it tends to hallucinate a
        # plausible-looking scenario rather than admit it doesn't know. Ask instead.
        return None, warnings, {}, [
            "Combien d'agents faut-il créer, et quel est le rôle de chacun ?",
            "Que doivent-ils faire précisément (patrouille, interception, encerclement...) ?",
        ]

    try:
        expected_count = _expected_agent_count(description)
        intruder_count = _expected_intruder_count(description)

        parsed, retry_warnings = _parse_scenario_from_description(description, kb)
        warnings.extend(retry_warnings)

        if parsed.get("needs_clarification"):
            questions = parsed.get("clarification_questions") or []
            if questions:
                return None, warnings, {}, questions

        agents_raw = parsed.get("agents") or []

        if not agents_raw and expected_count is None:
            # Total failure with no deterministic signal to fall back on — ask instead of guessing.
            return None, warnings, {}, [
                "Combien d'agents faut-il créer, et quel est le rôle de chacun ?",
                "Que doivent-ils faire précisément (patrouille, interception, encerclement...) ?",
            ]

        if expected_count is not None:
            agents_raw = _pad_missing_agents(agents_raw, expected_count, description)

        current_intruders = [a for a in agents_raw if _is_intruder_agent(a)]
        if intruder_count > len(current_intruders):
            missing = intruder_count - len(current_intruders)
            for i in range(missing):
                agents_raw.append(_make_default_intruder(agents_raw, index=len(current_intruders) + i + 1))
            warnings.append(
                f"{missing} agent(s) intrus manquant(s) dans la réponse de l'IA — ajouté(s) automatiquement."
            )

        if not agents_raw:
            raw = parsed.get("_raw_response", "")
            warnings.append(f"LLM returned no agents. Raw response (first 400 chars): {raw[:400]}")

        # A small local LLM is unreliable about role values — repair them
        # deterministically (normalize/dedupe) rather than trust them verbatim.
        _fix_encircle_roles(agents_raw, description)

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
            conditions.setdefault("role", role)
            if conditions.get("encircle_role"):
                conditions["encircle_role"] = _normalize_encircle_role(conditions["encircle_role"])

            x = float(agent_data.get("x", 0)) or 0.0
            y = float(agent_data.get("y", 0)) or 0.0
            conditions.setdefault("base_location", f"{x} {y}")

            try:
                heading = float(agent_data.get("heading", 0)) % 360
            except (TypeError, ValueError):
                heading = 0.0

            agent_entry = {
                "role": role,
                "x": x,
                "y": y,
                "z": 0.0,
                # Only known LOTUSim assets are spawnable — anything else the LLM
                # invents (e.g. "boat") silently fails to spawn, so it's normalized here.
                "model": _normalize_model(agent_data.get("model")),
                "heading": heading,
                "velocity": float(agent_data.get("velocity", 5)) or 5.0,
                "conditions": conditions,
            }

            if _is_intruder_agent(agent_data):
                # Numeric destinations are where the LLM is least reliable — always
                # compute the escape mission ourselves instead of trusting its output.
                agent_entry["mission"] = f"aller __self__ {x + 0.03:.6f} {y + 0.02:.6f}"
            else:
                # "operer" is the single generic entry point — tactical intent lives
                # entirely in `conditions`, so the mission string is never LLM-authored.
                agent_entry["mission"] = "operer __self__"

            agents[name] = agent_entry
            _ensure_agent_exists(kb, name, role)

        # Enrich KB with new methods/tasks
        kb_updates = _enrich_kb_with_methods(kb, parsed)
        _save_kb(kb)

        # Every acting agent already carries its own "operer __self__" mission (set
        # above) — this scenario-level field is only a display fallback, never LLM-authored.
        mission_list = ["operer __self__"]

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

        return scenario, warnings, kb_updates, None

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
    test_desc = "Two drones patrol an area. When an intruder is detected, they intercept it."
    print(f"Generating scenario from: {test_desc}\n")

    try:
        scenario, warnings, kb_updates, clarification = generate_scenario_from_description(test_desc)
        if clarification:
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
