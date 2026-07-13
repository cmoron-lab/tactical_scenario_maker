# Escorte du détroit d'Ormuz — Plan d'implémentation v3

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Exécuter dans LOTUSim le scénario de référence « Escorte du détroit
d'Ormuz » avec forces, déclencheur, autonomies cinématiques, actions typées,
adjudication, verdict et provenance de run.

**Architecture:** Cette tranche implémente le cycle d'exécution de LSGA v3,
pas le pipeline HDDL de niveau 1. Un scénario v2 déclaratif et un profil
d'exécution distinct sont compilés en missions par force. Un contrôleur
séquentiel maintient un état du monde observé, donne à chaque superviseur sa
vue de force, et délègue uniquement les capacités explicitement publiées par
le backend sélectionné. La cellule blanche observe la vérité terrain, déclenche
l'apparition de la force rouge, arbitre l'engagement et prononce le verdict.

**Tech Stack:** Python >= 3.10, stdlib au runtime, GTPyhop vendored, rclpy et
lotusim_msgs fournis par l'image ROS Jazzy, pytest/ruff/mypy via uv.

## Périmètre et décision de découpage

Ce plan réalise les incréments v3 1 à 4 pour un scénario de référence :
schéma v2, cellule blanche, actions typées/follow_target et combat arbitré.
Il ne réalise pas le Domain HDDL, pandaPI, l'EAL complet ni le modèle de
perception réaliste ; ce sont les incréments v3 5 et 6 ou des travaux
ultérieurs. Le niveau 1 est donc représenté par les missions explicitement
affectées aux forces dans le Scenario Request, compilées en un ExecutionGraph
stable. Cette limite doit être visible dans le journal de run.

Les cinq scénarios v1 et leur éditeur restent utilisables pendant cet
incrément. Le nouveau scénario v2 est rendu en lecture seule dans l'IHM locale
et lancé avec un profil explicite. Une migration globale de v1 vers v2 est un
incrément séparé : elle ne doit pas retarder la preuve de chaîne complète.

Estimation : 2 à 4 jours de développement plus une demi-journée de validation
sur le rig ROS. Le plan doit être exécuté en petits commits, chacun vérifiable
sans ROS sauf la validation e2e finale.

## Global Constraints

- Zéro dépendance runtime ajoutée. Utiliser dataclasses, enum, uuid interdit
  pour les goal ids (un compteur de run déterministe suffit), pathlib, json,
  threading et queue de la stdlib.
- Les imports ROS restent confinés à tsm/lotusim/client.py et
  tsm/execution/runtime.py. Les modules domaine, objectifs, cellule blanche et
  contrôleur doivent être testables sans ROS.
- Ne pas inventer un navigateur universel. Le seul backend initial est
  lotusim.waypoint_follower, explicitement cinématique ; ses capacités sont
  navigation.goto et navigation.follow_target.
- Une capacité signifie « peut tenter et rapporter un résultat », jamais
  « réussit ». Tous les objectifs suivent submitted -> accepted -> in_progress
  -> succeeded|failed|cancelled|timed_out.
- La pose observée et son horodatage simulé, extraits de
  VesselPositionArray.header, sont la source de vérité. Ne jamais écrire la
  cible commandée comme pose observée.
- Une dégradation de fidélité est interdite. Un profil absent, une capacité
  absente, un spawn raté ou un service indisponible bloque le run avant les
  superviseurs.
- Le premier scénario utilise information_policy = omniscient pour les
  décisions, mais chaque superviseur reçoit une ForceView distincte. Aucune
  API publique ne doit dépendre de cette omniscience.
- Une force deferred est spawnée uniquement par la cellule blanche. Les
  identifiants de navires restent stables : le runtime purge au préflight les
  navires connus d'un run précédent avant de demander un spawn.
- Toutes les temporisations tactiques et le timeout de scénario utilisent le
  temps simulé, jamais datetime.now().
- La commande ROS MASCmd existe déjà pour CREATE_CMD et DELETE_CMD ; le
  waypoint follower fournit déjà SetWaypoints, stop et waypoint_reached. Ne
  modifier aucun checkout LOTUSim pour ce plan.
- Utiliser uv run pytest, uv run ruff check . et uv run mypy. Ne jamais lancer
  pip, npm, yarn, pnpm ou node directement.

## Definition of Done

- scenarios/escorte_ormuz.json (version 2) ne contient aucun modèle Gazebo,
  limite de vitesse ou réglage de guidage.
- profiles/kinematic-ormuz.json sélectionne, pour chaque agent, le backend,
  la fidélité, les paramètres de spawn et les capacités disponibles.
- Le run crée vert et bleu, attend le trigger de passage, crée rouge, fait
  poursuivre les vedettes, fait interposer puis engager l'escorte, fait replier
  la seconde vedette, puis termine sur succès quand le cargo atteint la sortie.
- Le résultat de chaque objectif provient d'une observation ou d'une
  adjudication ; l'ack SetWaypoints seul ne peut jamais conclure à un succès.
- Le rapport de run contient les snapshots scénario/profil/doctrine, les
  capacités résolues, les événements horodatés en temps simulé et le verdict
  métier séparé de l'état du sous-processus.
- La suite sans ROS couvre le scénario nominal, le timeout, un profil
  incompatible, un spawn refusé et la séparation des vues de force.
- Le rig conteneurisé valide le run nominal depuis l'IHM, avec verdict visible
  et retour à l'état idle.

## Carte des fichiers

| Fichier | Responsabilité |
| --- | --- |
| tsm/domain/reference.py | Schéma de Scenario Request v2 et compilation d'un ExecutionGraph authored |
| tsm/domain/profile.py | Schéma du profil d'exécution et validation statique capacités/missions |
| tsm/domain/conditions.py | Langage unique de conditions des triggers, end state et doctrine v3 |
| tsm/execution/world.py | Snapshots immuables du monde, temps simulé et vues par force |
| tsm/execution/objectives.py | Goal, cycle de vie, compteur d'identifiants et événements d'objectif |
| tsm/execution/autonomy.py | Provider cinématique WaypointFollower et provider d'engagement arbitré |
| tsm/execution/controller.py | Superviseurs par agent, contrôleur de run séquentiel et gestion des forces |
| tsm/execution/white_cell.py | Triggers, adjudication, end state et verdict |
| tsm/lotusim/client.py | Transport ROS : poses horodatées, spawn, delete, stop, waypoints |
| tsm/execution/runtime.py | Assemblage ROS et boucle de contrôleur v3 |
| tsm/web/runs.py | Répertoires de run, statut processus + verdict métier |
| tsm/web/api.py, tsm/web/server.py, templates/index.html | Lancement avec profil et affichage du verdict/provenance |
| doctrine/knowledge_base.json | Tâches de transit, escorte, poursuite, engagement et repli |
| scenarios/escorte_ormuz.json | Scenario Request v2 de référence |
| profiles/kinematic-ormuz.json | Profil séparé de fidélité cinématique |
| tests/reference_fixtures.py | Scenario, profil, snapshots et transport factice partagés par les tests v3 |
| tests/test_reference_*.py | Contrats purs v2, objectif, cellule blanche et contrôleur |

---

### Task 1: Contrats v2 du scénario, du profil et des conditions

**Files:**
- Create: tsm/domain/reference.py
- Create: tsm/domain/profile.py
- Create: tests/test_reference_schema.py
- Create: tests/test_execution_profile.py
- Create: tests/reference_fixtures.py
- Modify: tsm/domain/__init__.py

**Interfaces:**

~~~python
@dataclass(frozen=True)
class ForceSpec:
    agents: tuple[str, ...]
    spawn: Literal["initial", "deferred"] = "initial"

@dataclass(frozen=True)
class Zone:
    lat: float
    lon: float
    radius_deg: float

@dataclass(frozen=True)
class Relation:
    source: str
    targets: tuple[str, ...]
    attitude: Literal["hostile", "neutral", "allied", "protect"]

@dataclass(frozen=True)
class TacticalAgentSpec:
    platform: str
    position: Position
    mission: Mission
    conditions: Mapping[str, Any]

@dataclass(frozen=True)
class Trigger:
    id: str
    when: Mapping[str, Any]
    actions: tuple[Mapping[str, Any], ...]

@dataclass(frozen=True)
class EndState:
    success: tuple[Mapping[str, Any], ...]
    failure: tuple[Mapping[str, Any], ...]
    timeout_s: float

@dataclass(frozen=True)
class AgentExecutionSpec:
    fidelity: Literal["kinematic", "scripted", "dynamic"]
    providers: Mapping[str, Mapping[str, Any]]
    spawn: Mapping[str, Any]

@dataclass(frozen=True)
class ReferenceScenario:
    forces: Mapping[str, ForceSpec]
    relations: tuple[Relation, ...]
    zones: Mapping[str, Zone]
    agents: Mapping[str, TacticalAgentSpec]
    triggers: tuple[Trigger, ...]
    end: EndState
    information_policy: Literal["omniscient", "force_scoped"]

@dataclass(frozen=True)
class ExecutionProfile:
    name: str
    agents: Mapping[str, AgentExecutionSpec]

~~~

Exports exacts : ReferenceScenario.from_dict(doc), ReferenceScenario.to_dict(),
load_reference_scenario(name), ExecutionProfile.from_dict(doc),
load_profile(name), validate_profile(scenario, profile, required_capabilities)
et compile_authored_graph(scenario).

- [ ] **Step 1: Écrire les tests rouges du schéma v2**

~~~python
def test_reference_scenario_keeps_spawn_config_out_of_tactical_agents():
    doc = {
        "version": 2,
        "information_policy": "omniscient",
        "forces": {"verte": {"agents": ["cargo"]}},
        "relations": [],
        "zones": {"sortie": {"center": {"lat": 1.0, "lon": 2.0}, "radius_deg": 0.001}},
        "agents": {
            "cargo": {
                "platform": "surface_vessel",
                "position": {"lat": 1.0, "lon": 2.0},
                "mission": {"task": "transiter", "args": ["cargo", "sortie"]},
                "conditions": {},
            }
        },
        "triggers": [],
        "end": {"success": [{"type": "all_in_zone", "force": "verte", "zone": "sortie"}],
                "failure": [], "timeout": "PT60S"},
    }
    scenario = ReferenceScenario.from_dict(doc)
    assert scenario.to_dict() == doc
    with pytest.raises(ScenarioError, match="profil d.execution"):
        ReferenceScenario.from_dict({**doc, "agents": {**doc["agents"],
            "cargo": {**doc["agents"]["cargo"], "model": "wamv"}}})
~~~

- [ ] **Step 2: Écrire le test rouge du profil**

~~~python
def test_profile_rejects_missing_capability_for_assigned_mission():
    scenario = scenario_with_single_agent(
        agent="escorte", mission_task="escorter_convoi")
    profile = execution_profile(
        agent="escorte", capabilities={"navigation.goto"})
    with pytest.raises(ProfileError, match="engage.attack_target"):
        validate_profile(scenario, profile,
                         {"escorte": {"navigation.follow_target", "engage.attack_target"}})
~~~

Dans tests/reference_fixtures.py, créer exactement :

~~~python
def scenario_with_single_agent(agent: str, mission_task: str) -> ReferenceScenario:
    return ReferenceScenario.from_dict({
        "version": 2, "information_policy": "omniscient",
        "forces": {"bleue": {"agents": [agent]}}, "relations": [],
        "zones": {}, "triggers": [],
        "agents": {agent: {
            "platform": "surface_vessel",
            "position": {"lat": 1.0, "lon": 2.0},
            "mission": {"task": mission_task, "args": [agent]},
            "conditions": {},
        }},
        "end": {"success": [], "failure": [], "timeout": "PT60S"},
    })

def execution_profile(agent: str, capabilities: set[str]) -> ExecutionProfile:
    return ExecutionProfile.from_dict({
        "version": 1, "name": "test",
        "agents": {agent: {
            "fidelity": "kinematic",
            "providers": {"lotusim.waypoint_follower": {"capabilities": sorted(capabilities)}},
            "spawn": {
                "model": "wamv", "linear_velocity": [0.0, 5.0],
                "angular_velocity_max": 0.05, "heading_deg": 0.0,
            },
        }},
    })

~~~

Les helpers dépendant de l'état du monde, des objectifs et du contrôleur sont
ajoutés à ce fichier dans les tâches qui créent leurs types ; ne pas importer un
module futur dans Task 1.

- [ ] **Step 3: Vérifier les échecs**

Run:

~~~bash
uv run pytest tests/test_reference_schema.py tests/test_execution_profile.py -q
~~~

Expected: échec d'import des nouveaux modules.

- [ ] **Step 4: Implémenter les dataclasses et la validation**

Implémenter exactement les règles suivantes :

~~~python
def parse_duration(value: str) -> float:
    match = re.fullmatch(r"PT(?:(\d+(?:\.\d+)?)M)?(?:(\d+(?:\.\d+)?)S)?", value)
    if not match or match.group(1) is None and match.group(2) is None:
        raise ScenarioError(f"durée ISO-8601 v3 invalide: {value!r}")
    return float(match.group(1) or 0) * 60 + float(match.group(2) or 0)

~~~

Le profil doit contenir par agent fidelity, provider, spawn et capabilities.
spawn porte model, linear_velocity, angular_velocity_max et heading_deg ; ces
champs sont refusés dans TacticalAgentSpec. Un provider cinématique ne peut
déclarer que navigation.goto et navigation.follow_target ; le provider
adjudicated peut déclarer engage.attack_target.

- [ ] **Step 5: Compiler l'ExecutionGraph authored**

Dans reference.py, ajouter un artefact sérialisable qui ne prétend pas être une
sortie HDDL :

~~~python
@dataclass(frozen=True)
class ExecutionGraph:
    by_force: Mapping[str, Mapping[str, Mission]]

def compile_authored_graph(scenario: ReferenceScenario) -> ExecutionGraph:
    return ExecutionGraph({
        force: {agent: scenario.agents[agent].mission
                for agent in spec.agents}
        for force, spec in scenario.forces.items()
    })
~~~

Le test doit vérifier que les forces deferred sont présentes dans le graphe
mais non actives au démarrage.

- [ ] **Step 6: Vérifier les contrats purs**

Run:

~~~bash
uv run pytest tests/test_reference_schema.py tests/test_execution_profile.py -q
uv run ruff check tsm/domain tests/test_reference_schema.py tests/test_execution_profile.py tests/reference_fixtures.py
uv run mypy tsm/domain
~~~

Expected: tous les tests passent, Ruff et mypy sans erreur.

- [ ] **Step 7: Commit**

~~~bash
git add tsm/domain tests/test_reference_schema.py tests/test_execution_profile.py tests/reference_fixtures.py
git commit -m "feat: définir les contrats v3 scénario, profil et conditions"
~~~

---

### Task 2: État observé, temps simulé et transport LOTUSim sûr

**Files:**
- Create: tsm/execution/world.py
- Create: tsm/domain/conditions.py
- Create: tests/test_reference_world.py
- Create: tests/test_conditions.py
- Modify: tests/reference_fixtures.py
- Modify: tsm/lotusim/client.py
- Modify: tsm/execution/runner.py

**Interfaces:**

~~~python
@dataclass(frozen=True)
class WorldSnapshot:
    revision: int
    sim_time_s: float
    positions: Mapping[str, Position]
    destroyed: frozenset[str]

~~~

Méthodes exactes à exporter : WorldStore.update_poses(sim_time_s, positions),
WorldStore.mark_destroyed(agent), WorldStore.snapshot(), evaluate(condition,
world, scenario), LotusimClient.set_waypoints(agent, lat, lon, timeout_s),
LotusimClient.stop_vessel(agent, timeout_s), LotusimClient.spawn_vessel(
vessel, init_pos, model, linear_velocity, angular_velocity_max, heading_deg,
timeout_s) et LotusimClient.delete_vessel(agent, timeout_s).

- [ ] **Step 1: Écrire les tests rouges de WorldStore**

~~~python
def test_world_store_uses_simulated_time_and_never_predicts_a_goal():
    store = WorldStore()
    first = store.update_poses(5.0, {"cargo": Position(1.0, 2.0)})
    second = store.update_poses(5.2, {"cargo": Position(1.0001, 2.0)})
    assert first.sim_time_s == 5.0
    assert second.positions["cargo"] == Position(1.0001, 2.0)
    assert second.revision == first.revision + 1

def test_destroyed_agent_is_preserved_when_the_next_pose_message_omits_it():
    store = WorldStore()
    store.update_poses(1, {"red": Position(1, 2)})
    store.mark_destroyed("red")
    assert "red" in store.update_poses(2, {}).destroyed
~~~

- [ ] **Step 2: Vérifier l'échec**

Run:

~~~bash
uv run pytest tests/test_reference_world.py -q
~~~

Expected: échec d'import de WorldStore.

- [ ] **Step 3: Implémenter des snapshots copiés et immuables**

Chaque mutation copie les mappings, incrémente revision et expose MappingProxyType
ou une copie défensive. Les superviseurs reçoivent toujours le résultat de
snapshot(), jamais les dictionnaires internes. RunLogs ajoute sim_time_s à chaque
événement ; l'horodatage mur reste optionnel pour l'affichage uniquement.

~~~python
def _seconds(stamp: Any) -> float:
    return float(stamp.sec) + float(stamp.nanosec) / 1_000_000_000

def _cb(self, msg: VesselPositionArray) -> None:
    poses = {v.vessel_name: Position(v.geo_point.latitude, v.geo_point.longitude)
             for v in msg.vessels}
    self._on_world(_seconds(msg.header.stamp), poses)
~~~

Ajouter dans conditions.py les deux tests retirés de Task 1 :

~~~python
def test_all_in_zone_and_agent_destroyed_share_one_evaluator():
    scenario = scenario_with_single_agent("cargo", "transiter")
    scenario = replace(scenario, forces={"verte": ForceSpec(("cargo",))},
                       zones={"sortie": Zone(1.0, 2.0, 0.001)})
    world = WorldSnapshot(1, 12.0, {"cargo": Position(1.0, 2.0)},
                          frozenset({"vedette"}))
    assert evaluate({"type": "all_in_zone", "force": "verte", "zone": "sortie"},
                    world, scenario)
    assert evaluate({"type": "agent_destroyed", "agent": "vedette"},
                    world, scenario)
~~~

Ajouter dans tests/reference_fixtures.py, après les helpers de Task 1 :

~~~python
def snapshot(sim_time_s: float, positions: Mapping[str, tuple[float, float]],
             destroyed: set[str] | None = None) -> WorldSnapshot:
    return WorldSnapshot(
        revision=int(sim_time_s),
        sim_time_s=sim_time_s,
        positions={name: Position(lat, lon) for name, (lat, lon) in positions.items()},
        destroyed=frozenset(destroyed or set()))
~~~

- [ ] **Step 4: Corriger les appels ROS**

Dans LotusimClient :

1. Vérifier que wait_for_service(timeout_sec=timeout_s) retourne True, sinon
   lever RuntimeError avec le nom du service.
2. Après call_async, vérifier fut.done(), fut.exception() et response.success.
3. Lire le booléen Result.result de MASCmd ; spawn_vessel retourne le nom
   canonique créé et échoue si ce nom diffère du nom demandé.
4. Implémenter DELETE_CMD avec la même action MASCmd et stop_vessel via le
   service /lotusim/<agent>/stop.
5. Ne plus mettre à jour l'état de planification dans c_aller_a. Le chemin v3
   n'appelle plus cette closure ; le chemin legacy reste inchangé.

- [ ] **Step 5: Ajouter un test de contrat de transport sans ROS**

Extraire les vérifications de future dans une fonction pure et déclarer son
protocole local :

~~~python
class FutureLike(Protocol):
    def done(self) -> bool:
        pass

    def result(self) -> Any:
        pass

    def exception(self) -> BaseException | None:
        pass

def require_result(future: FutureLike, operation: str) -> Any:
    if not future.done():
        raise RuntimeError(f"{operation}: timeout")
    if future.exception() is not None:
        raise RuntimeError(f"{operation}: {future.exception()}")
    return future.result()
~~~

Tester timeout, exception et réponse SetWaypoints(success=False) avec des
futures factices. Le test ne doit importer ni rclpy ni lotusim_msgs.

- [ ] **Step 6: Vérifier**

Run:

~~~bash
uv run pytest tests/test_reference_world.py tests/test_conditions.py tests/test_runner_logs.py -q
uv run ruff check tsm/execution/world.py tsm/lotusim/client.py
uv run mypy tsm/execution/world.py
~~~

Expected: tous les tests passent. Les imports ROS ne sont pas collectés par pytest.

- [ ] **Step 7: Commit**

~~~bash
git add tsm/execution/world.py tsm/domain/conditions.py tsm/execution/runner.py tsm/lotusim/client.py tests/reference_fixtures.py tests/test_reference_world.py tests/test_conditions.py
git commit -m "feat: fonder l'exécution sur les observations et le temps simulé"
~~~

---

### Task 3: Objectifs typés et backend cinématique spécifique

**Files:**
- Create: tsm/execution/objectives.py
- Create: tsm/execution/autonomy.py
- Create: tests/test_reference_objectives.py
- Create: tests/test_reference_autonomy.py
- Modify: tests/reference_fixtures.py

**Interfaces:**

~~~python
class ObjectiveStatus(str, Enum):
    SUBMITTED = "submitted"
    ACCEPTED = "accepted"
    IN_PROGRESS = "in_progress"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"

@dataclass(frozen=True)
class Objective:
    id: str
    agent: str
    capability: str
    parameters: Mapping[str, Any]
    submitted_sim_time_s: float
    deadline_sim_time_s: float

@dataclass(frozen=True)
class ObjectiveUpdate:
    objective_id: str
    status: ObjectiveStatus
    sim_time_s: float
    reason: str | None = None

class KinematicWaypointFollower:
    capabilities = frozenset({"navigation.goto", "navigation.follow_target"})
~~~

Méthodes exactes : submit(objective, world) -> ObjectiveUpdate,
tick(world) -> list[ObjectiveUpdate] et cancel(objective_id, world) ->
ObjectiveUpdate. Importer Enum depuis enum ; StrEnum est interdit car Python
3.10 est la cible.

- [ ] **Step 1: Écrire les tests rouges du cycle de vie**

~~~python
def test_goto_is_not_succeeded_until_an_observed_pose_reaches_target():
    provider, transport = kinematic_provider()
    goal = objective("g-000001", "cargo", "navigation.goto",
                     {"target": [1.001, 2.0], "arrival_radius_deg": 0.00002})
    assert provider.submit(goal, snapshot(0, {"cargo": (1.0, 2.0)})).status == ObjectiveStatus.ACCEPTED
    assert transport.waypoints == [("cargo", 1.001, 2.0)]
    assert provider.tick(snapshot(1, {"cargo": (1.0005, 2.0)}))[-1].status == ObjectiveStatus.IN_PROGRESS
    assert provider.tick(snapshot(2, {"cargo": (1.001, 2.0)}))[-1].status == ObjectiveStatus.SUCCEEDED

def test_follow_target_updates_waypoint_inside_provider_not_supervisor():
    provider, transport = kinematic_provider()
    provider.submit(objective("g-000001", "red", "navigation.follow_target",
                              {"target_agent": "cargo", "update_threshold_deg": 0.0003}),
                    snapshot(0, {"red": (1.0, 2.0), "cargo": (1.1, 2.0)}))
    provider.tick(snapshot(1, {"red": (1.0, 2.0), "cargo": (1.101, 2.0)}))
    assert len(transport.waypoints) == 2
~~~

- [ ] **Step 2: Vérifier les échecs**

Run:

~~~bash
uv run pytest tests/test_reference_objectives.py tests/test_reference_autonomy.py -q
~~~

Expected: échec d'import.

- [ ] **Step 3: Implémenter le compteur et le provider**

~~~python
class ObjectiveFactory:
    def __init__(self) -> None:
        self._next = 1

    def create(self, agent: str, capability: str, parameters: Mapping[str, Any],
               sim_time_s: float, timeout_s: float) -> Objective:
        objective = Objective(
            id=f"g-{self._next:06d}",
            agent=agent, capability=capability, parameters=dict(parameters),
            submitted_sim_time_s=sim_time_s,
            deadline_sim_time_s=sim_time_s + timeout_s,
        )
        self._next += 1
        return objective
~~~

KinematicWaypointFollower accepte seulement les deux capacités déclarées. goto
réussit seulement quand distance_deg(position observée, target) <=
arrival_radius_deg. follow_target réémet un waypoint seulement lorsque la
cible a changé d'au moins update_threshold_deg ; il réussit seulement si
stop_distance_deg est défini et atteint. Une cible détruite, une absence de
pose ou un dépassement de deadline produit respectivement failed ou timed_out.

- [ ] **Step 4: Tester annulation, timeout et capacité inconnue**

~~~python
def test_cancel_stops_the_vessel_and_emits_a_terminal_result():
    provider, transport = kinematic_provider()
    goal = objective("g-000001", "cargo", "navigation.goto",
                     {"target": [1.1, 2.0], "arrival_radius_deg": 0.00002},
                     deadline_sim_time_s=20)
    provider.submit(goal, snapshot(0, {"cargo": (1.0, 2.0)}))
    update = provider.cancel(goal.id, snapshot(1, {"cargo": (1.0, 2.0)}))
    assert update.status is ObjectiveStatus.CANCELLED
    assert transport.stopped == ["cargo"]

def test_goal_times_out_using_simulated_time_not_wall_time():
    provider, _ = kinematic_provider()
    goal = objective("g-000001", "cargo", "navigation.goto",
                     {"target": [1.1, 2.0], "arrival_radius_deg": 0.00002},
                     deadline_sim_time_s=5)
    provider.submit(goal, snapshot(0, {"cargo": (1.0, 2.0)}))
    assert provider.tick(snapshot(5, {"cargo": (1.0, 2.0)}))[-1].status is ObjectiveStatus.TIMED_OUT

def test_provider_rejects_unknown_capability():
    provider, _ = kinematic_provider()
    update = provider.submit(objective("g-000001", "cargo", "engage.attack_target",
                                       {}, deadline_sim_time_s=5),
                             snapshot(0, {"cargo": (1.0, 2.0)}))
    assert update.status is ObjectiveStatus.FAILED
    assert update.reason == "unsupported_capability"
~~~

Le fake transport doit enregistrer stop_vessel, set_waypoints et ne contenir
aucun import ROS.

Ajouter dans tests/reference_fixtures.py :

~~~python
def objective(goal_id: str, agent: str, capability: str,
              parameters: Mapping[str, Any],
              deadline_sim_time_s: float = 60.0) -> Objective:
    return Objective(goal_id, agent, capability, dict(parameters), 0.0,
                     deadline_sim_time_s)

class FakeTransport:
    def __init__(self) -> None:
        self.waypoints: list[tuple[str, float, float]] = []
        self.stopped: list[str] = []

    def set_waypoints(self, agent: str, lat: float, lon: float) -> None:
        self.waypoints.append((agent, lat, lon))

    def stop_vessel(self, agent: str) -> None:
        self.stopped.append(agent)

def kinematic_provider() -> tuple[KinematicWaypointFollower, FakeTransport]:
    transport = FakeTransport()
    return KinematicWaypointFollower(transport), transport
~~~

- [ ] **Step 5: Vérifier**

Run:

~~~bash
uv run pytest tests/test_reference_objectives.py tests/test_reference_autonomy.py -q
uv run ruff check tsm/execution/objectives.py tsm/execution/autonomy.py
uv run mypy tsm/execution/objectives.py tsm/execution/autonomy.py
~~~

Expected: tous les tests passent.

- [ ] **Step 6: Commit**

~~~bash
git add tsm/execution/objectives.py tsm/execution/autonomy.py tests/reference_fixtures.py tests/test_reference_objectives.py tests/test_reference_autonomy.py
git commit -m "feat: exécuter les objectifs cinématiques avec un cycle de vie"
~~~

---

### Task 4: Doctrine locale et artefacts de l'Escorte d'Ormuz

**Files:**
- Create: scenarios/escorte_ormuz.json
- Create: profiles/kinematic-ormuz.json
- Create: tests/test_reference_ormuz_assets.py
- Modify: tests/reference_fixtures.py
- Modify: doctrine/knowledge_base.json
- Modify: tsm/planning/methods.py
- Modify: tsm/execution/actions.py

**Interfaces:**

Les étapes primitives produites par le planner v3 sont exactement :

~~~python
("goto", agent, (lat, lon), arrival_radius_deg)
("follow_target", agent, target_agent, stop_distance_deg | None)
("attack_target", agent, target_agent)
~~~

Les actions GTPyhop enregistrées pour ces primitives sont pures et retournent
state sans modifier les poses. Leur effet réel est uniquement traduit par le
superviseur de Task 5.

- [ ] **Step 1: Écrire les tests rouges des artefacts**

~~~python
def test_ormuz_has_three_forces_and_deferred_red_force():
    scenario = load_reference_scenario("escorte_ormuz")
    assert scenario.forces["rouge"].spawn == "deferred"
    assert set(scenario.forces) == {"bleue", "rouge", "verte"}

def test_ormuz_profile_declares_only_selected_backends():
    profile = load_profile("kinematic-ormuz")
    assert profile.agents["escorte"].fidelity == "kinematic"
    assert "navigation.follow_target" in profile.agents["vedette_1"].capabilities
    assert "engage.attack_target" in profile.agents["escorte"].capabilities
~~~

- [ ] **Step 2: Créer le Scenario Request v2**

Créer scenarios/escorte_ormuz.json avec ces données stables :

~~~json
{
  "version": 2,
  "information_policy": "omniscient",
  "forces": {
    "bleue": {"agents": ["escorte"]},
    "verte": {"agents": ["cargo_1"]},
    "rouge": {"agents": ["vedette_1", "vedette_2"], "spawn": "deferred"}
  },
  "relations": [
    {"from": "rouge", "to": ["bleue", "verte"], "attitude": "hostile"},
    {"from": "bleue", "to": ["verte"], "attitude": "protect"}
  ],
  "zones": {
    "passe_ormuz": {"center": {"lat": 1.2620, "lon": 103.7500}, "radius_deg": 0.00015},
    "sortie_ouest": {"center": {"lat": 1.2670, "lon": 103.7500}, "radius_deg": 0.00015},
    "repli_nord": {"center": {"lat": 1.2630, "lon": 103.7560}, "radius_deg": 0.00015}
  },
  "triggers": [
    {"id": "embuscade-rouge",
     "when": {"type": "in_zone", "agent": "cargo_1", "zone": "passe_ormuz"},
     "do": [{"type": "spawn_force", "force": "rouge"}]}
  ],
  "end": {
    "success": [{"type": "all_in_zone", "force": "verte", "zone": "sortie_ouest"}],
    "failure": [{"type": "agent_destroyed", "force": "verte"}],
    "timeout": "PT180S"
  }
}
~~~

Déclarer cargo_1, escorte, vedette_1 et vedette_2 dans agents avec platform,
position, mission et conditions. Les modèles wamv, limites de vitesse et
réglages de guidage ne figurent pas dans ce fichier.

- [ ] **Step 3: Créer le profil cinématique séparé**

Le fichier profiles/kinematic-ormuz.json contient les quatre agents. Chaque
agent possède fidelity = kinematic, provider = lotusim.waypoint_follower,
le bloc spawn (model, linear_velocity, angular_velocity_max, heading_deg) et
ses capacités. escorte ajoute le provider adjudicated pour
engage.attack_target avec range_deg = 0.00045 et duration = PT2S. vedette_1
et vedette_2 publient navigation.goto et navigation.follow_target. cargo_1
publie navigation.goto.

Ajouter dans tests/reference_fixtures.py :

~~~python
def ormuz_scenario(timeout: str | None = None) -> ReferenceScenario:
    scenario = load_reference_scenario("escorte_ormuz")
    if timeout is None:
        return scenario
    return replace(scenario, end=replace(scenario.end, timeout_s=parse_duration(timeout)))

def ormuz_profile() -> ExecutionProfile:
    return load_profile("kinematic-ormuz")
~~~

- [ ] **Step 4: Ajouter les méthodes HTN v3**

Ajouter à knowledge_base.json les tâches :

1. transiter_vers_zone -> goto vers la zone passée en argument ;
2. poursuivre_cargo -> follow_target cargo_1 sans stop_distance ;
3. escorter_convoi -> follow_target vedette_1 avec stop_distance 0.00045,
   puis attack_target vedette_1 ;
4. repli_apres_perte -> goto vers repli_nord si vedette_1 est détruite,
   sinon poursuivre_cargo.

Ajouter dans methods.py les feuilles qui émettent les trois tuples ci-dessus.
La méthode de repli teste agent_destroyed contre le state local. Les méthodes
legacy aller_a, suivre et interposer restent inchangées.

~~~python
def follow_target_m(state: Any, agent: str, target: str,
                    stop_distance_deg: float | None = None) -> list[tuple[Any, ...]] | bool:
    if target not in state.agents or not state.agents[target].get("available", True):
        return False
    return [("follow_target", agent, target, stop_distance_deg)]
~~~

- [ ] **Step 5: Vérifier la doctrine**

Run:

~~~bash
uv run pytest tests/test_reference_ormuz_assets.py tests/test_planner.py tests/test_methods.py -q
uv run python -c "from tsm.domain.reference import load_reference_scenario; from tsm.domain.profile import load_profile; print(load_reference_scenario('escorte_ormuz').forces.keys(), load_profile('kinematic-ormuz').name)"
~~~

Expected: les trois forces et le profil kinematic-ormuz sont affichés ; les
tests legacy restent verts.

- [ ] **Step 6: Commit**

~~~bash
git add doctrine/knowledge_base.json tsm/planning/methods.py tsm/execution/actions.py scenarios/escorte_ormuz.json profiles/kinematic-ormuz.json tests/reference_fixtures.py tests/test_reference_ormuz_assets.py
git commit -m "feat: ajouter le scénario de référence Ormuz et sa doctrine"
~~~

---

### Task 5: Supervision par agent et contrôleur séquentiel par force

**Files:**
- Create: tsm/execution/controller.py
- Create: tests/test_reference_controller.py
- Modify: tests/reference_fixtures.py
- Modify: tsm/planning/planner.py

**Interfaces:**

~~~python
@dataclass(frozen=True)
class ForceView:
    force: str
    world: WorldSnapshot

~~~

Méthodes exactes : MissionSupervisor.tick(view), MissionSupervisor.handle_update(
update), RunController.start_initial_forces(), RunController.spawn_force(force),
RunController.tick(world), RunController.stop(reason), RunController.view_for(
force, world) et RunController.supervisor(force, agent).

Ajouter dans tests/reference_fixtures.py :

~~~python
class FakeProvider:
    def __init__(self) -> None:
        self.submitted: list[Objective] = []

    def submit(self, objective: Objective, world: WorldSnapshot) -> ObjectiveUpdate:
        self.submitted.append(objective)
        return ObjectiveUpdate(objective.id, ObjectiveStatus.ACCEPTED, world.sim_time_s)

    def tick(self, world: WorldSnapshot) -> list[ObjectiveUpdate]:
        return []

class StaticPlanner:
    def __init__(self, plan: list[tuple[Any, ...]]) -> None:
        self._plan = plan

    def find_plan(self, state: Any, task: tuple[Any, ...]) -> list[tuple[Any, ...]]:
        return list(self._plan)

def scenario_forces(policy: str, forces: Mapping[str, tuple[str, ...]]) -> ReferenceScenario:
    agents = {
        agent: {
            "platform": "surface_vessel",
            "position": {"lat": 1.0, "lon": 2.0},
            "mission": {"task": "transiter_vers_zone", "args": [agent, "sortie"]},
            "conditions": {},
        }
        for members in forces.values() for agent in members
    }
    return ReferenceScenario.from_dict({
        "version": 2, "information_policy": policy,
        "forces": {name: {"agents": list(members)} for name, members in forces.items()},
        "relations": [], "zones": {"sortie": {"center": {"lat": 1.2, "lon": 2.0},
                                             "radius_deg": 0.001}},
        "agents": agents, "triggers": [],
        "end": {"success": [], "failure": [], "timeout": "PT60S"},
    })

def view(force: str, world: WorldSnapshot) -> ForceView:
    return ForceView(force, world)

class NoopWhiteCell:
    def tick(self, world: WorldSnapshot) -> None:
        return None

def profile_for_scenario(scenario: ReferenceScenario) -> ExecutionProfile:
    return ExecutionProfile.from_dict({
        "version": 1, "name": "controller-test",
        "agents": {
            agent: {
                "fidelity": "kinematic",
                "providers": {
                    "lotusim.waypoint_follower": {
                        "capabilities": ["navigation.goto", "navigation.follow_target"]},
                    "adjudicated": {"capabilities": ["engage.attack_target"]},
                },
                "spawn": {
                    "model": "wamv", "linear_velocity": [0.0, 5.0],
                    "angular_velocity_max": 0.05, "heading_deg": 0.0,
                },
            }
            for agent in scenario.agents
        },
    })

def controller_with(scenario: ReferenceScenario) -> RunController:
    return RunController(
        scenario=scenario,
        graph=compile_authored_graph(scenario),
        profile=profile_for_scenario(scenario),
        world_store=WorldStore(),
        white_cell=NoopWhiteCell(),
        transport=FakeTransport(),
        publish_event=lambda _: None)
~~~

- [ ] **Step 1: Écrire les tests rouges de l'isolation**

~~~python
def test_force_view_hides_unobserved_agents_when_policy_becomes_force_scoped():
    scenario = scenario_forces(
        policy="force_scoped",
        forces={"bleue": ("escorte",), "rouge": ("vedette",)})
    controller = controller_with(scenario)
    view = controller.view_for("bleue",
                               snapshot(1, {"escorte": (1, 2), "vedette": (3, 4)}))
    assert "vedette" not in view.world.positions

def test_omniscient_reference_view_is_explicit_and_each_supervisor_has_own_state():
    controller = controller_with(scenario_forces(
        policy="omniscient",
        forces={"bleue": ("escorte",), "verte": ("cargo_1",)}))
    controller.start_initial_forces()
    controller.tick(snapshot(1, {"escorte": (1, 2), "cargo_1": (1.1, 2)}))
    assert controller.supervisor("bleue", "escorte") is not controller.supervisor("verte", "cargo_1")
~~~

- [ ] **Step 2: Écrire le test rouge de traduction de plan**

~~~python
def test_supervisor_submits_one_goal_then_waits_for_terminal_update():
    provider = FakeProvider()
    supervisor = MissionSupervisor(
        agent="cargo_1", force="verte",
        planner=StaticPlanner([("goto", "cargo_1", (1.2, 2.0), 0.00002)]),
        providers={"navigation.goto": provider},
        objectives=ObjectiveFactory())
    supervisor.tick(view("verte", snapshot(0, {"cargo_1": (1.0, 2.0)})))
    assert [g.capability for g in provider.submitted] == ["navigation.goto"]
    supervisor.tick(view("verte", snapshot(1, {"cargo_1": (1.1, 2.0)})))
    assert len(provider.submitted) == 1
~~~

- [ ] **Step 3: Implémenter sans threads agents**

RunController est la seule boucle de supervision. Il est réveillé par une
nouvelle revision de WorldStore, traite les forces dans l'ordre lexical et
appelle les superviseurs séquentiellement. Chaque MissionSupervisor construit
un état GTPyhop neuf depuis sa ForceView, garde seulement active_objective_id,
last_terminal_update et son ObjectiveFactory. Il ne partage jamais un state
GTPyhop mutable avec un autre superviseur.

~~~python
def tick(self, world: WorldSnapshot) -> None:
    self._white_cell.tick(world)
    for force in sorted(self._active_forces):
        view = self.view_for(force, world)
        for agent in self._graph.by_force[force]:
            self._supervisors[(force, agent)].tick(view)
    for provider in self._providers:
        for update in provider.tick(world):
            self._route_update(update)
~~~

Le contrôleur ne crée les superviseurs rouge qu'après spawn_force("rouge").
Les objectifs actifs sont annulés proprement lors d'un verdict ou d'un arrêt
opérateur.

- [ ] **Step 4: Préflight de profil et de spawn**

Avant start_initial_forces :

1. vérifier validate_profile ;
2. supprimer les noms déclarés déjà observés ;
3. attendre leur disparition dans WorldStore jusqu'à 10 secondes mur ;
4. spawn les forces initiales par ordre lexical ;
5. vérifier que le nom retourné est identique et que le service waypoint
   répond pour chaque agent ;
6. seulement alors créer les superviseurs.

Un échec produit un RunStartError et aucun superviseur n'est actif.

- [ ] **Step 5: Vérifier**

Run:

~~~bash
uv run pytest tests/test_reference_controller.py tests/test_reference_objectives.py tests/test_planner.py -q
uv run ruff check tsm/execution/controller.py
uv run mypy tsm/execution/controller.py
~~~

Expected: tous les tests passent, dont le cas de préflight refusé.

- [ ] **Step 6: Commit**

~~~bash
git add tsm/execution/controller.py tsm/planning/planner.py tests/reference_fixtures.py tests/test_reference_controller.py
git commit -m "feat: isoler la supervision v3 par force et par agent"
~~~

---

### Task 6: Cellule blanche, injections, adjudication et verdict

**Files:**
- Create: tsm/execution/white_cell.py
- Create: tests/test_reference_white_cell.py
- Modify: tsm/execution/controller.py

**Interfaces:**

~~~python
class Verdict(str, Enum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"

@dataclass(frozen=True)
class WhiteCellEvent:
    kind: str
    sim_time_s: float
    fields: Mapping[str, Any]

~~~

WhiteCell est construit avec scenario, profile, world_store, spawn_force,
delete_vessel, publish_event et stop. Ses méthodes exactes sont tick(world) ->
Verdict et submit_attack(objective, world) -> ObjectiveUpdate.

- [ ] **Step 1: Écrire les tests rouges des triggers**

~~~python
def test_trigger_spawns_red_once_when_cargo_enters_chokepoint():
    spawned = []
    store = WorldStore()
    cell = WhiteCell(ormuz_scenario(), ormuz_profile(), store,
                     spawn_force=spawned.append, delete_vessel=lambda _: None,
                     publish_event=lambda _: None, stop=lambda _: None)
    cell.tick(snapshot(0, {"cargo_1": (1.2600, 103.7500)}))
    cell.tick(snapshot(1, {"cargo_1": (1.2620, 103.7500)}))
    cell.tick(snapshot(2, {"cargo_1": (1.2621, 103.7500)}))
    assert spawned == ["rouge"]

def test_end_state_uses_sim_time_and_returns_timeout_once():
    store = WorldStore()
    cell = WhiteCell(ormuz_scenario(timeout="PT10S"), ormuz_profile(), store,
                     spawn_force=lambda _: None, delete_vessel=lambda _: None,
                     publish_event=lambda _: None, stop=lambda _: None)
    assert cell.tick(snapshot(0, {})) is Verdict.PENDING
    assert cell.tick(snapshot(9.9, {})) is Verdict.PENDING
    assert cell.tick(snapshot(10.0, {})) is Verdict.TIMED_OUT
~~~

- [ ] **Step 2: Écrire les tests rouges d'adjudication**

~~~python
def test_adjudicated_attack_deletes_target_and_succeeds_after_duration():
    world = snapshot(0, {"escorte": (1.0, 2.0), "vedette_1": (1.0001, 2.0)})
    deleted = []
    store = WorldStore()
    store.update_poses(0, {"escorte": Position(1.0, 2.0),
                           "vedette_1": Position(1.0001, 2.0)})
    cell = WhiteCell(ormuz_scenario(), ormuz_profile(), store,
                     spawn_force=lambda _: None, delete_vessel=deleted.append,
                     publish_event=lambda _: None, stop=lambda _: None)
    accepted = cell.submit_attack(
        objective("g-000001", "escorte", "engage.attack_target",
                  {"target_agent": "vedette_1"}, deadline_sim_time_s=10), world)
    assert accepted.status is ObjectiveStatus.ACCEPTED
    assert cell.tick(snapshot(2.1, {"escorte": (1.0, 2.0), "vedette_1": (1.0001, 2.0)}))
    assert deleted == ["vedette_1"]
    assert "vedette_1" in store.snapshot().destroyed
~~~

- [ ] **Step 3: Implémenter les règles déterministes**

Les triggers sont identifiés par id et ne s'exécutent qu'une fois. La cellule
blanche évalue success avant failure puis timeout à chaque snapshot ; une fois
terminal, elle ne réévalue plus. L'attaque est acceptée seulement si :

1. l'agent et la cible sont actifs ;
2. leur relation est hostile ou protect déclenché ;
3. distance_deg <= range_deg déclaré par le profil ;
4. la cible n'est pas déjà détruite.

Après duration_s de temps simulé, la cellule appelle delete_vessel, marque la
cible détruite dans WorldStore, journalise adjudication et produit succeeded.
Un objectif hors de portée est failed(reason="out_of_range"), pas un succès
silencieux.

~~~python
def tick(self, world: WorldSnapshot) -> Verdict:
    if self._verdict is not Verdict.PENDING:
        return self._verdict
    self._fire_due_triggers(world)
    self._complete_due_attacks(world)
    if all(evaluate(c, world, self._scenario) for c in self._scenario.end.success):
        self._finish(Verdict.SUCCEEDED, world)
    elif any(evaluate(c, world, self._scenario) for c in self._scenario.end.failure):
        self._finish(Verdict.FAILED, world)
    elif world.sim_time_s >= self._started_sim_time_s + self._scenario.end.timeout_s:
        self._finish(Verdict.TIMED_OUT, world)
    return self._verdict
~~~

- [ ] **Step 4: Relier les événements à RunController**

RunController fournit à WhiteCell les callbacks spawn_force, delete_vessel,
publish_event et stop. Le callback spawn_force fait le préflight de la force
deferred avant de l'activer. Un échec de spawn d'injection force le verdict
FAILED avec reason="spawn_unavailable".

- [ ] **Step 5: Vérifier**

Run:

~~~bash
uv run pytest tests/test_reference_white_cell.py tests/test_reference_controller.py -q
uv run ruff check tsm/execution/white_cell.py
uv run mypy tsm/execution/white_cell.py
~~~

Expected: les branches succès, échec et timeout sont toutes couvertes.

- [ ] **Step 6: Commit**

~~~bash
git add tsm/execution/white_cell.py tsm/execution/controller.py tests/test_reference_white_cell.py
git commit -m "feat: faire arbitrer triggers, engagement et verdict par la cellule blanche"
~~~

---

### Task 7: Runtime, provenance, API et IHM de suivi

**Files:**
- Modify: main.py
- Modify: tsm/execution/runtime.py
- Modify: tsm/execution/runner.py
- Modify: tsm/web/runs.py
- Modify: tsm/web/api.py
- Modify: tsm/web/server.py
- Modify: templates/index.html
- Modify: tests/test_run_manager.py
- Modify: tests/test_web_api.py
- Create: tests/test_reference_run_provenance.py

**Interfaces:**

Entrées exactes : main(scenario_name, profile_name=None), RunManager.launch(
name, profile=None) -> int, RunManager.record_verdict(verdict, reason) et
RunManager.status() -> dict avec state, verdict, verdict_reason, run_id,
profile, started_at et returncode.

- [ ] **Step 1: Écrire les tests rouges de provenance**

~~~python
def test_v3_run_creates_a_unique_directory_with_immutable_inputs(tmp_path):
    run = create_run_directory(tmp_path, run_id="r-000001",
                               scenario_doc={"version": 2}, profile_doc={"version": 1},
                               doctrine_doc={"tasks": {}})
    assert (run / "scenario.json").read_text() == '{\n  "version": 2\n}\n'
    assert (run / "profile.json").exists()
    assert (run / "events.jsonl").exists()

def test_status_keeps_process_and_verdict_distinct(tmp_path):
    manager = RunManager(logs_dir=tmp_path)
    manager.record_verdict("succeeded", "all_in_zone")
    status = manager.status()
    assert status["verdict"] == "succeeded"
    assert status["state"] != "succeeded"
~~~

- [ ] **Step 2: Implémenter le répertoire de run**

Chaque lancement crée logs/<run_id>/ avec :

1. scenario.json, profile.json et doctrine.json, sérialisés avant le spawn ;
2. manifest.json contenant run_id, versions de schéma, profil, capacités
   résolues et version git si disponible ;
3. events.jsonl, poses.csv et waypoints.csv ;
4. report.json écrit atomiquement au verdict avec verdict, reason,
   started_sim_time_s et finished_sim_time_s.

RunLogs reçoit un Path de run, ajoute sim_time_s dans les événements et ne
réutilise jamais le répertoire précédent.

- [ ] **Step 3: Adapter le CLI et RunManager**

main.py accepte :

~~~bash
python3 main.py escorte_ormuz --profile kinematic-ormuz
~~~

RunManager lance exactement :

~~~python
[sys.executable, "main.py", name, "--profile", profile]
~~~

si profile est non nul. Api.launch lit un corps JSON facultatif
{"profile": "kinematic-ormuz"} et renvoie 400 si un scénario v2 ne reçoit pas
de profil. Les scénarios v1 conservent le lancement legacy sans profil jusqu'à
leur migration dédiée.

- [ ] **Step 4: Rendre l'IHM minimale mais honnête**

Pour un scénario v2, renderEditor affiche une fiche lecture seule : forces,
agents, profil choisi et end state. Ajouter un select profile alimenté par
GET /api/profiles et envoyer son nom à launchScenario. Dans l'onglet Exécution,
afficher séparément :

1. état processus : idle/running/finished/failed ;
2. verdict : pending/succeeded/failed/timed_out/cancelled ;
3. temps simulé courant ;
4. lien vers report.json et manifest.json seulement lorsque le run est fini.

Ajouter les icônes timeline objective_submitted, objective_accepted,
objective_succeeded, objective_failed, trigger_fired, adjudication et verdict.
Ne pas refaire l'éditeur v1 ni introduire SSE/WebSocket.

- [ ] **Step 5: Vérifier sans ROS**

Run:

~~~bash
uv run pytest tests/test_run_manager.py tests/test_web_api.py tests/test_reference_run_provenance.py -q
uv run ruff check tsm/web tsm/execution/runtime.py tsm/execution/runner.py
uv run mypy tsm/web
~~~

Expected: les tests HTTP simulés passent et ne lancent aucun import ROS.

- [ ] **Step 6: Commit**

~~~bash
git add main.py tsm/execution/runtime.py tsm/execution/runner.py tsm/web templates/index.html tests/test_run_manager.py tests/test_web_api.py tests/test_reference_run_provenance.py
git commit -m "feat: tracer les runs v3 et exposer leur verdict"
~~~

---

### Task 8: Test d'intégration de la chaîne et validation du rig

**Files:**
- Create: tests/test_reference_e2e_memory.py
- Modify: tests/reference_fixtures.py
- Modify: README.md
- Modify: docs/rig-e2e.md
- Modify: docs/lsga-architecture-v3.md

**Interfaces:**

Le fake e2e fournit la même surface que LotusimClient : spawn_vessel,
delete_vessel, set_waypoints et stop_vessel. Il fait avancer uniquement les
snapshots et le temps simulé ; il ne simule pas de navigation physique.

Ajouter dans tests/reference_fixtures.py un InMemoryRuntimeHarness qui compose
ReferenceScenario, ExecutionProfile, WorldStore, RunController et WhiteCell,
et expose start(), tick(snapshot), verdict, spawned_forces, spawned_agents,
deleted, destroy(agent) et snapshot(sim_time_s, positions). La fonction
in_memory_runtime(name, profile, remove_capability=None) retourne exactement
(harness, harness). Lorsque remove_capability est fourni, elle retire cette
capacité du profil avant de construire le contrôleur.

- [ ] **Step 1: Écrire le test mémoire de la chaîne nominale**

~~~python
def test_ormuz_full_chain_reaches_success_verdict():
    runtime, fake = in_memory_runtime("escorte_ormuz", "kinematic-ormuz")
    runtime.start()
    runtime.tick(fake.snapshot(0, {"cargo_1": (1.2600, 103.7500),
                                   "escorte": (1.2598, 103.7497)}))
    runtime.tick(fake.snapshot(10, {"cargo_1": (1.2620, 103.7500),
                                    "escorte": (1.2615, 103.7500)}))
    assert "rouge" in fake.spawned_forces
    runtime.tick(fake.snapshot(20, {"cargo_1": (1.2640, 103.7500),
                                    "escorte": (1.2630, 103.7520),
                                    "vedette_1": (1.2631, 103.7520),
                                    "vedette_2": (1.2632, 103.7530)}))
    runtime.tick(fake.snapshot(23, {"cargo_1": (1.2669, 103.7500),
                                    "escorte": (1.2630, 103.7520),
                                    "vedette_2": (1.2632, 103.7530)}))
    assert "vedette_1" in fake.deleted
    runtime.tick(fake.snapshot(30, {"cargo_1": (1.2670, 103.7500),
                                    "escorte": (1.2630, 103.7520),
                                    "vedette_2": (1.2630, 103.7560)}))
    assert runtime.verdict is Verdict.SUCCEEDED
~~~

- [ ] **Step 2: Ajouter les variantes négatives**

~~~python
def test_ormuz_fails_when_cargo_is_destroyed():
    runtime, fake = in_memory_runtime("escorte_ormuz", "kinematic-ormuz")
    runtime.start()
    fake.destroy("cargo_1")
    runtime.tick(fake.snapshot(4, {"escorte": (1.2598, 103.7497)}))
    assert runtime.verdict is Verdict.FAILED

def test_ormuz_times_out_without_progress():
    runtime, fake = in_memory_runtime("escorte_ormuz", "kinematic-ormuz")
    runtime.start()
    runtime.tick(fake.snapshot(180, {"cargo_1": (1.2600, 103.7500),
                                     "escorte": (1.2598, 103.7497)}))
    assert runtime.verdict is Verdict.TIMED_OUT

def test_incompatible_profile_fails_before_any_spawn():
    runtime, fake = in_memory_runtime(
        "escorte_ormuz", "kinematic-ormuz",
        remove_capability=("vedette_1", "navigation.follow_target"))
    with pytest.raises(RunStartError, match="navigation.follow_target"):
        runtime.start()
    assert fake.spawned_agents == []
~~~

- [ ] **Step 3: Mettre à jour la documentation**

README :

~~~bash
python3 main.py escorte_ormuz --profile kinematic-ormuz
~~~

docs/rig-e2e.md ajoute une recette Ormuz précise : démarrer le conteneur, lancer
le serveur, sélectionner Escorte Ormuz / kinematic-ormuz, observer
embuscade-rouge puis verdict succeeded, vérifier logs/<run_id>/report.json, et
teardown. docs/lsga-architecture-v3.md met à jour le tableau §10.1 : incréments
1 à 4 « implémentés pour Escorte Ormuz », avec la limite explicite N1/HDDL et
information_policy omniscient.

- [ ] **Step 4: Vérifier la qualité locale**

Run:

~~~bash
uv run pytest
uv run ruff check .
uv run mypy
git diff --check
~~~

Expected: 0 échec, 0 erreur Ruff, 0 erreur mypy et aucune erreur whitespace.

- [ ] **Step 5: Vérifier le rig ROS**

Suivre docs/rig-e2e.md, puis exécuter :

~~~bash
curl -s localhost:8080/api/run
curl -s localhost:8080/api/run/events?since=0
~~~

Expected : le statut final comporte state=finished et verdict=succeeded ; la
timeline contient trigger_fired, objective_succeeded, adjudication, verdict et
run_end. Confirmer que report.json contient le même verdict et un
finished_sim_time_s supérieur à started_sim_time_s.

- [ ] **Step 6: Commit**

~~~bash
git add tests/test_reference_e2e_memory.py README.md docs/rig-e2e.md docs/lsga-architecture-v3.md
git commit -m "docs: rendre vérifiable le scénario de référence Ormuz"
~~~

## Revue finale du plan d'exécution

Avant de commencer Task 1, relire ce plan contre LSGA v3 :

1. La cellule blanche détient la vérité terrain, les triggers, l'adjudication
   et le verdict.
2. Les forces ne reçoivent que ForceView ; omniscient est un mode de scénario,
   pas un accès global dans le code.
3. Le profil d'exécution est séparé du Scenario Request et est journalisé.
4. waypoint follower reste un backend cinématique ; follow_target est tenu par
   son provider, jamais par un replan HTN en boucle.
5. Les objectifs ont un résultat terminal, et un échec d'objectif ne conclut
   pas automatiquement au verdict du run.
6. Aucun élément du plan ne demande une navigation universelle, un moteur HDDL
   ou une modification de LOTUSim.

Si une de ces six propositions n'est pas vraie après une tâche, corriger la
tâche avant de poursuivre, plutôt que compenser par une exception locale.
