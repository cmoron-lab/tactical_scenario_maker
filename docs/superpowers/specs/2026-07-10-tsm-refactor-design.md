# Design — Réorganisation du POC en couches + schéma canonique de scénario

**Date :** 10 juillet 2026
**Statut :** validé en session, prêt pour plan d'implémentation
**Référence :** [ARCHITECTURE.md](../../ARCHITECTURE.md) — cet incrément réalise les impacts 1 (schéma canonique) et 8 (frontière GTPyhop) de sa section 12, et répond à sa question ouverte n°10 (prochain incrément démontrable).

## 1. Objectif et périmètre

Rendre le POC maintenable : découper en couches (domaine / planification / exécution / adaptateur LOTUSim / web), introduire un schéma canonique JSON pour les scénarios, supprimer les états globaux et imports circulaires. **Iso-fonctionnel** par ailleurs : même comportement observable (waypoint follower, boucle de replanification événementielle, mêmes routes HTTP).

**Hors périmètre (décisions de session) :**

- Le générateur IA est **parqué** : `bdd/ai_scenario_generator.py` part dans `attic/` (avec `AI_GENERATOR_README.md` et `INSTALL_OLLAMA.sh`), hors du paquet, intact. `/api/generate-scenario` répond 501, l'onglet IA de l'UI est masqué. Sa réadaptation au schéma canonique est un incrément dédié.
- L'UI locale est adaptée **a minima** (appels API vers le schéma canonique, onglet IA masqué). Pas de découpage en fichiers statiques : le doc d'architecture oriente vers l'IHM officielle à terme, tout investissement lourd ici serait jetable.
- Pas de cycle de vie des objectifs (D5), pas d'encapsulation en « autonomies » (D3/D6), pas de gestion de cycle de vie des runs : le launch reste un `Popen` de `main.py`. Ce sont les incréments suivants.

## 2. Structure cible du paquet

```
tactical_scenario_maker/            # repo
├── app.py, main.py                 # shims (~5 lignes) → tsm ; mêmes commandes qu'avant
├── tsm/
│   ├── domain/
│   │   ├── scenario.py             # dataclasses Scenario/Agent/Mission, from_dict/to_dict, validation
│   │   ├── doctrine.py             # propriétaire unique de knowledge_base.json : un path, load, save
│   │   └── geo.py                  # distance_deg, in_zone, agent_conditions (ex bdd/utils.py)
│   ├── planning/
│   │   ├── planner.py              # classe Planner : encapsule gtpyhop (domaine privé, verrou)
│   │   └── methods.py              # KB→méthodes GTPyhop, 6 méthodes feuilles (orbite, interposition…),
│   │                               # résolution de tokens (__self__, __intruder__, __cible__, __drone__)
│   ├── execution/
│   │   ├── runtime.py              # main(scenario) : assemble client + planner + runners
│   │   ├── runner.py               # boucle agent événementielle (ex run_agent), RunLogs (CSV)
│   │   └── actions.py              # factory make_actions(client, logs) → actions/commands HTN
│   ├── lotusim/
│   │   └── client.py               # LotusimClient : nœud rclpy, spawn, SetWaypoints, poses + watch
│   ├── web/
│   │   ├── server.py               # http.server, routing (ex app.py)
│   │   └── api.py                  # handlers ↔ domaine (list/get/save/delete/plan/launch/kb)
│   └── vendor/
│       └── gtpyhop.py              # copie GTPyhop 1.1 (Dana Nau, BSD) — non modifiée
├── scenarios/*.json                # données versionnées (plus de .py générés)
├── attic/                          # générateur IA parqué + sa doc
├── templates/index.html            # UI locale, adaptée a minima
├── tests/
└── pyproject.toml                  # outillage dev uniquement (ruff, mypy, pytest via uv)
```

`bdd/` disparaît. `visualize.py` et `logs/` sont inchangés. **Aucune dépendance runtime ajoutée** : le code doit tourner dans l'environnement Python de ROS 2 ; stdlib seulement (c'est déjà le cas et c'est une propriété à préserver).

## 3. Schéma canonique de scénario

Un fichier JSON par scénario dans `scenarios/`. L'identité du scénario est son nom de fichier (pas de champ `name` dupliqué à l'intérieur — une seule source de vérité).

```json
{
  "version": 1,
  "agents": {
    "veilleur": {
      "position": {"lat": 1.260, "lon": 103.750},
      "heading_deg": 0.0,
      "model": "wamv",
      "velocity": {"linear": [0.0, 5.0], "angular_max": 0.05},
      "conditions": {"role": "patrol", "base_location": "1.260 103.750"},
      "mission": {"task": "veiller", "args": ["veilleur"]}
    }
  }
}
```

Décisions :

- **Mission structurée** `{task, args}`. Le parsing heuristique `_str_to_mission` (deux floats consécutifs devinés en position) meurt. Les arguments de type position sont des tableaux `[lat, lon]` en JSON, convertis en tuples au chargement (format attendu par les méthodes GTPyhop).
- **Vocabulaire assumé** : `mission.task` référence une tâche de la doctrine HTN (`knowledge_base.json`). La couche « capacités » de l'architecture cible viendra plus tard ; ce point est reporté dans ARCHITECTURE.md v2 (voir §8).
- **`x`/`y` renommés** `position.lat`/`position.lon` (le POC utilisait `x` pour la latitude et `y` pour la longitude).
- **`conditions`** reste un dict libre orienté KB (iso-fonctionnel), y compris `base_location` en chaîne `"lat lon"`.
- **Validation** : dataclasses + `from_dict` levant `ScenarioError` avec messages explicites (champ manquant, type invalide, version inconnue). Pas de pydantic ni jsonschema.
- **Migration** : script one-shot convertissant les 5 scénarios `.py` existants ; les `.json` résultants sont committés, les `.py` et le script supprimés dans la même branche.

La **KB garde son format actuel** (iso-fonctionnel) mais gagne un propriétaire unique : `domain/doctrine.py` — un seul chemin (contre trois constantes aujourd'hui), une seule sérialisation (`ensure_ascii=False` partout).

## 4. Planner : GTPyhop derrière une frontière

```python
class Planner:
    def __init__(self, kb, actions, commands=()): ...
        # crée SON gtpyhop.Domain, enregistre méthodes built-in + KB,
        # actions et commands — explicitement
    def find_plan(self, state, task): ... # sous verrou interne
    def reload_kb(self, kb): ...          # ré-enregistrement des méthodes KB
```

- **Plus d'effet de bord d'import** : importer un module ne crée plus de domaine GTPyhop et n'enregistre plus rien. L'ordre d'import manuel fragile (`Domain(...)` avant `import bdd.tasks_methods`) disparaît.
- GTPyhop rebinde `current_domain` globalement à la construction de chaque `Domain` : le verrou du Planner **rebinde `gtpyhop.current_domain` avant chaque `find_plan`**, ce qui sérialise du même coup les replanifications des threads agents (aujourd'hui concurrentes sans verrou sur un état partagé). Coût négligeable : un `find_plan` dure quelques millisecondes.
- Le `pop` dans le `_task_method_dict` privé (nécessaire car `declare_task_methods` ne fait qu'accumuler) survit, mais confiné à `planner.py` et commenté.
- **gtpyhop.py n'est pas forké** : vendored intact dans `tsm/vendor/`, exclu de ruff/mypy. Seul retrait toléré : le `print` de bannière à l'import, si trivial ; sinon on le laisse.

Le web construit un Planner avec les **actions pures** seulement (préview de plan, pas de ROS). Le runtime construit le sien avec les commands liées au `LotusimClient`.

## 5. Exécution et adaptateur LOTUSim

- **`lotusim/client.py` — `LotusimClient`** : possède le nœud rclpy et le thread executor ; expose `spawn_vessel(...)`, `set_waypoints(agent, points)`, la souscription `/lotusim/poses` et `register_watch(name, event)` (mécanisme wake-on-change conservé tel quel, y compris `POSITION_EPSILON_DEG` et le flush systématique des CSV). L'attente de futures (`_wait`) devient un helper privé du client. C'est la couture où se brancheront les autonomies de la cible (§7.6 d'ARCHITECTURE.md).
- **`execution/runner.py`** : boucle agent événementielle inchangée dans son comportement (réveil sur changement de position observée, `REPLAN_SAFETY_TIMEOUT` en filet), plus `RunLogs` (poses.csv, waypoints.csv) passé explicitement — les globals de module (`_pose_log`, `_waypoint_log`, `_ros_node`) disparaissent.
- **`execution/actions.py`** : GTPyhop appelle les actions avec `(state, *args)` uniquement — d'où l'`import main` circulaire actuel. Fix : les actions pures (`aller_a`, `creation_agent`) sont des fonctions de module sans dépendance ; les commands liées au ROS sortent d'une factory `make_commands(client, logs)` retournant les closures à déclarer au Planner. Le web n'enregistre que les pures ; le runtime enregistre les deux. Le hack `sys.modules.setdefault('main', ...)` meurt.
- **`execution/runtime.py`** : l'assemblage (ex `main.main()`) — construire client, planner, état initial, spawner les agents, lancer un runner par agent, arrêt propre.

## 6. Web et UI

- `web/server.py` conserve `http.server` (stdlib) et **les mêmes routes**. Les routes scénario parlent le schéma canonique tel quel — plus de conversion aller-retour vers un format « formulaire ».
- UI (`templates/index.html`), modifications confinées : le mission builder envoie `{task, args}` (le JS connaît déjà les tâches et leurs arguments), lecture des champs renommés (`position`, `velocity`), onglet IA masqué. Le reste (~2 700 lignes) n'est pas touché — y compris la logique HTN dupliquée en JS, assumée comme dette connue de l'UI locale jetable (documentée dans ARCHITECTURE.md v2).
- `/api/generate-scenario` → 501 `{"error": "générateur IA parqué — voir attic/"}`.

## 7. Gestion d'erreurs

- `ScenarioError` (validation) → réponse 400 avec le message ; scénario introuvable → 404 (comportement actuel conservé).
- Échec de spawn : loggé par agent, on continue (comportement actuel conservé).
- Aucun catch silencieux ; les erreurs inattendues remontent.

## 8. Tests, outillage, documentation

**Tests (pytest)** :

- schéma : round-trip `from_dict`/`to_dict`, erreurs de validation (champ manquant, type faux, version inconnue) ;
- planner : `find_plan` déterministe sur une KB fixture — décompositions attendues, préconditions non satisfaites → pas de plan ; `reload_kb` remplace bien les méthodes (pas d'accumulation) ;
- résolution de tokens : `test_intruder_resolution.py` adapté à la nouvelle structure ;
- les scénarios `.json` committés se chargent tous sans erreur.

Non testé unitairement, assumé : `lotusim/client.py` (transport ROS pur, se teste contre la sim), l'UI. La preuve d'exécution end-to-end de l'incrément : les tests passent, `app.py` sert l'UI et les routes répondent, et un run `main.py <scenario>` contre une instance LOTUSim se comporte comme avant (à vérifier manuellement, dit explicitement au moment du ship).

**Outillage** : `pyproject.toml` — ruff sur `tsm/` + `tests/` ; mypy **strict sur `tsm/domain/` et `tsm/planning/`**, normal ailleurs, `ignore_missing_imports` pour `rclpy`/`lotusim_msgs`, `tsm/vendor/` exclu de tout. uv pour l'outillage dev uniquement — le runtime reste sur le Python de l'environnement ROS.

**Documentation** :

- README refondu : quickstart (web, runtime, tests), carte du paquet ↔ composants logiques du §7 d'ARCHITECTURE.md, format de scénario avec exemple ;
- docstrings aux frontières de modules (chaque module de `tsm/` dit son rôle et ce dont il dépend) ;
- **ARCHITECTURE.md v2** : Q10 tranchée (cet incrément), Q1 partiellement tranchée (JSON versionné, v1), §12 mis à jour (fait / reste), et trois questions ouvertes affûtées issues de la relecture : (a) interaction HTN ↔ objectifs longs — quand un objectif est « en cours », le HTN replanifie-t-il, et qu'est-ce qui l'invalide ; (b) vocabulaire mission vs capacités — aujourd'hui `mission.task` = tâche de doctrine, assumé ; (c) propriétaire des événements de scénario et horloge de référence (temps sim vs temps mur, RTF ≪ 1 observé).

## 9. Ordre d'implémentation proposé

1. `pyproject.toml` + squelette `tsm/` + vendor gtpyhop + shims — l'existant continue de marcher pendant la migration ;
2. `domain/` (schéma + doctrine + geo) + tests ;
3. `planning/` (Planner + methods) + tests — c'est le morceau le plus délicat (verrou, ré-enregistrement) ;
4. `lotusim/client.py` + `execution/` (actions, runner, runtime) ;
5. `web/` + adaptation UI + migration des scénarios ;
6. parcage du générateur dans `attic/`, suppression de `bdd/` ;
7. ruff/mypy verts, README, ARCHITECTURE.md v2.

Chaque étape laisse le repo dans un état qui tourne.

## 10. Risques

| Risque | Mitigation |
|---|---|
| Régression de comportement du replan (verrou sérialise ce qui était concurrent) | Les `find_plan` durent quelques ms ; le wake-on-change est conservé ; vérification manuelle end-to-end contre LOTUSim avant de clore |
| L'UI casse sur un cas non couvert par l'adaptation a minima | Les routes gardent les mêmes chemins ; test manuel des trois onglets (le 3ᵉ étant masqué) |
| mypy strict trop coûteux sur `planning/` (closures dynamiques) | Le strict ne s'applique qu'à `domain/` et `planning/` ; si `methods.py` résiste, le passer en normal est acceptable et noté |
| Le format v1 oublie un champ utilisé par une méthode feuille | La migration des 5 scénarios réels + le test « tous les .json se chargent » le détecteraient |
