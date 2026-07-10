# Refactor tsm — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Post-implémentation (2026-07-10) :** plan exécuté intégralement (18 commits sur `refactor/tsm-layout`). Trois défauts DANS LE CODE DE CE PLAN ont été détectés par les reviews de tâches et corrigés — le code livré fait foi :
> 1. **Task 7** — le verrou du Planner était par instance ; `gtpyhop.current_domain` étant global au process, deux Planners concurrents pouvaient se rebinder le domaine en plein `find_plan`. Livré : verrou partagé module-level `_GTPYHOP_LOCK` (commit `e7a78b1`).
> 2. **Task 8** — `on_pose` était appelé sous le verrou du client : self-deadlock si le callback relit `get_pose`/`register_watch`. Livré : collecte sous verrou, notification hors verrou (commit `7a40b08`).
> 3. **Task 9** — `RunLogs()`/`LotusimClient()` étaient construits hors du try/finally : un échec de construction sautait `rclpy.shutdown()`. Livré : constructions dans le try, finally gardé par None (commit `28b3bdd`).
> S'ajoutent : un fix latent dans `methods._resolve` (garde `isinstance(str)` sur les args non-string, commit `d751586`) et l'exécution de T13 avec la procédure stash pour préserver des éditions utilisateur non commitées d'ARCHITECTURE.md.

**Goal :** Réorganiser le POC en paquet `tsm/` par couches (domaine / planification / exécution / adaptateur LOTUSim / web) avec un schéma canonique JSON de scénarios — iso-fonctionnel.

**Architecture :** Voir [le design](../specs/2026-07-10-tsm-refactor-design.md). Un paquet unique, une seule vraie frontière (`LotusimClient`), un `Planner` qui encapsule l'état global GTPyhop derrière un verrou, des scénarios en JSON versionné à la place des `.py` générés.

**Tech stack :** Python ≥ 3.10 (stdlib uniquement au runtime), GTPyhop vendored, rclpy/lotusim_msgs (fournis par l'environnement ROS du conteneur), uv + pytest + ruff + mypy pour l'outillage dev.

## Global Constraints

- **Branche de travail :** `refactor/tsm-layout`, créée depuis `main` à la tâche 1. Commits conventionnels, message = pourquoi. Jamais `--no-verify`.
- **Zéro dépendance runtime ajoutée** : la stdlib seulement. pytest/ruff/mypy vivent dans `[dependency-groups] dev` et s'exécutent via `uv run`.
- **Python cible ≥ 3.10** (celui du conteneur ROS). Chaque module de `tsm/` commence par `from __future__ import annotations`. Pas de syntaxe 3.11+.
- **Imports ROS confinés** : `rclpy`/`lotusim_msgs`/`geographic_msgs` au niveau module UNIQUEMENT dans `tsm/lotusim/client.py` (jamais importé par les tests ni par `tsm/web/`), et à l'intérieur des closures dans `make_commands`. Les tests doivent passer sur une machine sans ROS : `uv run pytest` ne doit jamais importer `tsm.lotusim` ni `tsm.execution.runtime`.
- **Vendor intact** : `tsm/vendor/gtpyhop.py` est une copie byte-identique de `gtpyhop.py` racine (vérifier par `diff`). Exclu de ruff et mypy.
- **Iso-fonctionnel — constantes à préserver verbatim** : `REPLAN_SAFETY_TIMEOUT = 5.0`, `POSITION_EPSILON_DEG = 1e-6`, `MIN_MOVE_DEG = 0.0003`, `ORBIT_ANGULAR_STEP = math.radians(35)`, `DEFAULT_ORBIT_RADIUS_DEG = 0.01`, `ORBIT_RADIUS_MARGIN = 0.9`, `INTERPOSE_FRACTION = 0.5`, `time.sleep(3.0)` entre spawns, `range_tolerance` 2 dans le SDF, timeouts `_wait` 10 s.
- **Sémantique GTPyhop à préserver** : les méthodes feuilles retournent `[]` (succès, rien à faire — garde d'idempotence) vs `False` (méthode inapplicable). Ne JAMAIS "simplifier" un `return []` en `return False` — voir le commentaire de `bdd/tasks_methods.py:303-316`, à transplanter avec le code.
- **Vérification finale end-to-end** : les tests unitaires passent sur le Mac ; le run réel (`main.py <scenario>` contre une instance LOTUSim dans le conteneur) est une vérification manuelle explicite, dite comme telle — jamais présumée.

## Modèles des sous-agents d'exécution

| Tâche | Modèle | Justification |
|---|---|---|
| 1, 4, 6, 12 | haiku | Mécanique, code fourni verbatim, vérification = commande |
| 2, 3, 5, 7, 8, 9, 10, 11, 13 | sonnet | Implémentation bien spécifiée, tests fournis |

---

### Task 1 : Squelette du paquet, pyproject, vendor

**Modèle : haiku**

**Files:**
- Create: `pyproject.toml`
- Create: `tsm/__init__.py`, `tsm/domain/__init__.py`, `tsm/planning/__init__.py`, `tsm/execution/__init__.py`, `tsm/lotusim/__init__.py`, `tsm/web/__init__.py`, `tsm/vendor/__init__.py`
- Create: `tsm/vendor/gtpyhop.py` (copie de `gtpyhop.py`)

**Interfaces:**
- Produces: le paquet importable `tsm`, `from tsm.vendor import gtpyhop`, `uv run pytest` fonctionnel.

- [ ] **Step 1 : Créer la branche**

```bash
git checkout -b refactor/tsm-layout
```

- [ ] **Step 2 : Écrire `pyproject.toml`**

```toml
[project]
name = "tactical-scenario-maker"
version = "0.1.0"
description = "Créateur de scénarios tactiques LOTUSim (POC)"
requires-python = ">=3.10"
dependencies = []

[dependency-groups]
dev = ["pytest>=8", "ruff>=0.4", "mypy>=1.10"]

[tool.uv]
package = false

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]

[tool.ruff]
line-length = 100
extend-exclude = ["tsm/vendor", "attic", "bdd", "gtpyhop.py", "visualize.py", "scenarios"]

[tool.mypy]
files = ["tsm"]
exclude = ["tsm/vendor"]
ignore_missing_imports = true

[[tool.mypy.overrides]]
module = "tsm.vendor.*"
ignore_errors = true

[[tool.mypy.overrides]]
module = ["tsm.domain.*", "tsm.planning.*"]
disallow_untyped_defs = true
disallow_incomplete_defs = true
check_untyped_defs = true
no_implicit_optional = true
warn_return_any = true
strict_equality = true
```

- [ ] **Step 3 : Créer les répertoires et `__init__.py`**

Tous les `__init__.py` sont vides sauf `tsm/__init__.py` :

```python
"""tsm — Tactical Scenario Maker, découpé par couches.

domain/     : schéma canonique des scénarios, doctrine HTN, géométrie
planning/   : encapsulation GTPyhop (Planner), méthodes HTN
execution/  : actions/commands, boucle agent, assemblage runtime
lotusim/    : adaptateur ROS vers LOTUSim (seul module qui importe rclpy)
web/        : API HTTP locale et serveur
vendor/     : GTPyhop 1.1 (Dana Nau, BSD-3-Clause-Clear) — ne pas modifier
"""
```

- [ ] **Step 4 : Vendorer gtpyhop**

```bash
cp gtpyhop.py tsm/vendor/gtpyhop.py
diff gtpyhop.py tsm/vendor/gtpyhop.py && echo IDENTIQUE
```

Expected: `IDENTIQUE` (aucune sortie de diff).

- [ ] **Step 5 : Vérifier l'import et la collecte pytest**

```bash
uv run python -c "from tsm.vendor import gtpyhop; print(type(gtpyhop.Domain))"
uv run pytest --collect-only -q
```

Expected: `<class 'type'>` (précédé de la bannière GTPyhop, tolérée) ; pytest collecte le test existant `tests/test_intruder_resolution.py` sans erreur d'import (il importe `bdd`, toujours présent à ce stade).

- [ ] **Step 6 : Commit**

```bash
git add pyproject.toml tsm/
git commit -m "chore: squelette du paquet tsm, outillage uv et vendor gtpyhop"
```

---

### Task 2 : Schéma canonique + store fichiers (`tsm/domain/scenario.py`)

**Modèle : sonnet**

**Files:**
- Create: `tsm/domain/scenario.py`
- Test: `tests/test_scenario_schema.py`

**Interfaces:**
- Produces (consommé par les tâches 4, 7, 9, 10) :
  - `ScenarioError(ValueError)`
  - `@dataclass Position(lat: float, lon: float)`
  - `@dataclass Mission(task: str, args: list[Any])` avec `to_htn_task() -> tuple[Any, ...]`
  - `@dataclass AgentSpec(position: Position, heading_deg: float, model: str, linear_velocity: tuple[float, float], angular_velocity_max: float, conditions: dict[str, Any], mission: Mission)`
  - `@dataclass Scenario(agents: dict[str, AgentSpec])` avec `Scenario.from_dict(doc: dict) -> Scenario` et `to_dict() -> dict`
  - Store : `list_scenarios(directory=SCENARIOS_DIR) -> list[str]`, `load_scenario(name, directory=...) -> Scenario`, `save_scenario(name, scenario, directory=...) -> None`, `delete_scenario(name, directory=...) -> None` ; `SCENARIOS_DIR`, `SCHEMA_VERSION = 1`

- [ ] **Step 1 : Écrire les tests**

```python
# tests/test_scenario_schema.py
import json

import pytest

from tsm.domain.scenario import (
    Mission, Scenario, ScenarioError,
    list_scenarios, load_scenario, save_scenario, delete_scenario,
)

DOC = {
    "version": 1,
    "agents": {
        "veilleur": {
            "position": {"lat": 1.26, "lon": 103.75},
            "heading_deg": 0.0,
            "model": "wamv",
            "velocity": {"linear": [0.0, 5.0], "angular_max": 0.05},
            "conditions": {"role": "patrol", "base_location": "1.260 103.750"},
            "mission": {"task": "veiller", "args": ["veilleur"]},
        }
    },
}


def test_round_trip():
    sc = Scenario.from_dict(DOC)
    assert sc.to_dict() == DOC


def test_agent_fields():
    sc = Scenario.from_dict(DOC)
    ag = sc.agents["veilleur"]
    assert ag.position.lat == 1.26 and ag.position.lon == 103.75
    assert ag.linear_velocity == (0.0, 5.0)
    assert ag.angular_velocity_max == 0.05


def test_mission_to_htn_task_converts_position_args():
    m = Mission(task="aller_a_position", args=["intrus", [1.28, 103.77]])
    assert m.to_htn_task() == ("aller_a_position", "intrus", (1.28, 103.77))


def test_bad_version_rejected():
    with pytest.raises(ScenarioError, match="version"):
        Scenario.from_dict({"version": 99, "agents": {}})


def test_missing_position_names_the_field():
    doc = json.loads(json.dumps(DOC))
    del doc["agents"]["veilleur"]["position"]
    with pytest.raises(ScenarioError, match="veilleur.*position"):
        Scenario.from_dict(doc)


def test_non_numeric_lat_rejected():
    doc = json.loads(json.dumps(DOC))
    doc["agents"]["veilleur"]["position"]["lat"] = "nord"
    with pytest.raises(ScenarioError, match="lat"):
        Scenario.from_dict(doc)


def test_store_round_trip(tmp_path):
    sc = Scenario.from_dict(DOC)
    save_scenario("demo", sc, directory=tmp_path)
    assert list_scenarios(directory=tmp_path) == ["demo"]
    assert load_scenario("demo", directory=tmp_path).to_dict() == DOC
    delete_scenario("demo", directory=tmp_path)
    assert list_scenarios(directory=tmp_path) == []


def test_store_rejects_path_traversal(tmp_path):
    with pytest.raises(ScenarioError, match="nom"):
        load_scenario("../etc/passwd", directory=tmp_path)
```

- [ ] **Step 2 : Vérifier qu'ils échouent**

Run: `uv run pytest tests/test_scenario_schema.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'tsm.domain.scenario'`

- [ ] **Step 3 : Implémenter**

```python
# tsm/domain/scenario.py
"""Schéma canonique des scénarios (v1) et accès fichiers.

Un scénario est un document JSON {"version": 1, "agents": {...}} ; son
identité est son nom de fichier (sans extension) dans scenarios/.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
SCENARIOS_DIR = Path(__file__).resolve().parents[2] / 'scenarios'
_NAME_RE = re.compile(r'^[A-Za-z0-9_-]+$')


class ScenarioError(ValueError):
    """Document de scénario invalide."""


def _num(doc: dict[str, Any], key: str, where: str) -> float:
    v = doc.get(key)
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        raise ScenarioError(f'{where}.{key} manquant ou non numérique')
    return float(v)


@dataclass
class Position:
    lat: float
    lon: float


@dataclass
class Mission:
    task: str
    args: list[Any] = field(default_factory=list)

    def to_htn_task(self) -> tuple[Any, ...]:
        """Tuple de tâche GTPyhop ; les args [lat, lon] deviennent des tuples."""
        return (self.task, *[tuple(a) if isinstance(a, list) else a for a in self.args])


@dataclass
class AgentSpec:
    position: Position
    heading_deg: float
    model: str
    linear_velocity: tuple[float, float]
    angular_velocity_max: float
    conditions: dict[str, Any]
    mission: Mission

    @classmethod
    def from_dict(cls, doc: dict[str, Any], where: str) -> AgentSpec:
        if not isinstance(doc, dict):
            raise ScenarioError(f'{where} doit être un objet')
        pos = doc.get('position')
        if not isinstance(pos, dict):
            raise ScenarioError(f'{where}.position manquant')
        vel = doc.get('velocity')
        if not isinstance(vel, dict):
            raise ScenarioError(f'{where}.velocity manquant')
        lin = vel.get('linear')
        if not (isinstance(lin, list) and len(lin) == 2
                and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in lin)):
            raise ScenarioError(f'{where}.velocity.linear doit être [min, max] numériques')
        mission = doc.get('mission')
        if not isinstance(mission, dict) or not isinstance(mission.get('task'), str):
            raise ScenarioError(f'{where}.mission.task manquant')
        args = mission.get('args', [])
        if not isinstance(args, list):
            raise ScenarioError(f'{where}.mission.args doit être une liste')
        model = doc.get('model')
        if not isinstance(model, str) or not model:
            raise ScenarioError(f'{where}.model manquant')
        conditions = doc.get('conditions', {})
        if not isinstance(conditions, dict):
            raise ScenarioError(f'{where}.conditions doit être un objet')
        return cls(
            position=Position(_num(pos, 'lat', f'{where}.position'),
                              _num(pos, 'lon', f'{where}.position')),
            heading_deg=_num(doc, 'heading_deg', where) if 'heading_deg' in doc else 0.0,
            model=model,
            linear_velocity=(float(lin[0]), float(lin[1])),
            angular_velocity_max=_num(vel, 'angular_max', f'{where}.velocity'),
            conditions=conditions,
            mission=Mission(task=mission['task'], args=list(args)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            'position': {'lat': self.position.lat, 'lon': self.position.lon},
            'heading_deg': self.heading_deg,
            'model': self.model,
            'velocity': {'linear': [self.linear_velocity[0], self.linear_velocity[1]],
                         'angular_max': self.angular_velocity_max},
            'conditions': self.conditions,
            'mission': {'task': self.mission.task, 'args': self.mission.args},
        }


@dataclass
class Scenario:
    agents: dict[str, AgentSpec]

    @classmethod
    def from_dict(cls, doc: dict[str, Any]) -> Scenario:
        if not isinstance(doc, dict):
            raise ScenarioError('le document doit être un objet JSON')
        if doc.get('version') != SCHEMA_VERSION:
            raise ScenarioError(f'version inconnue: {doc.get("version")!r} (attendu {SCHEMA_VERSION})')
        agents_doc = doc.get('agents')
        if not isinstance(agents_doc, dict):
            raise ScenarioError('agents manquant ou invalide')
        return cls(agents={
            name: AgentSpec.from_dict(a, where=f'agents.{name}')
            for name, a in agents_doc.items()
        })

    def to_dict(self) -> dict[str, Any]:
        return {'version': SCHEMA_VERSION,
                'agents': {name: a.to_dict() for name, a in self.agents.items()}}


# ── Store fichiers ────────────────────────────────────────────────────────────

def _path(name: str, directory: Path) -> Path:
    if not _NAME_RE.match(name):
        raise ScenarioError(f'nom de scénario invalide: {name!r}')
    return directory / f'{name}.json'


def list_scenarios(directory: Path = SCENARIOS_DIR) -> list[str]:
    return sorted(p.stem for p in directory.glob('*.json'))


def load_scenario(name: str, directory: Path = SCENARIOS_DIR) -> Scenario:
    path = _path(name, directory)
    if not path.exists():
        raise ScenarioError(f'scénario introuvable: {name}')
    with open(path, encoding='utf-8') as f:
        return Scenario.from_dict(json.load(f))


def save_scenario(name: str, scenario: Scenario, directory: Path = SCENARIOS_DIR) -> None:
    with open(_path(name, directory), 'w', encoding='utf-8') as f:
        json.dump(scenario.to_dict(), f, indent=2, ensure_ascii=False)
        f.write('\n')


def delete_scenario(name: str, directory: Path = SCENARIOS_DIR) -> None:
    path = _path(name, directory)
    if path.exists():
        path.unlink()
```

- [ ] **Step 4 : Vérifier que les tests passent**

Run: `uv run pytest tests/test_scenario_schema.py -q`
Expected: 9 passed

- [ ] **Step 5 : Commit**

```bash
git add tsm/domain/scenario.py tests/test_scenario_schema.py
git commit -m "feat: schéma canonique de scénario v1 et store JSON

Remplace la persistance par génération de code Python : un document
versionné, validé avec erreurs nommées, dont l'identité est le nom de
fichier."
```

---

### Task 3 : Géométrie et doctrine (`tsm/domain/geo.py`, `tsm/domain/doctrine.py`)

**Modèle : sonnet**

**Files:**
- Create: `tsm/domain/geo.py` (port typé de `bdd/utils.py`)
- Create: `tsm/domain/doctrine.py`
- Move: `bdd/knowledge_base.json` → `doctrine/knowledge_base.json` (git mv)
- Modify: `app.py:29` (constante `KB_PATH`), `bdd/tasks_methods.py:8` (`_KB_PATH`), `bdd/ai_scenario_generator.py:14` (`KB_PATH`) — pointer vers `doctrine/knowledge_base.json` pour que l'ancien monde continue de tourner pendant la transition
- Test: `tests/test_geo.py`

**Interfaces:**
- Produces : `tsm.domain.geo` : `MIN_MOVE_DEG = 0.0003`, `distance_deg(a, b) -> float`, `in_zone(a, b, radius) -> bool`, `agent_conditions(agent: dict) -> dict`, `check_condition(cond: dict, ag: dict) -> bool | None` — signatures et corps identiques à `bdd/utils.py:1-57`, seuls les type hints sont ajoutés.
- Produces : `tsm.domain.doctrine` : `KB_PATH = Path(__file__).resolve().parents[2] / 'doctrine' / 'knowledge_base.json'`, `load() -> dict[str, Any]`, `save(kb: dict[str, Any]) -> None` (json.dump `indent=2, ensure_ascii=False` + newline final).

- [ ] **Step 1 : Écrire le test**

```python
# tests/test_geo.py
from tsm.domain import doctrine
from tsm.domain.geo import agent_conditions, check_condition, distance_deg, in_zone


def test_distance_and_zone():
    a, b = {'lat': 1.0, 'lon': 2.0}, {'lat': 1.0, 'lon': 2.0003}
    assert abs(distance_deg(a, b) - 0.0003) < 1e-12
    assert in_zone(a, b, 0.001) and not in_zone(a, b, 0.0001)


def test_agent_conditions_prefers_conditions_over_legacy():
    assert agent_conditions({'conditions': {'role': 'x'}}) == {'role': 'x'}
    assert agent_conditions({'equipement': {'drone': 1}}) == {'drone_available': True}


def test_check_condition_state_equals_bool_coercion():
    assert check_condition({'type': 'state_equals', 'variable': 'v', 'value': 'true'}, {'v': True})
    assert check_condition({'type': 'distance_below'}, {}) is None  # cross-agent → au caller


def test_doctrine_loads_real_kb():
    kb = doctrine.load()
    assert 'tasks' in kb and 'resolve_tokens' in kb
```

- [ ] **Step 2 : Vérifier l'échec** — `uv run pytest tests/test_geo.py -q` → `ModuleNotFoundError`

- [ ] **Step 3 : Implémenter**

`tsm/domain/geo.py` : recopier `bdd/utils.py` intégralement (les corps de `distance_deg`, `in_zone`, `agent_conditions`, `check_condition` sont repris **verbatim**, docstrings incluses), ajouter `from __future__ import annotations` et les annotations : `def distance_deg(a: dict[str, float], b: dict[str, float]) -> float`, `def in_zone(a: dict[str, float], b: dict[str, float], radius: float) -> bool`, `def agent_conditions(agent: dict[str, Any]) -> dict[str, Any]`, `def check_condition(cond: dict[str, Any], ag: dict[str, Any]) -> bool | None`.

```python
# tsm/domain/doctrine.py
"""Propriétaire unique de la doctrine HTN (knowledge_base.json).

Un seul chemin, une seule sérialisation — trois constantes divergentes
pointaient sur ce fichier avant le refactor.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

KB_PATH = Path(__file__).resolve().parents[2] / 'doctrine' / 'knowledge_base.json'


def load() -> dict[str, Any]:
    with open(KB_PATH, encoding='utf-8') as f:
        return json.load(f)


def save(kb: dict[str, Any]) -> None:
    with open(KB_PATH, 'w', encoding='utf-8') as f:
        json.dump(kb, f, indent=2, ensure_ascii=False)
        f.write('\n')
```

Déplacement + retouches legacy :

```bash
mkdir -p doctrine && git mv bdd/knowledge_base.json doctrine/knowledge_base.json
```

Dans `app.py` ligne 29 : `KB_PATH = Path(__file__).parent / 'doctrine' / 'knowledge_base.json'`.
Dans `bdd/tasks_methods.py` ligne 8 : `_KB_PATH = Path(__file__).parent.parent / 'doctrine' / 'knowledge_base.json'`.
Dans `bdd/ai_scenario_generator.py` ligne 14 : même principe (`Path(__file__).parent.parent / 'doctrine' / 'knowledge_base.json'` — vérifier la forme actuelle de la constante avant de l'éditer).

- [ ] **Step 4 : Vérifier**

Run: `uv run pytest tests/test_geo.py tests/test_intruder_resolution.py -q`
Expected: tous passent (le test legacy prouve que l'ancien monde lit toujours la KB déplacée).

- [ ] **Step 5 : Commit**

```bash
git add -A
git commit -m "feat: domaine geo + doctrine propriétaire unique de la KB

knowledge_base.json quitte bdd/ pour doctrine/ ; les trois anciennes
constantes de chemin pointent dessus le temps de la transition."
```

---

### Task 4 : Migration des scénarios `.py` → `.json`

**Modèle : haiku**

**Files:**
- Create (temporaire): `scripts/migrate_scenarios.py`
- Create: `scenarios/*.json` (5 fichiers)
- Delete: `scenarios/*.py` (5 fichiers) et `scripts/migrate_scenarios.py` après exécution

**Interfaces:**
- Consumes: `tsm.domain.scenario.load_scenario` (tâche 2), `tsm.domain.geo.agent_conditions` (tâche 3).
- Produces: `scenarios/{2_agents_patrolling,demo_veille_drone_intru,deux_agents_cercle,evitement_mutuel,reconnaissance_drone}.json` au schéma v1.

Note transition : à partir d'ici, l'ANCIEN monde (UI web ET runtime pré-shim) ne trouve plus de scénarios — il cherche des `.py`. Assumé sur la branche : le runtime bascule en tâche 9, le web en tâches 10-11.

- [ ] **Step 1 : Écrire et exécuter le script**

```python
# scripts/migrate_scenarios.py
"""One-shot : convertit scenarios/*.py (AGENTS = {...}) au schéma canonique v1."""
import importlib
import json
from pathlib import Path

from tsm.domain.geo import agent_conditions

SCEN = Path('scenarios')

for py in sorted(SCEN.glob('*.py')):
    agents_in = importlib.import_module(f'scenarios.{py.stem}').AGENTS
    agents = {}
    for name, a in agents_in.items():
        mission = list(a['mission'])
        lin = a.get('linear_velocities_limits', (0.0, 5.0))
        agents[name] = {
            'position': {'lat': float(a['x']), 'lon': float(a['y'])},
            'heading_deg': float(a.get('heading', 0.0)),
            'model': a.get('model', 'wamv'),
            'velocity': {'linear': [float(lin[0]), float(lin[1])],
                         'angular_max': float(a.get('angular_velocities_limits', 0.05))},
            'conditions': agent_conditions(a),
            'mission': {'task': mission[0],
                        'args': [list(x) if isinstance(x, tuple) else x for x in mission[1:]]},
        }
    out = py.with_suffix('.json')
    out.write_text(json.dumps({'version': 1, 'agents': agents}, indent=2, ensure_ascii=False) + '\n',
                   encoding='utf-8')
    print(f'{py.stem}: {len(agents)} agents -> {out.name}')
```

Run: `uv run python scripts/migrate_scenarios.py`
Expected: 5 lignes `<nom>: N agents -> <nom>.json`

- [ ] **Step 2 : Vérifier que chaque JSON se charge par le schéma**

```bash
uv run python -c "
from tsm.domain.scenario import list_scenarios, load_scenario
names = list_scenarios()
assert len(names) == 5, names
for n in names:
    sc = load_scenario(n)
    print(n, sorted(sc.agents))
"
```

Expected: 5 lignes, chaque scénario avec ses agents. Comparer visuellement `demo_veille_drone_intru.json` avec le `.py` d'origine (3 agents, mission `suivre_agent` pour drone1, args `[['1.280', ...]]` ABSENT — l'arg position de l'intrus doit être `[1.28, 103.77]` numérique).

- [ ] **Step 3 : Supprimer les `.py` et le script, commit**

```bash
git rm scenarios/*.py && rm scripts/migrate_scenarios.py && rmdir scripts 2>/dev/null
git add scenarios/
git commit -m "feat: scénarios migrés au schéma canonique JSON v1

Les .json committés font foi ; le script de conversion one-shot ne
survit pas à la migration."
```

---

### Task 5 : Méthodes HTN (`tsm/planning/methods.py`)

**Modèle : sonnet**

**Files:**
- Create: `tsm/planning/methods.py` (port de `bdd/tasks_methods.py` — sans effet de bord d'import, sans global mutable)
- Test: `tests/test_methods.py` (remplace `tests/test_intruder_resolution.py`, qui est supprimé en tâche 12)

**Interfaces:**
- Consumes: `tsm.domain.geo` (`in_zone`, `MIN_MOVE_DEG`, `distance_deg`, `check_condition`), `tsm.vendor.gtpyhop`.
- Produces (consommé par la tâche 7 et 9) :
  - `register_builtin() -> None` — déclare les 6 méthodes feuilles dans `gtpyhop.current_domain`
  - `register_kb(kb: dict) -> None` — (ré)enregistre les méthodes issues de la KB ; nettoie d'abord les enregistrements précédents de chaque tâche KB
  - `collect_watched_tokens(kb, task_name, visited=None) -> set[str]` et `resolve_watched_agents(state, agent, tokens) -> set[str]` — signatures et corps **identiques** à `bdd/tasks_methods.py:261-300`
  - `_resolve(arg, agent, state, tokens)` et `_find_agent_by_pattern(state, pattern, agent=None)` — utilisés par les tests

**Le changement structurel du port** (tout le reste est verbatim) : le module-global `_resolve_tokens` disparaît. Le dict de tokens devient un paramètre explicite qui circule : `register_kb` le lit depuis `kb['resolve_tokens']` et le capture dans les closures.

- [ ] **Step 1 : Écrire les tests** (port des 3 cas existants + nouveau cas de reload)

```python
# tests/test_methods.py
from tsm.planning.methods import _resolve


def _state(agents):
    st = type('State', (), {})()
    st.agents = agents
    return st


def test_resolve_intruder_uses_marked_agent_name():
    state = _state({
        'usv': {'pos': {'lat': 1.0, 'lon': 2.0}},
        'ghost': {'pos': {'lat': 1.1, 'lon': 2.1}, 'is_intruder': True},
    })
    assert _resolve('__intruder__', 'usv', state, {}) == 'ghost'


def test_resolve_base_uses_marked_agent_name():
    state = _state({
        'usv': {'pos': {'lat': 1.0, 'lon': 2.0}},
        'dock': {'pos': {'lat': 1.2, 'lon': 2.2}, 'is_base': True},
    })
    assert _resolve('__base__', 'usv', state, {}) == 'dock'


def test_resolve_any_picks_nearest_other_agent():
    state = _state({
        'agent1': {'pos': {'lat': 1.26, 'lon': 103.75}},
        'far_boat': {'pos': {'lat': 1.40, 'lon': 103.90}},
        'near_boat': {'pos': {'lat': 1.261, 'lon': 103.751}},
    })
    assert _resolve('__any__', 'agent1', state, {}) == 'near_boat'


def test_resolve_token_mapping_from_kb():
    state = _state({
        'usv': {'pos': {'lat': 1.0, 'lon': 2.0}},
        'proie': {'pos': {'lat': 1.1, 'lon': 2.1}},
    })
    # __cible__ -> __any__ (mapping KB) -> agent le plus proche
    assert _resolve('__cible__', 'usv', state, {'__cible__': '__any__'}) == 'proie'
```

- [ ] **Step 2 : Vérifier l'échec** — `uv run pytest tests/test_methods.py -q` → `ModuleNotFoundError`

- [ ] **Step 3 : Implémenter le port**

Structure du fichier (les corps marqués *verbatim* sont recopiés de `bdd/tasks_methods.py` sans modification, docstrings et commentaires inclus — notamment le bloc "Idempotency guard convention" des lignes 303-316) :

```python
# tsm/planning/methods.py
"""Méthodes HTN : les 6 feuilles de mouvement + la traduction KB → GTPyhop.

Aucun effet de bord d'import : l'enregistrement dans le domaine se fait
explicitement via register_builtin()/register_kb(), appelés par le Planner
avec gtpyhop.current_domain déjà positionné.
"""
from __future__ import annotations

import math
from typing import Any

from tsm.domain.geo import MIN_MOVE_DEG, check_condition, distance_deg, in_zone
from tsm.vendor import gtpyhop

# ── Préconditions ── port verbatim de bdd/tasks_methods.py:13-58, avec le
# paramètre tokens ajouté :
def _check(cond, agent, state, tokens):
    ...  # corps verbatim ; l'appel interne devient
         # _resolve_agent_token(state, agent, cond.get('target', ''), tokens)

# ── Résolution ──
# _nearest_agent(state, agent, candidates)        : verbatim (l.66-84)
# _find_agent_by_pattern(state, pattern, agent)   : verbatim (l.87-125)

def _resolve_agent_token(state, agent, token, tokens):
    ...  # verbatim l.128-149, sauf : pattern = tokens.get(token, token)

def _resolve(arg, agent, state, tokens):
    ...  # verbatim l.152-210, sauf l'appel: _resolve_agent_token(..., tokens)

def _make_method(preconditions, subtasks, tokens):
    def method(state, agent):
        for cond in preconditions:
            if not _check(cond, agent, state, tokens):
                return False
        return [
            tuple([st['task']] + [_resolve(a, agent, state, tokens) for a in st.get('args', [])])
            for st in subtasks
        ]
    return method

# ── Méthodes feuilles ── verbatim l.303-435 : aller_a_agent_m, suivre_m,
# maintenir_contact_m, aller_a_position_m, orbiter_m, interposer_m, avec
# leurs constantes ORBIT_ANGULAR_STEP, DEFAULT_ORBIT_RADIUS_DEG,
# ORBIT_RADIUS_MARGIN, INTERPOSE_FRACTION et TOUS leurs commentaires.

def register_builtin() -> None:
    """Déclare les méthodes feuilles dans gtpyhop.current_domain."""
    gtpyhop.declare_task_methods('aller_a_agent', aller_a_agent_m)
    gtpyhop.declare_task_methods('suivre', suivre_m)
    gtpyhop.declare_task_methods('maintenir_contact', maintenir_contact_m)
    gtpyhop.declare_task_methods('aller_a_position', aller_a_position_m)
    gtpyhop.declare_task_methods('orbiter', orbiter_m)
    gtpyhop.declare_task_methods('interposer', interposer_m)


def register_kb(kb: dict[str, Any]) -> None:
    """(Ré)enregistre les méthodes de la KB dans gtpyhop.current_domain."""
    tokens = dict(kb.get('resolve_tokens', {}))
    for task_name, task_def in kb['tasks'].items():
        # declare_task_methods ACCUMULE (comportement upstream voulu pour
        # étaler les déclarations, pas pour recharger) : sans ce pop dans le
        # dict privé, chaque rechargement de KB empilerait un doublon de
        # chaque méthode. Seul accès aux internes de gtpyhop du paquet.
        gtpyhop.current_domain._task_method_dict.pop(task_name, None)
        methods = []
        for i, m in enumerate(task_def['methods']):
            fn = _make_method(m['preconditions'], m['subtasks'], tokens)
            fn.__name__ = f'm_{task_name}_{i}'
            methods.append(fn)
        if methods:
            gtpyhop.declare_task_methods(task_name, *methods)

# collect_watched_tokens / resolve_watched_agents : verbatim l.261-300.
```

L'implémenteur recopie les corps *verbatim* depuis `bdd/tasks_methods.py` (le fichier est dans le repo) en appliquant UNIQUEMENT les deltas listés : paramètre `tokens` sur `_check`/`_resolve_agent_token`/`_resolve`/`_make_method`, import depuis `tsm.domain.geo` et `tsm.vendor`, suppression du global `_resolve_tokens`, de `load_kb()` (remplacé par `register_kb(kb)` sans I/O) et des `declare_task_methods` top-level (remplacés par `register_builtin()`).

- [ ] **Step 4 : Vérifier**

Run: `uv run pytest tests/test_methods.py -q`
Expected: 4 passed. (Les `register_*` sont couverts par les tests du Planner, tâche 7.)

- [ ] **Step 5 : Commit**

```bash
git add tsm/planning/methods.py tests/test_methods.py
git commit -m "feat: port des méthodes HTN sans effet de bord d'import

Le dict resolve_tokens cesse d'être un global de module : il circule en
paramètre et se capture dans les closures à l'enregistrement."
```

---

### Task 6 : Actions et commands (`tsm/execution/actions.py`)

**Modèle : haiku**

**Files:**
- Create: `tsm/execution/actions.py`
- Test: `tests/test_actions.py`

**Interfaces:**
- Produces (consommé par les tâches 7, 9, 10) :
  - `aller_a(state, agent, pos)` et `creation_agent(state, agent, drone)` — actions pures, corps verbatim de `bdd/primitives_actions.py:50-54` et `82-104` (docstring de `creation_agent` incluse)
  - `make_commands(client, logs) -> tuple` — retourne `(c_aller_a,)` ; `client` et `logs` sont duck-typés (aucun import de `tsm.lotusim` ici)

- [ ] **Step 1 : Test**

```python
# tests/test_actions.py
from tsm.execution.actions import aller_a, creation_agent, make_commands


def _state():
    st = type('State', (), {})()
    st.agents = {'usv': {'pos': {'lat': 1.0, 'lon': 2.0}, 'last_waypoint': None},
                 'dr1': {}}
    return st


def test_aller_a_updates_state():
    st = aller_a(_state(), 'usv', (1.5, 2.5))
    assert st.agents['usv']['pos'] == {'lat': 1.5, 'lon': 2.5}
    assert st.agents['usv']['last_waypoint'] == (1.5, 2.5)


def test_creation_agent_marks_both():
    st = creation_agent(_state(), 'usv', 'dr1')
    assert st.agents['usv']['deployed_drone'] == 'dr1'
    assert st.agents['dr1']['drone_deployed'] is True


def test_make_commands_c_aller_a_uses_client_and_logs():
    calls = []
    client = type('C', (), {'set_waypoints': lambda self, a, lat, lon: calls.append(('wp', a, lat, lon))})()
    logs = type('L', (), {'log_waypoint': lambda self, a, lat, lon: calls.append(('log', a, lat, lon))})()
    (c_aller_a,) = make_commands(client, logs)
    assert c_aller_a.__name__ == 'c_aller_a'  # requis par le lookup 'c_' + action
    st = c_aller_a(_state(), 'usv', (1.5, 2.5))
    assert ('wp', 'usv', 1.5, 2.5) in calls and ('log', 'usv', 1.5, 2.5) in calls
    assert st.agents['usv']['last_waypoint'] == (1.5, 2.5)
```

- [ ] **Step 2 : Vérifier l'échec** — `uv run pytest tests/test_actions.py -q` → `ModuleNotFoundError`

- [ ] **Step 3 : Implémenter**

```python
# tsm/execution/actions.py
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


def creation_agent(state: Any, agent: str, drone: str) -> Any:
    # docstring et corps verbatim de bdd/primitives_actions.py:82-104
    ...


def make_commands(client: Any, logs: Any) -> tuple[Any, ...]:
    def c_aller_a(state: Any, agent: str, pos: Any) -> Any:
        """Command : envoie le waypoint à LOTUSim et met à jour le state."""
        client.set_waypoints(agent, pos[0], pos[1])
        logs.log_waypoint(agent, pos[0], pos[1])
        state.agents[agent]['pos'] = {'lat': pos[0], 'lon': pos[1]}
        state.agents[agent]['last_waypoint'] = pos
        return state

    return (c_aller_a,)
```

- [ ] **Step 4 : Vérifier** — `uv run pytest tests/test_actions.py -q` → 3 passed

- [ ] **Step 5 : Commit**

```bash
git add tsm/execution/actions.py tests/test_actions.py
git commit -m "feat: actions pures et factory de commands — mort de l'import circulaire

Les dépendances (client ROS, logs) arrivent par closure au lieu du
hack 'import main' + sys.modules."
```

---

### Task 7 : Planner (`tsm/planning/planner.py`)

**Modèle : sonnet**

**Files:**
- Create: `tsm/planning/planner.py`
- Test: `tests/test_planner.py`

**Interfaces:**
- Consumes: `tsm.planning.methods.register_builtin/register_kb`, `tsm.vendor.gtpyhop`, `tsm.domain.scenario.Scenario`, `tsm.execution.actions` (dans les tests).
- Produces (consommé par les tâches 9, 10) :
  - `class Planner: __init__(self, kb: dict, actions: tuple = (), commands: tuple = ())`, `find_plan(self, state, task: tuple) -> list | bool`, `run_commands(self, state, plan: list) -> None`, `reload_kb(self, kb: dict) -> None`
  - `build_state(scenario: Scenario) -> gtpyhop.State` — état initial complet (pos, available, intruder_nearby, last_waypoint, conditions avec coercition 'true'/'false' → bool, position_history)

- [ ] **Step 1 : Tests**

```python
# tests/test_planner.py
from tsm.domain.scenario import Scenario
from tsm.execution.actions import aller_a, creation_agent
from tsm.planning.planner import Planner, build_state

KB = {
    'resolve_tokens': {},
    'tasks': {
        'patrouille': {'methods': [{
            'name': 'aller au point',
            'preconditions': [],
            'subtasks': [{'task': 'aller_a_position', 'args': ['__self__', [1.25, 103.75]]}],
        }]},
    },
}

DOC = {'version': 1, 'agents': {'usv': {
    'position': {'lat': 1.26, 'lon': 103.75}, 'heading_deg': 0.0, 'model': 'wamv',
    'velocity': {'linear': [0.0, 5.0], 'angular_max': 0.05},
    'conditions': {'role': 'patrol', 'actif': 'true'},
    'mission': {'task': 'patrouille', 'args': ['usv']},
}}}


def _planner():
    return Planner(KB, actions=(aller_a, creation_agent))


def test_build_state_coerces_bool_strings():
    st = build_state(Scenario.from_dict(DOC))
    assert st.agents['usv']['actif'] is True
    assert st.agents['usv']['pos'] == {'lat': 1.26, 'lon': 103.75}
    assert st.position_history == {}


def test_find_plan_decomposes_kb_task():
    p = _planner()
    st = build_state(Scenario.from_dict(DOC))
    plan = p.find_plan(st, ('patrouille', 'usv'))
    assert plan == [('aller_a', 'usv', [1.25, 103.75])]


def test_find_plan_idempotency_guard_returns_empty_plan():
    p = _planner()
    st = build_state(Scenario.from_dict(DOC))
    st.agents['usv']['last_waypoint'] = (1.25, 103.75)  # déjà en route
    assert p.find_plan(st, ('patrouille', 'usv')) == []


def test_two_planners_do_not_share_methods():
    # NB : find_plan sur une tâche inconnue LÈVE dans gtpyhop (il ne retourne
    # pas False) — l'isolation se vérifie sur les domaines eux-mêmes.
    p1 = _planner()
    p2 = Planner({'resolve_tokens': {}, 'tasks': {}}, actions=(aller_a,))
    assert 'patrouille' in p1._domain._task_method_dict
    assert 'patrouille' not in p2._domain._task_method_dict
    st = build_state(Scenario.from_dict(DOC))
    assert p1.find_plan(st, ('patrouille', 'usv')) == [('aller_a', 'usv', [1.25, 103.75])]


def test_reload_kb_replaces_methods_without_accumulation():
    p = _planner()
    st = build_state(Scenario.from_dict(DOC))
    for _ in range(3):
        p.reload_kb(KB)
    task_methods = p._domain._task_method_dict['patrouille']
    assert len(task_methods) == 1  # pas d'empilement de doublons
    assert p.find_plan(st, ('patrouille', 'usv')) == [('aller_a', 'usv', [1.25, 103.75])]


def test_run_commands_applies_pure_action_fallback():
    p = _planner()
    st = build_state(Scenario.from_dict(DOC))
    p.run_commands(st, [('aller_a', 'usv', (1.30, 103.80))])
    assert st.agents['usv']['pos'] == {'lat': 1.30, 'lon': 103.80}
```

- [ ] **Step 2 : Vérifier l'échec** — `uv run pytest tests/test_planner.py -q` → `ModuleNotFoundError`

- [ ] **Step 3 : Implémenter**

```python
# tsm/planning/planner.py
"""GTPyhop derrière une frontière : domaine privé, verrou, zéro global fuité.

gtpyhop rebinde son current_domain global à chaque construction de Domain
et toutes ses fonctions declare_*/find_plan opèrent dessus. Le Planner
confine ça : chaque opération rebinde current_domain sous verrou, ce qui
sérialise du même coup les replanifications concurrentes des threads
agents (un find_plan dure quelques ms).
"""
from __future__ import annotations

import itertools
import threading
from typing import Any

from tsm.domain.scenario import Scenario
from tsm.planning import methods
from tsm.vendor import gtpyhop

_ids = itertools.count(1)


class Planner:
    def __init__(self, kb: dict[str, Any], actions: tuple[Any, ...] = (),
                 commands: tuple[Any, ...] = ()) -> None:
        self._lock = threading.Lock()
        with self._lock:
            self._domain = gtpyhop.Domain(f'tsm_{next(_ids)}')  # rebinde current_domain
            gtpyhop.verbose = 0
            if actions:
                gtpyhop.declare_actions(*actions)
            if commands:
                gtpyhop.declare_commands(*commands)
            methods.register_builtin()
            methods.register_kb(kb)

    def find_plan(self, state: Any, task: tuple[Any, ...]) -> Any:
        with self._lock:
            gtpyhop.current_domain = self._domain
            return gtpyhop.find_plan(state, [task])

    def reload_kb(self, kb: dict[str, Any]) -> None:
        with self._lock:
            gtpyhop.current_domain = self._domain
            methods.register_kb(kb)

    def run_commands(self, state: Any, plan: list[tuple[Any, ...]]) -> None:
        """Exécute un plan : command 'c_<action>' si présente, sinon l'action pure.

        Hors verrou volontairement : les commands bloquent sur des appels ROS
        et les dicts du domaine ne changent plus après construction (reload_kb
        ne touche que les méthodes de tâches, pas les actions/commands).
        """
        for step in plan:
            fn = self._domain._command_dict.get('c_' + step[0]) \
                or self._domain._action_dict.get(step[0])
            if fn:
                fn(state, *step[1:])


def build_state(scenario: Scenario) -> Any:
    """État GTPyhop initial — même construction pour la préview web et le runtime."""
    state = gtpyhop.State('state')
    state.agents = {}
    for name, spec in scenario.agents.items():
        agent: dict[str, Any] = {
            'pos': {'lat': spec.position.lat, 'lon': spec.position.lon},
            'available': True,
            'intruder_nearby': False,
            'last_waypoint': None,
        }
        for k, v in spec.conditions.items():
            if isinstance(v, str) and v.lower() in ('true', 'false'):
                agent[k] = v.lower() == 'true'
            else:
                agent[k] = v
        state.agents[name] = agent
    state.position_history = {}
    return state
```

- [ ] **Step 4 : Vérifier** — `uv run pytest tests/test_planner.py -q` → 6 passed ; puis `uv run pytest -q` → toute la suite passe.

- [ ] **Step 5 : Commit**

```bash
git add tsm/planning/planner.py tests/test_planner.py
git commit -m "feat: Planner — gtpyhop confiné derrière un domaine privé et un verrou

Plus d'ordre d'import fragile ni de domaine global partagé entre
threads ; le rechargement de KB remplace au lieu d'empiler."
```

---

### Task 8 : Adaptateur LOTUSim (`tsm/lotusim/client.py`)

**Modèle : sonnet**

**Files:**
- Create: `tsm/lotusim/client.py`

**Interfaces:**
- Produces (consommé par la tâche 9) : `class LotusimClient` —
  `__init__(self, node_name='goto_point', namespace='/lotusim', on_pose=None)`,
  `spawn_vessel(self, vessel, init_pos, model, linear_velocities_limits, angular_velocities_limits, heading=0.0)`,
  `set_waypoints(self, agent, lat, lon)`, `get_pose(self, name) -> dict | None`,
  `register_watch(self, name, event)`, `ok() -> bool`, `log_info(msg)`, `log_error(msg)`, `shutdown()`.
- **Pas de test unitaire** (transport ROS pur — se vérifie contre la sim, dit explicitement). Vérification = `py_compile` + revue.

- [ ] **Step 1 : Implémenter**

```python
# tsm/lotusim/client.py
"""Adaptateur ROS vers LOTUSim — SEUL module du paquet à importer rclpy.

Possède le nœud et son executor ; expose le spawn, l'envoi de waypoints et
l'observation des poses avec réveil sur changement réel (wake-on-change).
C'est la couture où se brancheront les autonomies de l'architecture cible
(ARCHITECTURE.md §7.6).
"""
from __future__ import annotations

import math
import threading
from typing import Any, Callable, Optional

import rclpy
from geographic_msgs.msg import GeoPoint
from rclpy.action import ActionClient
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node

from lotusim_msgs.action import MASCmd
from lotusim_msgs.msg import MASCmd as MASCmdMsg
from lotusim_msgs.msg import VesselPositionArray
from lotusim_msgs.srv import SetWaypoints

# En dessous, deux positions sont "identiques" (bruit GPS/float) : une mise à
# jour de pose ne réveille pas inutilement les agents qui la surveillent.
POSITION_EPSILON_DEG = 1e-6


def _wait(fut: Any, timeout: float = 10.0) -> None:
    done = threading.Event()
    fut.add_done_callback(lambda _: done.set())
    done.wait(timeout=timeout)


class LotusimClient:
    def __init__(self, node_name: str = 'goto_point', namespace: str = '/lotusim',
                 on_pose: Optional[Callable[[str, float, float], None]] = None) -> None:
        self._node = Node(node_name, namespace=namespace)
        self._executor = MultiThreadedExecutor()
        self._executor.add_node(self._node)
        threading.Thread(target=self._executor.spin, daemon=True).start()
        self._data: dict[str, dict[str, float]] = {}
        self._lock = threading.Lock()
        self._watchers: dict[str, list[threading.Event]] = {}
        self._on_pose = on_pose
        self._node.create_subscription(VesselPositionArray, '/lotusim/poses', self._cb, 10)

    # ── Observation des poses ────────────────────────────────────────────

    def _cb(self, msg: Any) -> None:
        with self._lock:
            for v in msg.vessels:
                new = {'lat': v.geo_point.latitude, 'lon': v.geo_point.longitude}
                old = self._data.get(v.vessel_name)
                changed = (
                    old is None
                    or abs(old['lat'] - new['lat']) > POSITION_EPSILON_DEG
                    or abs(old['lon'] - new['lon']) > POSITION_EPSILON_DEG
                )
                self._data[v.vessel_name] = new
                if self._on_pose:
                    self._on_pose(v.vessel_name, new['lat'], new['lon'])
                if changed:
                    for ev in self._watchers.get(v.vessel_name, []):
                        ev.set()

    def get_pose(self, name: str) -> Optional[dict[str, float]]:
        with self._lock:
            return self._data.get(name)

    def register_watch(self, name: str, event: threading.Event) -> None:
        """Réveille `event` quand la position de `name` change réellement."""
        with self._lock:
            self._watchers.setdefault(name, []).append(event)

    # ── Commandes LOTUSim ────────────────────────────────────────────────

    def spawn_vessel(self, vessel: str, init_pos: tuple[float, float], model: str,
                     linear_velocities_limits: tuple[float, float],
                     angular_velocities_limits: float, heading: float = 0.0) -> None:
        spawn = ActionClient(self._node, MASCmd, '/lotusim/mas_cmd')
        spawn.wait_for_server()
        cmd = MASCmdMsg()
        cmd.cmd_type = MASCmdMsg.CREATE_CMD
        cmd.model_name = model
        cmd.vessel_name = vessel
        cmd.geo_point = GeoPoint(latitude=init_pos[0], longitude=init_pos[1], altitude=0.0)
        # MASCmd.heading est un champ top-level (radians, utilisé tel quel comme yaw
        # par entity_spawner.cpp) — pas un tag SDF. `heading` ici est en degrés
        # (convention scénario/UI), donc conversion.
        cmd.heading = math.radians(heading)
        cmd.sdf_string = f"""
            <lotus_param>
                <waypoint_follower>
                    <follower>
                        <loop>false</loop>
                        <range_tolerance>2</range_tolerance>
                        <linear_velocities_limits>{linear_velocities_limits[0]} {linear_velocities_limits[1]}</linear_velocities_limits>
                        <angular_velocities_limits>{angular_velocities_limits}</angular_velocities_limits>
                    </follower>
                </waypoint_follower>
            </lotus_param>
        """
        goal = MASCmd.Goal()
        goal.cmd = cmd
        fut = spawn.send_goal_async(goal)
        _wait(fut, timeout=10.0)
        if not fut.done() or fut.result() is None:
            raise RuntimeError(f"spawn_vessel: pas de réponse pour '{vessel}'")
        res_fut = fut.result().get_result_async()
        _wait(res_fut, timeout=10.0)
        if not res_fut.done() or res_fut.result() is None:
            raise RuntimeError(f"spawn_vessel: timeout résultat pour '{vessel}'")
        self._node.get_logger().info(f'Spawned: {res_fut.result().result.name}')

    def set_waypoints(self, agent: str, lat: float, lon: float) -> None:
        cli = self._node.create_client(SetWaypoints, f'/lotusim/{agent}/waypoints')
        cli.wait_for_service()
        req = SetWaypoints.Request()
        req.path = [GeoPoint(latitude=lat, longitude=lon, altitude=0.0)]
        req.loop = False
        fut = cli.call_async(req)
        _wait(fut)
        self._node.get_logger().info(f'[{agent}] → ({lat:.5f}, {lon:.5f})')

    # ── Divers ───────────────────────────────────────────────────────────

    def ok(self) -> bool:
        return bool(rclpy.ok())

    def log_info(self, msg: str) -> None:
        self._node.get_logger().info(msg)

    def log_error(self, msg: str) -> None:
        self._node.get_logger().error(msg)

    def shutdown(self) -> None:
        self._executor.shutdown()
        self._node.destroy_node()
```

- [ ] **Step 2 : Vérifier ce qui est vérifiable sans ROS**

```bash
uv run python -m py_compile tsm/lotusim/client.py && echo COMPILE_OK
uv run pytest -q
```

Expected: `COMPILE_OK` ; la suite complète passe toujours (rien ne doit importer `tsm.lotusim`).

- [ ] **Step 3 : Commit**

```bash
git add tsm/lotusim/client.py
git commit -m "feat: LotusimClient — l'adaptateur ROS devient la seule frontière LOTUSim

Nœud, spawn, waypoints et wake-on-change regroupés ; c'est ici que se
brancheront les autonomies de l'architecture cible."
```

---

### Task 9 : Boucle agent + assemblage runtime (`tsm/execution/runner.py`, `runtime.py`, shim `main.py`)

**Modèle : sonnet**

**Files:**
- Create: `tsm/execution/runner.py`
- Create: `tsm/execution/runtime.py`
- Rewrite: `main.py` (devient un shim)
- Test: `tests/test_runner_logs.py`

**Interfaces:**
- Consumes: `LotusimClient` (tâche 8), `Planner`/`build_state` (7), `make_commands`/actions (6), `methods.collect_watched_tokens`/`resolve_watched_agents` (5), `doctrine.load` (3), `load_scenario` (2).
- Produces : `RunLogs(directory='logs')` avec `log_pose/log_waypoint/close`, `run_agent(name, task, state, planner, client, watched_names)`, `runtime.main(scenario_name: str)`.

- [ ] **Step 1 : Test de RunLogs**

```python
# tests/test_runner_logs.py
import csv

from tsm.execution.runner import RunLogs


def test_runlogs_writes_flushed_rows(tmp_path):
    logs = RunLogs(directory=tmp_path)
    logs.log_pose('usv', 1.26, 103.75)
    logs.log_waypoint('usv', 1.27, 103.76)
    # flush systématique : lisible AVANT close
    with open(tmp_path / 'poses.csv') as f:
        rows = list(csv.reader(f))
    assert rows[0] == ['timestamp', 'agent', 'lat', 'lon']
    assert rows[1][1:] == ['usv', '1.26', '103.75']
    logs.close()
    with open(tmp_path / 'waypoints.csv') as f:
        assert list(csv.reader(f))[1][1:] == ['usv', '1.27', '103.76']
```

- [ ] **Step 2 : Vérifier l'échec** — `uv run pytest tests/test_runner_logs.py -q` → `ModuleNotFoundError`

- [ ] **Step 3 : Implémenter `runner.py`**

```python
# tsm/execution/runner.py
"""Boucle agent événementielle et logs CSV du run. Aucun import ROS :
le client est reçu en paramètre (duck-typé), la boucle interroge client.ok()."""
from __future__ import annotations

import csv
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Si aucune position surveillée n'a changé après ce délai, on re-vérifie quand
# même — filet de sécurité (une watch ratée, une résolution de token qui a
# changé), pas le rythme normal (c'est l'événement wake-on-change).
REPLAN_SAFETY_TIMEOUT = 5.0
POSITION_HISTORY_LEN = 5


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')


class RunLogs:
    """poses.csv + waypoints.csv, flushés à chaque ligne — sans flush, un kill
    brutal laissait un gros bloc dans le buffer OS (observé : une plage de NUL
    à la relecture)."""

    def __init__(self, directory: Any = 'logs') -> None:
        d = Path(directory)
        d.mkdir(exist_ok=True)
        self._pose_f = open(d / 'poses.csv', 'w', newline='')
        self._wp_f = open(d / 'waypoints.csv', 'w', newline='')
        self._pose = csv.writer(self._pose_f)
        self._wp = csv.writer(self._wp_f)
        self._wp_lock = threading.Lock()
        self._pose.writerow(['timestamp', 'agent', 'lat', 'lon'])
        self._wp.writerow(['timestamp', 'agent', 'lat', 'lon'])

    def log_pose(self, agent: str, lat: float, lon: float) -> None:
        # appelé depuis le callback du client, déjà sérialisé par son verrou
        self._pose.writerow([_ts(), agent, lat, lon])
        self._pose_f.flush()

    def log_waypoint(self, agent: str, lat: float, lon: float) -> None:
        with self._wp_lock:  # appelé par les commands depuis les threads agents
            self._wp.writerow([_ts(), agent, lat, lon])
            self._wp_f.flush()

    def close(self) -> None:
        self._pose_f.close()
        self._wp_f.close()


def sync_positions(state: Any, client: Any) -> None:
    """Recopie les poses observées dans l'état de planification + historique
    court (les préconditions distance_* calculent tout depuis ces positions)."""
    for name in state.agents:
        pos = client.get_pose(name)
        if pos:
            old = state.agents[name].get('pos')
            if old and (old['lat'] != pos['lat'] or old['lon'] != pos['lon']):
                hist = state.position_history.setdefault(name, [])
                hist.append(old)
                state.position_history[name] = hist[-POSITION_HISTORY_LEN:]
            state.agents[name]['pos'] = pos


def run_agent(name: str, task: tuple[Any, ...], state: Any, planner: Any,
              client: Any, watched_names: set[str]) -> None:
    """Replanification événementielle : bloque jusqu'à ce qu'une position
    surveillée change réellement, REPLAN_SAFETY_TIMEOUT en filet."""
    wake = threading.Event()
    for watched in watched_names | {name}:
        client.register_watch(watched, wake)
    client.log_info(f'[{name}] surveille : {sorted(watched_names | {name})}')

    while client.ok():
        sync_positions(state, client)
        plan = planner.find_plan(state, task)
        if plan is not False and plan:
            client.log_info(f'[{name}] exécute plan: {[a[0] for a in plan]}')
            planner.run_commands(state, plan)
        wake.wait(timeout=REPLAN_SAFETY_TIMEOUT)
        wake.clear()
```

- [ ] **Step 4 : Implémenter `runtime.py` et le shim `main.py`**

```python
# tsm/execution/runtime.py
"""Assemblage du runtime : client ROS + planner + un thread runner par agent.

Ce module (et lui seul, avec tsm.lotusim.client) touche rclpy — jamais
importé par les tests ni par tsm.web.
"""
from __future__ import annotations

import threading
import time

import rclpy

from tsm.domain import doctrine
from tsm.domain.scenario import load_scenario
from tsm.execution.actions import aller_a, creation_agent, make_commands
from tsm.execution.runner import RunLogs, run_agent
from tsm.lotusim.client import LotusimClient
from tsm.planning import methods
from tsm.planning.planner import Planner, build_state


def main(scenario_name: str) -> None:
    scenario = load_scenario(scenario_name)   # échoue AVANT d'initialiser ROS
    kb = doctrine.load()

    rclpy.init()
    logs = RunLogs()
    client = LotusimClient(on_pose=logs.log_pose)
    try:
        planner = Planner(kb, actions=(aller_a, creation_agent),
                          commands=make_commands(client, logs))
        state = build_state(scenario)

        client.log_info(f'[HTN] Scénario : {scenario_name}')
        for name, spec in scenario.agents.items():
            plan = planner.find_plan(state, spec.mission.to_htn_task())
            client.log_info(f'[HTN] {name}: {plan}')

        for name, spec in scenario.agents.items():
            try:
                client.spawn_vessel(name, (spec.position.lat, spec.position.lon),
                                    spec.model, spec.linear_velocity,
                                    spec.angular_velocity_max, heading=spec.heading_deg)
            except Exception as e:
                client.log_error(f"[spawn] échec pour '{name}' (model={spec.model!r}): {e}")
            time.sleep(3.0)

        threads = []
        for name, spec in scenario.agents.items():
            # Quelles positions ce mission-thread doit-il surveiller : tous les
            # tokens atteignables depuis sa tâche de mission, résolus sur l'état
            # initial (best-effort — le filet REPLAN_SAFETY_TIMEOUT couvre les
            # changements d'identité de cible en cours de run).
            tokens = methods.collect_watched_tokens(kb, spec.mission.task)
            watched = methods.resolve_watched_agents(state, name, tokens)
            threads.append(threading.Thread(
                target=run_agent,
                args=(name, spec.mission.to_htn_task(), state, planner, client, watched),
                daemon=True,
            ))
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    except KeyboardInterrupt:
        pass
    finally:
        logs.close()
        client.shutdown()
        rclpy.shutdown()
```

```python
#!/usr/bin/env python3
# main.py — shim : l'implémentation vit dans tsm/execution/runtime.py.
import sys

if __name__ == '__main__':
    if len(sys.argv) < 2:
        from tsm.domain.scenario import list_scenarios
        sys.exit(f"usage: python3 main.py <scenario>  (disponibles : {', '.join(list_scenarios())})")
    from tsm.execution.runtime import main
    main(sys.argv[1])
```

- [ ] **Step 5 : Vérifier**

```bash
uv run pytest -q
uv run python -m py_compile tsm/execution/runner.py tsm/execution/runtime.py main.py && echo COMPILE_OK
uv run python main.py 2>&1 | tail -1
```

Expected: suite verte ; `COMPILE_OK` ; le dernier appel affiche la ligne `usage: ... (disponibles : 2_agents_patrolling, demo_veille_drone_intru, ...)` — preuve que le shim liste les scénarios JSON sans toucher à ROS.

- [ ] **Step 6 : Commit**

```bash
git add tsm/execution/runner.py tsm/execution/runtime.py main.py tests/test_runner_logs.py
git commit -m "feat: runtime assemblé par composition — main.py devient un shim

La boucle agent ne connaît plus ni globals ni ROS : planner, client et
logs arrivent en paramètres."
```

---

### Task 10 : API web (`tsm/web/api.py`, `tsm/web/server.py`, shim `app.py`)

**Modèle : sonnet**

**Files:**
- Create: `tsm/web/api.py`, `tsm/web/server.py`
- Rewrite: `app.py` (devient un shim)
- Test: `tests/test_web_api.py`

**Interfaces:**
- Consumes: `doctrine` (3), store scénarios (2), `Planner`/`build_state` (7), actions pures (6).
- Produces : `Api` (handlers purs), `make_server(port: int = 8080) -> HTTPServer`, mêmes routes qu'avant :
  `GET /` (HTML), `GET /api/scenarios`, `GET /api/kb`, `POST /api/kb`, `GET|POST|DELETE /api/scenario/<name>`, `GET /api/scenario/<name>/plan`, `POST /api/scenario/<name>/launch`, `POST /api/generate-scenario` → **501**.
- Mapping d'erreurs : `ScenarioError` sur un GET/DELETE → 404 `{"error": "not found"}` ; sur un POST (validation) → 400 `{"error": "<message>"}` ; route inconnue → 404.

- [ ] **Step 1 : Test (smoke HTTP, sans ROS)**

```python
# tests/test_web_api.py
import json
import threading
from http.client import HTTPConnection

from tsm.web.server import make_server


def _get(conn, path):
    conn.request('GET', path)
    r = conn.getresponse()
    return r.status, json.loads(r.read())


def test_api_end_to_end_sans_ros():
    srv = make_server(port=0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    conn = HTTPConnection('127.0.0.1', port)
    try:
        status, names = _get(conn, '/api/scenarios')
        assert status == 200 and 'demo_veille_drone_intru' in names

        status, doc = _get(conn, '/api/scenario/demo_veille_drone_intru')
        assert status == 200 and doc['version'] == 1 and 'veilleur' in doc['agents']

        status, plans = _get(conn, '/api/scenario/demo_veille_drone_intru/plan')
        assert status == 200 and set(plans) == set(doc['agents'])

        status, _ = _get(conn, '/api/scenario/inconnu')
        assert status == 404

        conn.request('POST', '/api/scenario/demo_veille_drone_intru',
                     body=json.dumps({'version': 99}),
                     headers={'Content-Type': 'application/json'})
        assert conn.getresponse().status == 400  # ScenarioError → message explicite

        conn.request('POST', '/api/generate-scenario', body=json.dumps({'description': 'x'}),
                     headers={'Content-Type': 'application/json'})
        r = conn.getresponse()
        assert r.status == 501 and 'parqué' in json.loads(r.read())['error']
    finally:
        srv.shutdown()
```

- [ ] **Step 2 : Vérifier l'échec** — `uv run pytest tests/test_web_api.py -q` → `ModuleNotFoundError`

- [ ] **Step 3 : Implémenter**

```python
# tsm/web/api.py
"""Handlers de l'API locale — parlent le schéma canonique, aucun import ROS."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

from tsm.domain import doctrine
from tsm.domain.scenario import (Scenario, delete_scenario, list_scenarios,
                                 load_scenario, save_scenario)
from tsm.execution.actions import aller_a, creation_agent
from tsm.planning.planner import Planner, build_state

REPO_ROOT = Path(__file__).resolve().parents[2]


class Api:
    def __init__(self) -> None:
        self._planner = Planner(doctrine.load(), actions=(aller_a, creation_agent))

    def scenarios(self) -> list[str]:
        return list_scenarios()

    def get_kb(self) -> dict[str, Any]:
        return doctrine.load()

    def save_kb(self, kb: dict[str, Any]) -> dict[str, Any]:
        doctrine.save(kb)
        self._planner.reload_kb(kb)
        return {'ok': True}

    def get_scenario(self, name: str) -> dict[str, Any]:
        return load_scenario(name).to_dict()

    def save_scenario(self, name: str, doc: dict[str, Any]) -> dict[str, Any]:
        save_scenario(name, Scenario.from_dict(doc))
        return {'ok': True}

    def delete_scenario(self, name: str) -> dict[str, Any]:
        delete_scenario(name)
        return {'ok': True}

    def plan(self, name: str) -> dict[str, str]:
        scenario = load_scenario(name)
        state = build_state(scenario)
        results = {}
        for aname, spec in scenario.agents.items():
            try:
                plan = self._planner.find_plan(state, spec.mission.to_htn_task())
                if plan is False:
                    results[aname] = 'Aucun plan applicable (préconditions non satisfaites)'
                elif not plan:
                    results[aname] = '[] — inactif (drone géré par agent dédié)'
                else:
                    results[aname] = str(plan)
            except Exception as e:  # préview best-effort : l'erreur est LE résultat affiché
                results[aname] = f'Erreur: {e}'
        return results

    def launch(self, name: str) -> dict[str, Any]:
        load_scenario(name)  # refus propre (400) avant de lancer quoi que ce soit
        proc = subprocess.Popen([sys.executable, 'main.py', name], cwd=REPO_ROOT)
        return {'ok': True, 'pid': proc.pid}
```

```python
# tsm/web/server.py
"""Serveur HTTP local (stdlib) : routing + sérialisation, la logique vit dans Api."""
from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse

from tsm.domain.scenario import ScenarioError
from tsm.web.api import Api

TEMPLATE_PATH = Path(__file__).resolve().parents[2] / 'templates' / 'index.html'


def _route(method: str, path: str):
    """Retourne (action, params) ou (None, {})."""
    parts = path.strip('/').split('/')
    if method == 'GET':
        if parts == ['']:
            return 'html', {}
        if parts == ['api', 'scenarios']:
            return 'list_scenarios', {}
        if parts == ['api', 'kb']:
            return 'get_kb', {}
        if len(parts) == 3 and parts[:2] == ['api', 'scenario']:
            return 'get_scenario', {'name': parts[2]}
        if len(parts) == 4 and parts[:2] == ['api', 'scenario'] and parts[3] == 'plan':
            return 'get_plan', {'name': parts[2]}
    if method == 'POST':
        if parts == ['api', 'kb']:
            return 'save_kb', {}
        if len(parts) == 3 and parts[:2] == ['api', 'scenario']:
            return 'save_scenario', {'name': parts[2]}
        if len(parts) == 4 and parts[:2] == ['api', 'scenario'] and parts[3] == 'launch':
            return 'launch_scenario', {'name': parts[2]}
        if parts == ['api', 'generate-scenario']:
            return 'generate_scenario', {}
    if method == 'DELETE':
        if len(parts) == 3 and parts[:2] == ['api', 'scenario']:
            return 'delete_scenario', {'name': parts[2]}
    return None, {}


class _Handler(BaseHTTPRequestHandler):
    api: Api  # posé par make_server

    def log_message(self, fmt, *args):
        pass

    def _send_json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _send_html(self):
        content = TEMPLATE_PATH.read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(content)))
        self.end_headers()
        try:
            self.wfile.write(content)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _read_json(self):
        length = int(self.headers.get('Content-Length', 0))
        return json.loads(self.rfile.read(length))

    def _dispatch(self, method):
        action, params = _route(method, urlparse(self.path).path)
        try:
            if action == 'html':
                self._send_html()
            elif action == 'list_scenarios':
                self._send_json(self.api.scenarios())
            elif action == 'get_kb':
                self._send_json(self.api.get_kb())
            elif action == 'save_kb':
                self._send_json(self.api.save_kb(self._read_json()))
            elif action == 'get_scenario':
                self._send_json(self.api.get_scenario(params['name']))
            elif action == 'get_plan':
                self._send_json(self.api.plan(params['name']))
            elif action == 'save_scenario':
                self._send_json(self.api.save_scenario(params['name'], self._read_json()))
            elif action == 'delete_scenario':
                self._send_json(self.api.delete_scenario(params['name']))
            elif action == 'launch_scenario':
                self._send_json(self.api.launch(params['name']))
            elif action == 'generate_scenario':
                self._send_json({'error': 'générateur IA parqué — voir attic/'}, 501)
            else:
                self._send_json({'error': 'not found'}, 404)
        except ScenarioError as e:
            if method == 'POST':
                self._send_json({'error': str(e)}, 400)
            else:
                self._send_json({'error': 'not found'}, 404)

    def do_GET(self):
        self._dispatch('GET')

    def do_POST(self):
        self._dispatch('POST')

    def do_DELETE(self):
        self._dispatch('DELETE')


class _Server(HTTPServer):
    allow_reuse_address = True


def make_server(port: int = 8080) -> HTTPServer:
    handler = type('Handler', (_Handler,), {'api': Api()})
    return _Server(('', port), handler)


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    try:
        server = make_server(port)
    except OSError:
        print(f'Port {port} déjà utilisé. Essayez : python3 app.py 8081')
        sys.exit(1)
    print(f'Tactical Scenario Maker → http://localhost:{port}')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nArrêt.')
```

```python
#!/usr/bin/env python3
# app.py — shim : l'implémentation vit dans tsm/web/server.py.
from tsm.web.server import main

if __name__ == '__main__':
    main()
```

- [ ] **Step 4 : Vérifier**

Run: `uv run pytest -q`
Expected: suite complète verte, y compris le smoke HTTP.

- [ ] **Step 5 : Commit**

```bash
git add tsm/web/ app.py tests/test_web_api.py
git commit -m "feat: API web sur le schéma canonique — app.py devient un shim

Les routes ne changent pas de chemin ; les conversions formulaire
disparaissent, le générateur IA répond 501 (parqué)."
```

---

### Task 11 : Adaptation a minima de l'UI (`templates/index.html`)

**Modèle : sonnet**

**Files:**
- Modify: `templates/index.html` (7 points de contact, ~40 lignes touchées sur 2673)

Les numéros de ligne ci-dessous sont ceux du fichier AVANT modification (vérifiés par reconnaissance). Appliquer dans l'ordre bas→haut pour les préserver, ou se repérer aux noms de fonctions.

**Interfaces:**
- Consumes: l'API de la tâche 10 (document `{version: 1, agents: {...}}`, mission `{task, args}` avec `args[0]` = nom de l'agent lui-même — convention des signatures de tâches Python).

- [ ] **Step 1 : Masquer l'onglet IA** — ligne 1005, supprimer le bouton :

```html
<button class="tab-btn"        data-tab="ia"        onclick="switchTab('ia')">🤖 IA</button>
```

Le panneau `#tab-ia` (display:none par défaut) et tout son JS (l.2440-2643) deviennent inatteignables — les laisser en place, ils partent avec le générateur à sa réadaptation.

- [ ] **Step 2 : `parseMission` (l.1430-1433)** — consomme l'objet mission au lieu de la string, en préservant le contrat aval (`extra` = liste plate de strings, sans le nom de l'agent) :

```js
function parseMission(m) {
  const args = (m && m.args) ? m.args.slice(1) : [];   // args[0] = l'agent lui-même
  const flat = [];
  for (const a of args) { if (Array.isArray(a)) flat.push(...a); else flat.push(a); }
  return { task: (m && m.task) || 'veiller', extra: flat.map(String) };
}
```

L'appel `parseMission(a.mission || '')` dans `buildCard` (l.1352) devient `parseMission(a.mission)`.

- [ ] **Step 3 : `buildCard` (l.1347-1428)** — sourcer les champs depuis la nouvelle forme :

- l.1364-1370 : `value="${a.x ?? ''}"` → `value="${a.position?.lat ?? ''}"` ; `value="${a.y ?? ''}"` → `value="${a.position?.lon ?? ''}"` (les `name="x"`/`name="y"` des inputs ne changent pas — ils portaient déjà lat/lon).
- l.1382 : `value="${a.heading ?? 0}"` → `value="${a.heading_deg ?? 0}"`.
- l.1386 : `value="${a.vel_min ?? 0} ${a.vel_max ?? 5}"` → `value="${a.velocity?.linear?.[0] ?? 0} ${a.velocity?.linear?.[1] ?? 5}"`.

- [ ] **Step 4 : `collectAgents` (l.1594-1634)** — construire la nouvelle forme. Les lignes 1601-1610 (assemblage string) deviennent :

```js
const task = g('task');
const type = getTaskMeta(task).extra ?? 'none';
const args = [aname];
if (type === 'pos') {
  const lat = g('mission_lat'), lon = g('mission_lon');
  if (lat && lon) args.push([Number(lat), Number(lon)]);
} else if (type === 'target') {
  const t = g('mission_target');
  if (t) args.push(t);
}
```

et le littéral des lignes 1621-1631 devient :

```js
data[aname] = {
  position: { lat: parseFloat(g('x')) || 0, lon: parseFloat(g('y')) || 0 },
  heading_deg: parseFloat(g('heading')) || 0,
  model: g('model') || 'wamv',
  velocity: { linear: [isNaN(vm) ? 0 : vm, isNaN(vM) ? 5 : vM], angular_max: 0.05 },
  conditions,
  mission: { task, args },
};
```

(`angular_max: 0.05` reste le littéral qu'était `ang_vel: 0.05` — pas de champ UI pour lui aujourd'hui, hors périmètre d'en ajouter un.)

- [ ] **Step 5 : Enveloppe du document** —

- `selectScenario` (l.1297-1303) : `.then(agents => { renderEditor(name, agents, false); ... })` → `.then(doc => { renderEditor(name, doc.agents, false); ... })`.
- Refetch post-save (l.1670-1674) : idem, `doc.agents`.
- `saveScenario` (l.1663-1666) : `body: JSON.stringify(collectAgents())` → `body: JSON.stringify({ version: 1, agents: collectAgents() })`.

- [ ] **Step 6 : Vérification manuelle (seule vérification possible pour l'UI — l'assumer)**

```bash
uv run python app.py 8080
```

Dans le navigateur : (1) la liste montre les 5 scénarios ; (2) ouvrir `demo_veille_drone_intru` → les 3 agents s'affichent avec lat/lon/vitesses/mission corrects ; (3) « Plan » affiche un plan par agent ; (4) modifier une latitude, sauver, recharger la page → la valeur persiste ; (5) créer un scénario neuf avec 1 agent, le sauver, le supprimer ; (6) l'onglet IA n'apparaît plus. Vérifier `scenarios/*.json` à la main après le (4) : le fichier doit rester au schéma v1 propre.

- [ ] **Step 7 : Commit**

```bash
git add templates/index.html
git commit -m "feat: l'UI parle le schéma canonique — mission structurée, onglet IA masqué"
```

---

### Task 12 : Parcage du générateur, suppression de l'ancien monde

**Modèle : haiku**

**Files:**
- Create: `attic/README.md`
- Move: `bdd/ai_scenario_generator.py`, `AI_GENERATOR_README.md`, `INSTALL_OLLAMA.sh` → `attic/`
- Delete: `bdd/tasks_methods.py`, `bdd/primitives_actions.py`, `bdd/utils.py` (le répertoire `bdd/` disparaît), `gtpyhop.py` (racine), `tests/test_intruder_resolution.py`

- [ ] **Step 1 : Déplacer et supprimer**

```bash
mkdir -p attic
git mv bdd/ai_scenario_generator.py AI_GENERATOR_README.md INSTALL_OLLAMA.sh attic/
git rm bdd/tasks_methods.py bdd/primitives_actions.py bdd/utils.py
git rm gtpyhop.py tests/test_intruder_resolution.py
```

- [ ] **Step 2 : Écrire `attic/README.md`**

```markdown
# attic — code parqué, hors du paquet

`ai_scenario_generator.py` : générateur IA (Ollama + règles) du pré-PoC,
gelé lors du refactor de 2026-07 (décision de session : parqué, pas adapté).
Il parle l'ANCIEN format de scénario et mutait la KB en pleine requête —
sa réadaptation au schéma canonique (et la séparation doctrine/brouillon,
ARCHITECTURE.md §12.2) est un incrément dédié. Ne pas importer depuis tsm/.
```

- [ ] **Step 3 : Vérifier qu'aucune référence ne survit**

```bash
rg -l "from bdd|import bdd" --glob '!attic/**' ; echo "bdd: $?"
rg -l "^import gtpyhop|^from gtpyhop" --glob '!attic/**' --glob '!tsm/vendor/**' ; echo "gtpyhop racine: $?"
rg -l "import main" --glob '!attic/**' ; echo "import main: $?"
uv run pytest -q
```

Expected: les trois `rg` ne trouvent rien (code retour 1) ; suite verte. Si `visualize.py` apparaît dans un des résultats : le SIGNALER et s'arrêter — il est hors périmètre, ne pas le modifier sans décision.

- [ ] **Step 4 : Commit**

```bash
git add -A
git commit -m "chore: générateur IA parqué dans attic/, suppression de l'ancien monde

bdd/, le gtpyhop racine et le hack import-main n'ont plus d'appelant ;
attic/ documente pourquoi le générateur attend son incrément."
```

---

### Task 13 : Qualité (ruff, mypy), README, ARCHITECTURE.md v2

**Modèle : sonnet**

**Files:**
- Modify: tout fichier `tsm/`/`tests/` signalé par ruff/mypy
- Rewrite: `README.md`
- Modify: `docs/ARCHITECTURE.md` (§4.1, §5.5, §12, §14)

- [ ] **Step 1 : Passes qualité**

```bash
uv run ruff check .
uv run mypy
uv run pytest -q
```

Corriger jusqu'au vert. Contrainte : ne PAS affaiblir la config pour passer — à une exception ATTENDUE près : `tsm/planning/methods.py` contient des ports verbatim non annotés (`_check`, `_resolve`…) qui ne passeront pas `disallow_untyped_defs`. Le sortir de l'override strict avec un commentaire dans `pyproject.toml` (`# ponytail: ports verbatim non annotés, strict à réévaluer si methods.py se stabilise`) plutôt que d'annoter du code verbatim.

- [ ] **Step 2 : Réécrire `README.md`**

Contenu requis (rédiger en français, style sobre) :

```markdown
# Tactical Scenario Maker

Créateur et exécuteur de scénarios tactiques pour LOTUSim (POC).
Décrit des agents et leurs missions, les décompose en HTN (GTPyhop),
envoie des waypoints au WaypointFollower de LOTUSim et replanifie sur
les positions observées. Architecture cible : docs/ARCHITECTURE.md.

## Lancer

    python3 app.py [port]          # UI locale (défaut : 8080) — sans ROS
    python3 main.py <scenario>     # runtime — dans l'environnement ROS,
                                   # instance LOTUSim déjà démarrée

## Développement

    uv run pytest                  # tests (sans ROS)
    uv run ruff check . && uv run mypy

## Structure

| Répertoire | Rôle | Composant logique (ARCHITECTURE.md §7) |
|---|---|---|
| tsm/domain/ | schéma de scénario v1, doctrine HTN, géométrie | Domaine tactique |
| tsm/planning/ | Planner (GTPyhop confiné), méthodes HTN | Domaine tactique |
| tsm/execution/ | actions/commands, boucle agent, assemblage | Exécutif de mission (embryon) |
| tsm/lotusim/ | adaptateur ROS (seul import rclpy) | Frontière LOTUSim / future autonomie |
| tsm/web/ | API HTTP locale | Éditeur tactique (provisoire) |
| scenarios/ | scénarios JSON v1 (l'identité = le nom de fichier) |  |
| doctrine/ | knowledge_base.json — la doctrine HTN |  |
| attic/ | générateur IA parqué (voir attic/README.md) |  |

## Format de scénario (v1)

[reprendre l'exemple JSON de docs/superpowers/specs/2026-07-10-tsm-refactor-design.md §3, verbatim]
```

- [ ] **Step 3 : Mettre à jour `docs/ARCHITECTURE.md`**

Quatre retouches précises :

1. **§4.1** — remplacer la liste de composants (les 7 puces `app.py`/`templates/...`/`bdd/...`) par :

```markdown
- [`tsm/web`](../tsm/web/) sert la SPA locale et l'API (scénarios, doctrine, préview de plan, lancement d'un run en sous-processus).
- [`templates/index.html`](../templates/index.html) reste l'UI locale monolithique, adaptée au schéma canonique (onglet IA masqué).
- [`doctrine/knowledge_base.json`](../doctrine/knowledge_base.json) contient la doctrine HTN, possédée par `tsm/domain/doctrine.py`.
- [`tsm/domain`](../tsm/domain/) porte le schéma canonique v1 des scénarios (`scenarios/*.json`) et la géométrie.
- [`tsm/planning`](../tsm/planning/) confine GTPyhop derrière un `Planner` (domaine privé, verrou) et porte les méthodes HTN.
- [`tsm/execution`](../tsm/execution/) exécute : actions/commands, boucle de replanification événementielle par agent, assemblage du runtime (`main.py` n'est plus qu'un shim).
- [`tsm/lotusim`](../tsm/lotusim/) est l'unique frontière ROS (spawn, waypoints, poses) — la couture des futures autonomies (§7.6).
- [`attic/`](../attic/) : générateur IA parqué en attente de réadaptation (voir §12, impact 2).
```

2. **§5.5** — ajouter à la fin de la section : `**Mise à jour 2026-07 :** le schéma canonique v1 (JSON versionné, `scenarios/*.json`) a remplacé les modules Python générés ; il reste deux représentations (schéma canonique, sortie du générateur IA parqué) au lieu de trois.`
3. **§12** — item 1 : suffixer `— **fait** (schéma v1, 2026-07)` ; item 2 : suffixer `— la mutation implicite de la KB est neutralisée (générateur parqué), la séparation doctrine/brouillon reste à faire` ; item 8 : suffixer `— **fait** (tsm/planning/planner.py, 2026-07)`.
4. **§14** — question 1 : suffixer `*(tranché pour les scénarios : JSON v1 — manifestes et profils d'exécution restent ouverts)*` ; question 10 : suffixer `*(tranché et livré : réorganisation en couches + schéma canonique, voir docs/superpowers/specs/2026-07-10-tsm-refactor-design.md)*`.
5. **§8.3** — après le paragraphe sur le modèle d'événements OpenSCENARIO, ajouter : `Dans le pré-PoC refactoré, la mission du schéma v1 (« mission.task ») référence une tâche de la doctrine HTN — c'est assumé tant que la couche capacités (D3, §7.6) n'existe pas ; le vocabulaire scénario/doctrine/capacités sera séparé avec les manifestes.`

**Attention :** ARCHITECTURE.md évolue en parallèle (le §3 a déjà bougé) — se repérer aux titres de sections et aux textes cités, jamais aux numéros de ligne. Si un texte d'ancrage cité ci-dessus a changé, s'arrêter et signaler plutôt que d'improviser.

- [ ] **Step 4 : Vérification finale complète**

```bash
uv run pytest -q && uv run ruff check . && uv run mypy && echo TOUT_VERT
```

Expected: `TOUT_VERT`.

- [ ] **Step 5 : Commit**

```bash
git add -A
git commit -m "docs: README refondu et ARCHITECTURE.md aligné sur le refactor livré

ruff et mypy verts ; les impacts 1 et 8 du §12 sont actés comme faits."
```

---

## Après la dernière tâche

1. **Vérification end-to-end manuelle (non automatisable depuis le Mac)** : dans le conteneur ROS avec une instance LOTUSim démarrée, `python3 main.py demo_veille_drone_intru` — le drone doit poursuivre l'intrus comme avant le refactor (comparer `logs/waypoints.csv` à un run de référence pré-refactor si disponible). Tant que ce run n'a pas été fait, le refactor est « tests verts, e2e non vérifié » — le dire ainsi.
2. Intégration : `superpowers:finishing-a-development-branch` (rebase sur `main`, historique linéaire, pas de merge commit).

