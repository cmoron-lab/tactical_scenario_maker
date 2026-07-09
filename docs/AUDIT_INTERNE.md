# AUDIT INTERNE — Tactical Scenario Maker / LOTUSim

Généré par exploration automatisée du dépôt le 2026-07-09, branche `htn_implementation`
(HEAD `469c9fe`, à jour avec `origin/htn_implementation`). Document brut, non rédigé pour
être lu comme une doc finale — sert de matière première aux 4 prompts de passation à venir.

Convention : `NON TROUVÉ DANS LE CODE` = information absente, pas déduite, pas supposée.

---

## 0. Vue d'ensemble rapide

- Dépôt Python (~7600 lignes hors HTML), un seul gros fichier front (`templates/index.html`,
  2673 lignes, HTML+CSS+JS inline, zéro dépendance externe/CDN).
- Deux mondes distincts cohabitent dans le même repo :
  1. **Simulation réelle** (`main.py`, `bdd/primitives_actions.py`) — dépend de ROS2 Humble
     + d'un package custom `lotusim_msgs` (workspace externe `~/lotusim_ws`), tourne contre un
     simulateur naval "LOTUSim" (non présent dans ce dépôt).
  2. **UI web autonome** (`app.py` + `templates/index.html`) — stdlib Python pur (`http.server`),
     zéro dépendance ROS, sert d'éditeur de scénarios + planificateur "à blanc" (dry-run HTN
     sans exécution réelle) + générateur IA.
- Un planificateur HTN tiers vendorisé tel quel : `gtpyhop.py` (GTPyhop v1.1, Univ. of Maryland,
  BSD-3-Clause-Clear, Dana Nau 2021) — pas un fork modifié à première vue, code intact.
- Un générateur de scénarios par LLM local (`bdd/ai_scenario_generator.py`, 1704 lignes) via
  Ollama/Mistral 7B en HTTP local (`localhost:11434`), avec une quantité inhabituelle de
  parsing déterministe / heuristiques anti-hallucination autour de l'appel LLM lui-même.
- **Aucun fichier de dépendances** (pas de `requirements.txt`, `pyproject.toml`, `setup.py`,
  `Pipfile`). Les deps Python tierces (`requests`) et ROS (`rclpy`, `geographic_msgs`,
  `lotusim_msgs`) sont supposées déjà présentes dans l'environnement — confirmé installées
  dans l'environnement où cet audit a été exécuté (Python 3.10.12, ROS_DISTRO=humble,
  `lotusim_msgs` trouvé sous `/home/carla/lotusim_ws`).
- Branding dans le `<title>` du front : **"Scenario Maker — Naval Group"** — présent tel quel
  dans `templates/index.html:5`. Aucune autre mention de "Naval Group" ailleurs dans le code.
  Contexte/statut de ce nom : NON TROUVÉ DANS LE CODE (pas de licence, pas de mention
  contractuelle, pas de README qui l'explique).

---

## 1. Arborescence fichier par fichier

### Racine

| Fichier | Rôle réel | Remarques |
|---|---|---|
| `app.py` (361 lignes) | Serveur HTTP stdlib (pas Flask) servant l'UI web + API REST JSON pour éditer/lancer des scénarios, éditer la KB HTN, et appeler le générateur IA. Point d'entrée : `python3 app.py [port]`. | Docstring dit `http://localhost:5000` (ligne 5), mais le port par défaut réel codé en dur ligne 351 est **8080**. Contradiction directe entre commentaire et code — voir §5.1. |
| `main.py` (251 lignes) | Point d'entrée **réel** de simulation ROS2 : spawn les agents dans LOTUSim, boucle de planification HTN événementielle par agent (thread par agent), logging CSV des poses/waypoints. | `import rclpy`, `from lotusim_msgs.msg import VesselPositionArray` — nécessite un environnement ROS2 sourcé + le package `lotusim_msgs` buildé. Argument CLI = nom de scénario (`sys.argv[1]`), défaut `'scenario_1'` — **ce fichier scénario n'existe plus** dans `scenarios/` (supprimé au commit `3376389`). Lancer `python3 main.py` sans argument échoue donc à l'import (`ModuleNotFoundError: scenarios.scenario_1`). Voir §5.2. |
| `gtpyhop.py` (963 lignes) | Moteur de planification HTN générique, tiers, vendorisé intégralement (pas un package pip). API : `Domain`, `State`, `declare_task_methods`, `find_plan`, etc. | En-tête dit "version 1.1" (ligne 4), mais le `print()` d'import en bas de fichier (ligne 962) affiche "Imported GTPyhop version 1.0." — incohérence dans le fichier tiers lui-même, pas introduite par ce projet. Le fichier est importé dans `app.py`, `main.py`, `bdd/tasks_methods.py`, `tests/test_intruder_resolution.py` — **imprime ce message à chaque import**, y compris pendant les tests (bruit visible dans `pytest -q`). |
| `visualize.py` (160 lignes) | Génère `logs/map.html` (carte Leaflet interactive) à partir de `logs/poses.csv` / `logs/waypoints.csv`. CLI : `python3 visualize.py [poses.csv] [waypoints.csv]`. Ouvre le navigateur automatiquement (`webbrowser.open`). | Dépend de Leaflet via CDN (`unpkg.com`) dans le HTML généré — **seul point du projet qui charge une ressource externe**, contraste avec `app.py`/`index.html` qui sont 100% autonomes. Tolère les logs corrompus (octets NUL) suite à un arrêt brutal du process. |
| `INSTALL_OLLAMA.sh` (36 lignes) | Script setup : installe Ollama si absent, `ollama pull mistral`. | Correct et cohérent avec `AI_GENERATOR_README.md`. `curl \| sh` (installe depuis ollama.ai) — pas de vérification d'intégrité, standard pour ce genre de script mais à noter. |
| `AI_GENERATOR_README.md` (263 lignes) | Doc utilisateur du générateur IA. | Dit "Open `http://localhost:8080`" (cohérent avec le vrai défaut de `app.py`, PAS avec le commentaire dans `app.py`). Section "Available Models" mentionne `neural-chat`, `llama2`, `dolphin-mixtral` comme alternatives — **aucune n'est référencée dans le code** (le modèle est en dur `"mistral"` dans `_query_ollama()`, changeable seulement en éditant le code source, pas via l'UI ni une variable d'env). |
| `.gitignore` | Ignore `__pycache__/`, `*.pyc`, `.pytest_cache/`, `logs/*.csv`. | **`logs/map.html` n'est PAS ignoré** alors qu'il est un artefact généré (par `visualize.py`) au même titre que les CSV — il est pourtant tracké en Git et régulièrement modifié dans les commits de features (ex. `469c9fe`, `4879212`, `329dcb3`) sans rapport avec le contenu de ces commits. Incohérence de convention : soit c'est voulu comme "carte de démo figée", soit c'est un oubli. NON TROUVÉ DANS LE CODE d'explication. |
| `.vscode/settings.json` | Vide (`{}`). | Untracked (dans `?? .vscode/` du `git status`). |
| `.claude/settings.local.json` | Permissions Claude Code locales. | Révèle un historique de debug utile : recherche de `librcl_action.so`, `lotusim_msgs` build, ET une tentative antérieure d'utiliser **Flask** (`pip install flask`, `sudo apt-get install -y python3-flask`, `import flask`) — abandonnée au profit du stdlib `http.server` (cohérent avec le commentaire "no external dependencies" dans `app.py`). Ce fichier n'est probablement pas destiné à la passation mais donne un signal fiable sur une décision d'archi (Flask envisagé puis rejeté). |

### `bdd/` (base de connaissances + logique métier)

| Fichier | Rôle réel | Remarques |
|---|---|---|
| `knowledge_base.json` (406 lignes) | Base de connaissances HTN déclarative : `resolve_tokens` (alias de résolution d'agents), `tasks` (tâches composites avec méthodes/préconditions/sous-tâches), `leaf_tasks` (signatures des tâches feuilles), `primitive_actions` (doc des actions ROS). Rechargée à chaud par `bdd/tasks_methods.py::load_kb()`. | Modifié en non-committé (voir §4). 8 missions "top-level" assignables directement par le générateur IA (`_TOP_LEVEL_MISSIONS`, cf. §2) : `veiller`, `rentrer_a_la_base`, `suivre_agent`, `reconnaissance`, `deploiement_drone`, `surveiller_zone`, `eviter`, `encercler` — plus `naviguer_vers_base` (brique interne, jamais assignée directement) et `reagir_conditions` (tâche générée dynamiquement par l'IA pour les cas conditionnels, cf. plus bas). |
| `tasks_methods.py` (447 lignes, non modifié depuis HEAD hormis le diff WIP) | Cœur de la résolution : préconditions (`_check`), résolution de tokens `__xxx__` → nom d'agent concret (`_resolve`, `_resolve_agent_token`, `_find_agent_by_pattern`, `_nearest_agent`), génération dynamique de méthodes GTPyhop depuis la KB JSON (`_make_method`, `load_kb`), et les méthodes "feuilles" de mouvement (`aller_a_agent_m`, `suivre_m`, `maintenir_contact_m`, `aller_a_position_m`, `orbiter_m`, `interposer_m`). Contient aussi `collect_watched_tokens`/`resolve_watched_agents` utilisés par `main.py` pour la replanification événementielle. | Très documenté en commentaires inline (qui expliquent des bugs passés corrigés — ex. l'oscillation liée à `False` vs `[]` dans GTPyhop, le "spinning in place" sur `aller_a_position_m`). `load_kb()` vide explicitement `_task_method_dict[task_name]` avant de recharger — commentaire explique que sans ça, chaque sauvegarde de KB dupliquait les méthodes (bug corrigé, documenté en place). |
| `primitives_actions.py` (108 lignes) | Actions primitives réelles : `spawn_vessel` (spawn ROS via action `/lotusim/mas_cmd`), `aller_a`/`c_aller_a` (action pure vs commande ROS envoyant un waypoint), `creation_agent` (marqueur d'état pour "activer" un drone compagnon — **ne spawn PAS réellement un nouvel agent ROS**, limitation documentée en commentaire : l'architecture ne supporte qu'un thread de planification par agent, fixé au démarrage depuis le fichier scénario). | `heading` reçu en degrés (convention scénario/UI) mais converti en radians pour `MASCmd.heading` — conversion documentée par commentaire, cohérente avec `main.py`/UI. |
| `utils.py` (56 lignes) | Utilitaires génériques : `distance_deg`, `in_zone`, `agent_conditions` (compat rétro `equipement` → `conditions`), `check_condition` (préconditions "state_*" partagées entre le planificateur réel et un éventuel dry-run). | `agent_conditions` : fallback "legacy" sur la clé `equipement` — **aucun scénario actuel n'utilise `equipement`** (tous utilisent `conditions`), donc ce chemin est mort dans l'état actuel du dépôt, sauf compat ascendante pour d'anciens fichiers scénario non présents ici. |
| `ai_scenario_generator.py` (1704 lignes) | Générateur de scénarios en langage naturel → JSON structuré, via Ollama/Mistral local. Détaillé en §2. | Fichier le plus gros et le plus dense en logique métier du dépôt, largement modifié en non-committé (+588/-178 lignes de diff). |

### `scenarios/` (fichiers de scénarios = `AGENTS = {...}` littéral Python)

Tous les scénarios actuellement présents sur disque (5 trackés + inchangés, 1 tracké supprimé,
2 nouveaux non trackés) :

| Fichier | Statut Git | Contenu / ce qu'il exerce |
|---|---|---|
| `2_agents_patrolling.py` | **non tracké (nouveau)** | 2 agents ; `Agent2` utilise la mission `reagir_conditions` (tâche générée par le diff KB non committé — voir §4) avec `commande: attaquer` + `eviter_threshold`. Sert clairement de test manuel pour la fonctionnalité en cours de développement. |
| `demo_veille_drone_intru.py` | **non tracké (nouveau)** | 3 agents (`veilleur` passif, `drone1` en `suivre_agent`, `intrus` mobile). Commentaire explicite sur le calibrage des distances pour que la démo soit visuellement parlante. |
| `deux_agents_cercle.py` | tracké, propre | `agent1` passif, `agent2` en `encercler` — exemple canonique de la mission "encercler" ajoutée au commit `4879212`. |
| `evitement_mutuel.py` | tracké, propre | 2 agents en `eviter` mutuel, chacun ciblant l'autre explicitement via `conditions.cible`. |
| `reconnaissance_drone.py` | tracké, propre | 3 agents : `veilleur` (mission `reconnaissance`, `drone_available: True`), `drone1` (`suivre_agent`), `cible` (passif). |
| `surveillance_zone.py` | **supprimé, non committé** (`git status`: `D`) | Exerçait `surveiller_zone` (les 3 méthodes de la tâche, dans l'ordre) avec un agent `role: zone`. **Conséquence : plus AUCUN scénario sur disque n'exerce `surveiller_zone` / le rôle `zone` actuellement** — la fonctionnalité existe toujours dans le code et la KB mais n'a plus d'exemple vivant. Suppression volontaire ou accidentelle : NON TROUVÉ DANS LE CODE (pas de message expliquant pourquoi). |

Scénarios supprimés lors du commit `469c9fe` (remplacés/obsolètes, listés pour mémoire — absents
du disque) : `2_agents_circling.py`, `deploiement_drone_direct.py`, `deux_agents_demi_tour.py`,
`poursuite_intrus.py`, `reconnaissance_sans_drone.py`, `retour_base.py`,
`surveillance_zone_deux_drones.py`, `veille_passive.py`. Historique uniquement, pas d'action requise.

### `templates/`

| Fichier | Rôle réel |
|---|---|
| `index.html` (2673 lignes) | SPA monofichier (style inline `<style>`, JS inline `<script>`, pas de framework, pas de build step). Trois onglets : **Scénarios** (éditeur d'agents), **Connaissances HTN** (éditeur visuel de la KB JSON), **🤖 IA** (générateur langage naturel). Communique avec `app.py` via `fetch()` sur les routes `/api/*`. Détaillé en §3. |

### `tests/`

| Fichier | Rôle réel |
|---|---|
| `test_intruder_resolution.py` (46 lignes) | 3 tests `unittest` sur `bdd.tasks_methods._resolve` : résolution de `__intruder__`/`__base__` via marqueur `is_xxx`, et `__any__` via plus-proche-agent. **Seul fichier de test du dépôt.** Exécuté : `python3 -m pytest -q` → 3/3 passent dans l'environnement d'audit. | Ne teste PAS : `ai_scenario_generator.py` (0 test malgré 1704 lignes et une logique de parsing/heuristiques très dense), `app.py` (aucun test d'API HTTP), `primitives_actions.py`/`main.py` (nécessiteraient un mock ROS, absent). |

### `logs/`

| Fichier | Rôle réel |
|---|---|
| `poses.csv` (7273 lignes), `waypoints.csv` (53 lignes) | Logs bruts d'une exécution réelle passée (ignorés par Git). Contiennent des positions/timestamps concrets — pas de données sensibles apparentes (juste lat/lon dans la zone LOTUSim configurée), mais ce sont des artefacts d'exécution, pas du code. |
| `map.html` (65 lignes) | Généré par `visualize.py`. Tracké en Git (voir remarque `.gitignore` ci-dessus) et modifié dans le diff non committé actuel (+2/-2, probablement re-généré lors d'un test manuel). |

### Fichiers absents notables

- Pas de `README.md` à la racine (seulement `AI_GENERATOR_README.md`, spécifique au générateur IA).
  Aucune doc générale d'installation/architecture du projet dans son ensemble.
- Pas de `LICENSE`.
- Pas de CI (`.github/workflows/`, etc.) — NON TROUVÉ.
- Pas de `bdd/events.py` — existait, supprimé au commit `3376389` ("dead code").

---

## 2. `bdd/ai_scenario_generator.py` — détail (fichier le plus complexe du dépôt)

Point d'entrée : `generate_scenario_from_description(description, existing_kb=None)` →
tuple `(scenario|None, warnings, kb_updates, clarification_questions|None, refusal_reason|None)`.
Appelé depuis `app.py::generate_scenario`.

Pipeline réel (dans l'ordre) :

1. **Filtre "signal actionnable"** (`_has_actionable_signal`) — refuse *avant même d'appeler le LLM*
   si la description ne contient ni intrus/menace ni mot-clé de mission. Retourne des questions de
   clarification plutôt que de laisser le LLM halluciner.
2. **Refus déterministe pré-LLM** pour les formes de mouvement non supportées (carré, spirale,
   zigzag, étoile, figure en huit — `_mentions_unsupported_shape`) et pour l'interposition non
   couplée à une condition de menace (`_mentions_interposition_phrase`).
3. **Détection déterministe de branches conditionnelles** (`_detect_multi_condition_branches`) —
   parse chaque ligne `si <condition> : <comportement>` de la description, indépendamment du LLM,
   pour construire directement une tâche composite `reagir_conditions` dans la KB (plusieurs
   méthodes = plusieurs branches). Remplace un ancien système à 3 détecteurs séparés qui perdait
   silencieusement des clauses (documenté en commentaire comme bug corrigé).
4. **Appel LLM** (`_parse_scenario_from_description` → `_query_ollama`, modèle `mistral`, mode JSON
   forcé, température 0.15, timeout 90s) avec un prompt très structuré (`_build_prompt`, ~100 lignes)
   qui liste les 8 missions autorisées, les règles de comptage d'agents, et un mécanisme
   d'auto-correction : si le nombre d'agents/intrus ne correspond pas à ce que le texte dit, une
   **seconde requête LLM** est faite avec un message de correction (`MAX_RETRIES = 1`, donc 2 appels
   LLM max par génération).
5. **Garde-fous déterministes post-LLM** : clamp des coordonnées dans la zone LOTUSim valide
   (`LAT_RANGE`/`LON_RANGE`, car le LLM hallucine parfois des coordonnées hors zone), normalisation
   du modèle de véhicule vers une liste blanche (`VALID_MODELS`), validation structurelle de toute
   tâche suggérée par le LLM (`_validate_suggested_method` — détecte par ex. une précondition de
   distance à `__self__`, toujours 0, donc jamais déclenchable), réparation de tokens mal formés
   (`_repair_suggested_tokens` — le LLM écrit parfois `__agent2__` pour désigner littéralement l'agent
   `agent2`).
6. **Refus final si toujours cassé après retry** — le générateur préfère répondre `cannot_model`
   plutôt que d'écrire un scénario qui "a l'air" complet mais ne ferait pas ce qui est demandé
   (principe explicite en commentaire, répété à plusieurs endroits du fichier).
7. **Enrichissement de la KB** (`_enrich_kb_with_methods`) — écrit les nouvelles tâches/méthodes
   directement dans `bdd/knowledge_base.json` sur disque (`_save_kb`), donc **une génération IA
   modifie l'état global partagé de la KB**, pas seulement le scénario retourné à l'utilisateur.

### Point d'architecture non documenté ailleurs : le token `__self__` en sortie du générateur

Le JSON retourné par `generate_scenario_from_description` contient des missions littéralement
sous la forme `"veiller __self__"`, `"eviter __self__"`, etc. (`__self__` non résolu). La
résolution `__self__` → nom réel de l'agent **n'a lieu ni côté serveur, ni dans
`bdd/tasks_methods.py`**, mais **côté client JS**, dans `templates/index.html:2609`
(`importGeneratedScenario()`) via `.replace(/__self__/g, name)`, juste avant l'appel
`POST /api/scenario/<name>` qui écrit le fichier scénario final. **Conséquence directe** : le
JSON brut renvoyé par `POST /api/generate-scenario` (visible par ex. via `curl` ou un futur
client API) contient des missions non résolues et n'est pas exécutable tel quel — seul le
chemin "Importer comme scénario" du bouton UI fait cette substitution. Personne ne documente
ce contrat implicite entre le back et le front à cet endroit.

### Commentaire obsolète repéré

`templates/index.html:2537-2539` :
```js
// Every agent shares the same "operer" mission — what actually differs is the
// task chain its conditions resolve to. The backend walks that chain for us.
const taskPath = (a.resolved_task || ['operer']).map(escHtml).join(' → ');
```
Il n'existe **aucune tâche `operer`** dans `bdd/knowledge_base.json` ni ailleurs dans le code
actuel (`grep -rn "operer"` ne trouve que ces 2 lignes). `operer` semble être un vestige de
l'architecture décrite dans le message du commit `3376389` ("single generic 'operer' entry
point reusable across any scenario type") — design abandonné depuis (remplacé par les 8
missions top-level actuelles), mais le commentaire et le fallback `['operer']` n'ont pas été
mis à jour. Le fallback ne se déclenche que si `a.resolved_task` est absent, ce qui n'arrive
plus dans le flux actuel (`ai_scenario_generator.py` renseigne toujours `resolved_task`) —
donc code mort en pratique, mais trompeur pour quiconque lit ce commentaire en pensant que la
tâche `operer` existe encore.

---

## 3. `templates/index.html` — structure JS (aperçu, pas ligne à ligne)

~90 fonctions JS globales, pas de module bundler, tout dans un seul `<script>` (lignes
1185–2671). Organisation par sections commentées :

- **Éditeur de scénarios** (`renderEditor`, `buildCard`, `collectAgents`, `saveScenario`,
  `deleteScenario`, `launchScenario`, `computePlan`) — CRUD sur les fichiers `scenarios/*.py`
  via l'API, plus un bouton "calculer le plan" qui appelle `/api/scenario/<name>/plan` (dry-run
  GTPyhop sans exécution ROS, cf. `app.py::_compute_plan`).
- **Dépendances de mission** (`getTaskAgentDeps`, `resolveMissionDeps`, `updateMissionDeps`,
  `collectUnmetMissionDeps`) — logique côté client qui **duplique en JS** une partie de la
  logique de résolution de tokens qui existe déjà en Python (`bdd/tasks_methods.py`), pour
  afficher des avertissements dans l'UI (ex. "nécessite un agent role:intruder") avant même
  d'appeler le serveur. Risque de divergence si l'un des deux est modifié sans l'autre — à
  vérifier lors de tout changement de `_resolve_agent_token`/`resolve_tokens`.
- **Éditeur de KB** (`renderKB`, `buildTaskCard`, `buildMethodCard`, `buildPrecondRow`,
  `buildSubtaskRow`, `collectKB`, `saveKB`) — éditeur visuel complet des tâches/méthodes/
  préconditions/sous-tâches de `knowledge_base.json`, avec auto-save partiel
  (`scheduleKBAutoSave`).
- **Onglet IA** (`generateScenarioFromAI`, `displayGeneratedScenario`, `importGeneratedScenario`,
  `showClarificationQuestions`) — appelle `/api/generate-scenario`, affiche warnings/questions de
  clarification, gère l'import (avec la substitution `__self__` documentée ci-dessus).

`escHtml` est utilisé de façon quasi-systématique sur le contenu injecté dynamiquement (noms
d'agents, labels de tâches, messages d'erreur) — pas d'audit XSS approfondi mené ici, mais le
pattern général est cohérent (échappement avant insertion HTML). Pas vérifié exhaustivement
ligne par ligne.

---

## 4. Diff non committé actuel (état de travail en cours, WIP)

D'après `git diff --stat` sur la branche `htn_implementation` :

```
bdd/ai_scenario_generator.py   | 588 ++++++++++++++++++++++++++++++++---------
bdd/knowledge_base.json        |  61 ++++-
bdd/tasks_methods.py           |  27 ++
logs/map.html                  |   4 +-
scenarios/surveillance_zone.py |  40 --- (supprimé)
templates/index.html           |  10 +-
```
Plus 2 fichiers non trackés : `scenarios/2_agents_patrolling.py`,
`scenarios/demo_veille_drone_intru.py`.

Résumé de ce que fait ce WIP (déduit du diff, pas d'un message de commit — rien n'est encore
committé) :
- Ajout complet et cohérent, sur les 3 fichiers à la fois, de la mécanique d'interposition
  (agent positionné entre une menace et un protégé) — **absent de HEAD partout**, vérifié par
  `git show HEAD:<fichier> | grep interposer` sur les 3 fichiers concernés (aucune occurrence) :
  - `tasks_methods.py` : nouvelle fonction `interposer_m` + `declare_task_methods('interposer', ...)`.
  - `knowledge_base.json` : nouvelle entrée `"interposer"` dans `leaf_tasks` (args: 3 agents).
  - `ai_scenario_generator.py` : le code qui référence `interposer` (`_parse_branch_behavior`,
    branche `'interpose'` dans `multi_task_name`, cf. §2) fait partie du **même diff non
    committé** (+588/-178 lignes) — ce n'est pas du code déjà committé qui pointait vers une
    tâche manquante, c'est une fonctionnalité ajoutée de façon cohérente sur les 3 fichiers en
    une seule fois. Avant ce WIP, la mission "interposition" n'existait tout simplement pas
    dans le pipeline (ni détectée, ni exécutable).
- Renommage de la tâche KB `reagir_commande` → `reagir_conditions`, avec une nouvelle méthode
  `reagir_conditions_m1` combinant DEUX préconditions (`state_equals commande=attaquer` ET
  `distance_below`) — exactement le mécanisme "plusieurs clauses combinées par ET" documenté
  dans `_parse_branch_conditions`. Les anciennes valeurs `commande=cercle`/`commande=rine`
  disparaissent, remplacées par un enchaînement distance-only (m2/m3).
- `logs/map.html` régénéré (probablement suite à un test manuel de `main.py`/`visualize.py`).
- `templates/index.html` : ajout d'un bloc d'aide UI expliquant la syntaxe
  `si distance(agent1) > 100 m : ...` dans l'onglet IA (documentation utilisateur de la
  fonctionnalité `_detect_multi_condition_branches`).

**Cohérence** : le scénario non tracké `2_agents_patrolling.py` utilise déjà
`'mission': ('reagir_conditions', 'Agent2')` avec `commande: 'attaquer'` — cohérent avec le
nouveau nom de tâche dans le diff KB non committé. Le WIP est donc un tout cohérent en cours de
test manuel, pas des changements orphelins.

---

## 5. Contradictions / ambiguïtés à signaler explicitement

### 5.1 Port HTTP : 5000 (commentaire) vs 8080 (code réel, et doc)
`app.py:5` (docstring) dit `http://localhost:5000`. Le code réel (`app.py:351`,
`port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080`) et `AI_GENERATOR_README.md` disent
**8080**. Confirmé par test réel (`timeout 4 python3 app.py 8091` répond correctement sur le
port passé en argument). Le commentaire ligne 5 est simplement faux/périmé.

### 5.2 `main.py` : scénario par défaut inexistant
`main.py:110` : `_scenario_name = sys.argv[1] if len(sys.argv) > 1 else 'scenario_1'`.
`scenarios/scenario_1.py` a été supprimé au commit `3376389`. Lancer `python3 main.py` sans
argument plante à l'import (`ModuleNotFoundError`). En pratique, `main.py` n'est jamais lancé
sans argument dans ce projet — toujours via `app.py::launch_scenario`
(`subprocess.Popen([sys.executable, 'main.py', params['name']], ...)`, qui passe toujours un nom
explicite) — donc ce n'est pas un bug bloquant en usage normal via l'UI, mais c'est un piège pour
quiconque lance `main.py` directement en CLI sans lire le code, et le défaut n'a pas été mis à
jour depuis la suppression des anciens scénarios.

### 5.3 GTPyhop : "version 1.1" vs message d'import "version 1.0"
Cf. §1, fichier tiers vendorisé (`gtpyhop.py`), incohérence pré-existante dans le fichier
externe lui-même, pas introduite par ce projet.

### 5.4 Commentaire "operer" obsolète dans `index.html`
Cf. §2. Fallback JS mort en pratique, mais commentaire trompeur qui décrit une architecture
abandonnée.

### 5.5 `logs/map.html` tracké en Git, `logs/*.csv` non
Cf. §1. Incohérence de convention `.gitignore` — pas d'explication trouvée dans le code/les
messages de commit.

### 5.6 `AI_GENERATOR_README.md` documente des modèles LLM alternatifs non branchés dans le code
La section "Available Models" (mistral/neural-chat/llama2/dolphin-mixtral) suggère une
flexibilité qui n'existe pas dans l'UI — le seul moyen de changer de modèle est d'éditer en dur
`_query_ollama(prompt, model="mistral")` dans le code source. Pas de select UI, pas de variable
d'environnement, pas de config file pour ça. La doc dit "Edit `bdd/ai_scenario_generator.py`" —
donc en un sens elle est honnête sur la procédure, mais le tableau comparatif de modèles laisse
penser à un choix plus accessible qu'il ne l'est réellement.

### 5.7 Scénario `surveillance_zone.py` supprimé sans trace de raison
Cf. §1. Suppression non committée, aucun message expliquant si c'est intentionnel (remplacement
prévu par un autre scénario zone) ou un nettoyage accidentel pendant les tests manuels du WIP.
**À confirmer avec l'utilisateur avant tout commit.**

### 5.8 Contrat implicite `__self__` non résolu entre back et front
Cf. §2. Non documenté nulle part explicitement comme "contrat d'API" — seul un commentaire JS
local (`index.html:2608`) l'explique, côté consommateur, pas côté producteur
(`ai_scenario_generator.py` ne documente pas que sa sortie contient des tokens non résolus
destinés à être substitués par l'appelant).

### 5.9 Absence totale de tests pour `ai_scenario_generator.py`
1704 lignes de logique (parsing regex, heuristiques anti-hallucination, retry LLM, validation
structurelle) sans un seul test unitaire, alors que `tasks_methods.py` (447 lignes) a 3 tests
dédiés. Écart de couverture significatif vu la complexité relative des deux fichiers.

### 5.10 Pas de fichier de dépendances
Cf. §0. `requests`, `rclpy`, `geographic_msgs`, `lotusim_msgs` sont requis mais non déclarés
nulle part (pas de `requirements.txt`). Reproductibilité de l'environnement : repose entièrement
sur la mémoire/l'environnement local de l'utilisateur (confirmé fonctionnel dans l'environnement
d'audit, mais non portable tel quel sans le workspace ROS externe `~/lotusim_ws`).

---

## 6. Points d'entrée (résumé)

| Commande | Ce qu'elle fait | Dépendances requises |
|---|---|---|
| `python3 app.py [port]` | Lance l'UI web (défaut port 8080) | stdlib + `requests` (import de `ai_scenario_generator`) |
| `python3 main.py <nom_scenario>` | Lance la simulation ROS2 réelle contre LOTUSim | ROS2 Humble, `rclpy`, `geographic_msgs`, `lotusim_msgs`, LOTUSim actif sur `/lotusim/*` |
| `python3 visualize.py [poses.csv] [waypoints.csv]` | Génère `logs/map.html` et l'ouvre | stdlib uniquement (Leaflet via CDN dans le HTML généré) |
| `python3 -m pytest -q` | Lance les 3 tests unitaires | stdlib + `gtpyhop` (aucune dépendance ROS) |
| `bash INSTALL_OLLAMA.sh` | Installe Ollama + télécharge `mistral` | `curl`, accès réseau |
| `ollama serve` | Backend LLM local requis par l'onglet IA | Ollama installé, port 11434 |

---

## 7. Ce qui n'a PAS été audité en profondeur (limites de cet audit)

- Pas de revue ligne-à-ligne complète de `templates/index.html` (2673 lignes) — structure et
  fonctions cartographiées, logique interne de chaque fonction JS pas vérifiée exhaustivement.
- Pas de test réel de bout en bout du flux `/api/generate-scenario` (Ollama était disponible et
  répondait dans l'environnement d'audit — modèle `mistral:latest` chargé — mais aucune
  génération réelle n'a été déclenchée pour ne pas modifier `knowledge_base.json` pendant
  l'audit).
- Pas de lancement réel de `main.py` contre un LOTUSim actif (nécessiterait le simulateur, hors
  périmètre de ce dépôt).
- Contenu des autres branches (`main`, `event_management`, `improveFollow`, `conditionScenario`,
  `newSceanrios`) non comparé au détail — seule `htn_implementation` (branche courante) a été
  auditée.
- Pas d'analyse de sécurité formelle (XSS, injection) au-delà de l'observation que `escHtml` est
  utilisé de façon apparemment systématique côté front, et que `app.py` écrit des fichiers
  scénario Python via `repr()` (pas d'`eval`/`exec` sur une entrée utilisateur observé, mais pas
  vérifié pour 100% des chemins).
