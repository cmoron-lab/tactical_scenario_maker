"""Supervision v3 : une ForceView et un MissionSupervisor par agent, orchestrés
séquentiellement par un unique RunController (le « qui décide »).

Décomposition en trois responsabilités :

- ForceView : la fenêtre d'observation d'une force sur le WorldSnapshot. En
  omniscient elle est le monde entier (explicitement, pas implicitement) ; en
  force_scoped elle masque tout ce qui n'appartient pas à la force.
- MissionSupervisor : boucle événementielle d'un agent. Sans objectif actif il
  construit un état GTPyhop NEUF depuis sa vue, planifie, traduit la première
  primitive en Objective et la soumet ; avec un objectif actif il ne fait RIEN
  jusqu'à recevoir un update terminal (jamais de replanification par polling).
  Il ne partage jamais un état GTPyhop mutable avec un autre superviseur.
- RunController : préflight (profil + spawn), registre de providers, création
  des superviseurs, boucle de tick unique (pas de threads agents), spawn des
  forces différées, arrêt propre. Toute dégradation de fidélité est interdite :
  un profil incompatible ou un spawn raté lève RunStartError AVANT tout
  superviseur.

Aucun import ROS ici : le transport est un Protocol structurel, satisfait aussi
bien par le client LOTUSim réel (Task 7) que par le double de test.
"""
from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Callable, Protocol

from tsm.domain import doctrine
from tsm.domain.profile import ExecutionProfile, ProfileError, validate_profile
from tsm.domain.reference import ExecutionGraph, ReferenceScenario
from tsm.execution.actions import attack_target, follow_target, goto
from tsm.execution.autonomy import AdjudicatedEngagementProvider, KinematicWaypointFollower
from tsm.execution.objectives import (
    Objective,
    ObjectiveFactory,
    ObjectiveStatus,
    ObjectiveUpdate,
)
from tsm.execution.white_cell import Verdict
from tsm.execution.world import WorldSnapshot, WorldStore
from tsm.planning.planner import Planner
from tsm.vendor import gtpyhop

Event = Mapping[str, Any]
PublishEvent = Callable[[Event], None]

_TERMINAL_STATUSES = frozenset({
    ObjectiveStatus.SUCCEEDED, ObjectiveStatus.FAILED,
    ObjectiveStatus.CANCELLED, ObjectiveStatus.TIMED_OUT,
})
# Défaut de fidélité : purge et attente de spawn sont explicitement en temps
# mur (le seul endroit du tactique où le temps simulé ne s'applique pas).
_PURGE_TIMEOUT_S = 10.0
_READINESS_TIMEOUT_S = 10.0
_DEFAULT_UPDATE_THRESHOLD_DEG = 0.0003

# Primitive de plan v3 → capacité d'objectif. goto/follow_target/attack_target
# sont les seules primitives que la doctrine v3 peut émettre (cf. methods.py).
_PRIMITIVE_CAPABILITY = {
    'goto': 'navigation.goto',
    'follow_target': 'navigation.follow_target',
    'attack_target': 'engage.attack_target',
}

# Tâches enregistrées en Python (methods.py) : leur décomposition n'est pas
# décrite dans la KB (kb['leaf_tasks'] ne nomme pas de primitives), on la fige
# donc ici — union de TOUTES les branches que la doctrine peut prendre, pour
# qu'« aucune dégradation silencieuse » ne survienne (le profil doit couvrir la
# branche de repli comme la branche de poursuite). Les tâches déclaratives de
# la KB (poursuivre_cargo…) sont dérivées par parcours, pas figées.
_PYTHON_TASK_CAPABILITIES = {
    'transiter_vers_zone': frozenset({'navigation.goto'}),
    'escorter_convoi': frozenset({'navigation.follow_target', 'engage.attack_target'}),
    'repli_apres_perte': frozenset({'navigation.goto', 'navigation.follow_target'}),
}


def required_capabilities_for_task(kb: Mapping[str, Any], task_name: str,
                                   _visited: set[str] | None = None) -> set[str]:
    """Capacités qu'une tâche de mission peut exiger, transitivement. Data-driven
    quand la KB porte déjà les faits (tâches déclaratives), table statique sinon
    (tâches Python dont la décomposition vit dans le code)."""
    if task_name in _PRIMITIVE_CAPABILITY:
        return {_PRIMITIVE_CAPABILITY[task_name]}
    if task_name in _PYTHON_TASK_CAPABILITIES:
        return set(_PYTHON_TASK_CAPABILITIES[task_name])
    if _visited is None:
        _visited = set()
    if task_name in _visited:
        return set()
    _visited.add(task_name)
    task_def = kb.get('tasks', {}).get(task_name)
    if not task_def:
        return set()
    caps: set[str] = set()
    for method in task_def.get('methods', []):
        for subtask in method.get('subtasks', []):
            caps |= required_capabilities_for_task(kb, subtask.get('task', ''), _visited)
    return caps


class RunStartError(RuntimeError):
    """Préflight refusé : profil incompatible, spawn raté ou service
    indisponible. Levée AVANT toute création de superviseur ; aucun superviseur
    n'est actif quand elle remonte."""


class _Provider(Protocol):
    def submit(self, objective: Objective, world: WorldSnapshot) -> ObjectiveUpdate: ...
    def tick(self, world: WorldSnapshot) -> list[ObjectiveUpdate]: ...
    def cancel(self, objective_id: str, world: WorldSnapshot) -> ObjectiveUpdate: ...


class _Transport(Protocol):
    def spawn_vessel(self, vessel: str, init_pos: tuple[float, float], model: str,
                     linear_velocity: Any, angular_velocity_max: float,
                     heading_deg: float) -> str: ...
    def delete_vessel(self, agent: str) -> None: ...
    def set_waypoints(self, agent: str, lat: float, lon: float) -> None: ...
    def stop_vessel(self, agent: str) -> None: ...


@dataclass(frozen=True)
class ForceView:
    force: str
    world: WorldSnapshot


def _noop_publish(event: Event) -> None:
    return None


def _state_from_view(view: ForceView) -> Any:
    """État GTPyhop NEUF depuis la vue — la forme exacte que lisent les méthodes
    v3 (state.agents[name] = {'pos': {...}, 'available': ...}). Reconstruit à
    chaque tick, jamais partagé ni muté entre superviseurs."""
    state: Any = gtpyhop.State('view')
    state.agents = {}
    for name, pos in view.world.positions.items():
        state.agents[name] = {
            'pos': {'lat': pos.lat, 'lon': pos.lon},
            'available': name not in view.world.destroyed,
        }
    return state


class MissionSupervisor:
    """Boucle événementielle d'un agent : au plus un objectif actif à la fois."""

    def __init__(self, agent: str, force: str, planner: Any,
                 providers: Mapping[str, _Provider], objectives: ObjectiveFactory,
                 mission_task: tuple[Any, ...] = (), timeout_s: float = 0.0,
                 update_threshold_deg: float = _DEFAULT_UPDATE_THRESHOLD_DEG,
                 publish_event: PublishEvent = _noop_publish) -> None:
        self._agent = agent
        self._force = force
        self._planner = planner
        self._providers = providers
        self._objectives = objectives
        self._mission_task = mission_task
        self._timeout_s = timeout_s
        self._update_threshold_deg = update_threshold_deg
        self._publish = publish_event
        self.active_objective_id: str | None = None
        self.last_terminal_update: ObjectiveUpdate | None = None
        self._active_objective: Objective | None = None

    def tick(self, view: ForceView) -> None:
        # Objectif actif : on attend son update terminal (événementiel, pas de
        # replanification par polling — le red test l'exige explicitement).
        if self.active_objective_id is not None:
            return
        world = view.world
        plan = self._planner.find_plan(_state_from_view(view), self._mission_task)
        if not plan:  # False / None / [] : idle ce tick, retentera au suivant
            return
        capability, parameters = self._translate(plan[0])
        goal = self._objectives.create(self._agent, capability, parameters,
                                       world.sim_time_s, self._timeout_s)
        self.active_objective_id = goal.id
        self._active_objective = goal
        self._publish({
            'type': 'objective_submitted', 'objective_id': goal.id,
            'agent': self._agent, 'force': self._force,
            'capability': capability, 'sim_time_s': world.sim_time_s,
        })
        provider = self._providers.get(capability)
        if provider is None:
            # Capacité sans implémentation (ex. engage.attack_target avant Task 6)
            # : FAILED routé vers soi-même, jamais de crash du run.
            self.handle_update(ObjectiveUpdate(goal.id, ObjectiveStatus.FAILED,
                                               world.sim_time_s,
                                               reason='unsupported_capability'))
            return
        self.handle_update(provider.submit(goal, world))

    def handle_update(self, update: ObjectiveUpdate) -> None:
        # Seules les TRANSITIONS sont journalisées : submitted/accepted marquent
        # le début, le statut terminal la fin. Le provider cinématique émet
        # IN_PROGRESS à chaque tick — publiées, ces lignes noieraient la
        # timeline (Task 7 n'a pas d'icône in_progress) et gonfleraient
        # events.jsonl sans porter d'information.
        if update.status is not ObjectiveStatus.IN_PROGRESS:
            self._publish({
                'type': 'objective_update', 'objective_id': update.objective_id,
                'status': update.status.value, 'reason': update.reason,
                'agent': self._agent, 'force': self._force,
                'sim_time_s': update.sim_time_s,
            })
        if update.objective_id != self.active_objective_id:
            return  # update périmé (objectif déjà conclu) : ignoré
        if update.status in _TERMINAL_STATUSES:
            self.last_terminal_update = update
            self.active_objective_id = None
            self._active_objective = None

    def cancel_active(self, world: WorldSnapshot) -> None:
        if self._active_objective is None:
            return
        provider = self._providers.get(self._active_objective.capability)
        if provider is None:  # objectif sans provider déjà conclu FAILED en tick
            return
        self.handle_update(provider.cancel(self._active_objective.id, world))

    def _translate(self, primitive: tuple[Any, ...]) -> tuple[str, dict[str, Any]]:
        kind = primitive[0]
        if kind == 'goto':
            _, _agent, (lat, lon), arrival_radius_deg = primitive
            return 'navigation.goto', {
                'target': [lat, lon], 'arrival_radius_deg': arrival_radius_deg}
        if kind == 'follow_target':
            _, _agent, target, stop_distance_deg = primitive
            params: dict[str, Any] = {
                'target_agent': target,
                'update_threshold_deg': self._update_threshold_deg,
            }
            if stop_distance_deg is not None:
                params['stop_distance_deg'] = stop_distance_deg
            return 'navigation.follow_target', params
        if kind == 'attack_target':
            _, _agent, target = primitive
            return 'engage.attack_target', {'target_agent': target}
        raise ValueError(f'primitive de plan inconnue: {kind!r}')


class RunController:
    """Unique boucle de supervision : ordre lexical des forces, superviseurs
    appelés séquentiellement, providers tickés après, updates routés au
    superviseur propriétaire. Pas de thread par agent."""

    def __init__(self, *, scenario: ReferenceScenario, graph: ExecutionGraph,
                 profile: ExecutionProfile, world_store: WorldStore,
                 white_cell: Any, transport: _Transport,
                 publish_event: PublishEvent) -> None:
        self._scenario = scenario
        self._graph = graph
        self._profile = profile
        self._world_store = world_store
        self._white_cell = white_cell
        self._transport = transport
        self._publish = publish_event
        self._kb = doctrine.load()
        # Un seul Planner (domaine immuable après construction) partagé par tous
        # les superviseurs — le state GTPyhop, lui, est neuf à chaque tick.
        self._planner = Planner(self._kb, actions=(goto, follow_target, attack_target))
        # Un ObjectiveFactory PARTAGÉ : le KinematicWaypointFollower est unique et
        # indexe ses objectifs par id ; des compteurs par superviseur
        # produiraient des g-000001 en collision. Le partage garantit l'unicité
        # globale des ids (et donc le routage sans ambiguïté).
        self._objectives = ObjectiveFactory()
        self._waypoint_follower = KinematicWaypointFollower(transport)
        self._provider_impls: dict[str, _Provider] = {
            'navigation.goto': self._waypoint_follower,
            'navigation.follow_target': self._waypoint_follower,
        }
        self._provider_instances: list[_Provider] = [self._waypoint_follower]
        # engage.attack_target est arbitré par la cellule blanche : on ne câble
        # l'adaptateur que si le white_cell sait adjuger (le NoopWhiteCell des
        # tests de contrôleur ne l'expose pas, et ne doit pas être tické ainsi).
        if hasattr(white_cell, 'submit_attack'):
            engagement = AdjudicatedEngagementProvider(white_cell)
            self._provider_impls['engage.attack_target'] = engagement
            self._provider_instances.append(engagement)
        self._supervisors: dict[tuple[str, str], MissionSupervisor] = {}
        self._active_forces: set[str] = set()
        self._stopped = False
        self._seen_destroyed: frozenset[str] = frozenset()
        self._seen_agents: frozenset[str] | None = None
        self._verdict_published = False

    # ── Vue par force ────────────────────────────────────────────────────────

    def view_for(self, force: str, world: WorldSnapshot) -> ForceView:
        if self._scenario.information_policy == 'omniscient':
            return ForceView(force, world)  # explicite : la politique est une donnée
        members = set(self._graph.by_force.get(force, {}))
        scoped = WorldSnapshot(
            revision=world.revision, sim_time_s=world.sim_time_s,
            positions=MappingProxyType(
                {n: p for n, p in world.positions.items() if n in members}),
            destroyed=frozenset(d for d in world.destroyed if d in members))
        return ForceView(force, scoped)

    def supervisor(self, force: str, agent: str) -> MissionSupervisor:
        return self._supervisors[(force, agent)]

    # ── Préflight + démarrage ────────────────────────────────────────────────

    def start_initial_forces(self) -> None:
        self._preflight_validate()
        initial = sorted(force for force, spec in self._scenario.forces.items()
                         if spec.spawn == 'initial')
        # Purge TOUS les noms déclarés (forces différées comprises) : les ids
        # sont stables entre runs, et une vedette d'un run précédent encore en
        # scène rendrait le respawn différé invisible au détecteur d'apparition
        # (constaté au rig, run r-000006).
        self._purge(sorted(self._scenario.agents))
        for force in initial:
            for agent in sorted(self._graph.by_force[force]):
                self._spawn(force, agent)
        # Seulement après TOUS les spawns : sinon un échec tardif laisserait des
        # superviseurs actifs (invariant « zéro superviseur si RunStartError »).
        for force in initial:
            self._create_supervisors(force)

    def spawn_force(self, force: str) -> None:
        """Force différée (déclenchée par la white cell en Task 6). Idempotent :
        un second appel est un no-op publié."""
        if force in self._active_forces:
            self._publish({'type': 'spawn_force_noop', 'force': force})
            return
        agents = sorted(self._graph.by_force[force])
        self._purge(agents)
        for agent in agents:
            self._spawn(force, agent)
        self._create_supervisors(force)

    def _preflight_validate(self) -> None:
        required = {agent: required_capabilities_for_task(self._kb, spec.mission.task)
                    for agent, spec in self._scenario.agents.items()}
        try:
            validate_profile(self._scenario, self._profile, required)
        except ProfileError as exc:
            self._publish({'type': 'preflight_failed', 'reason': str(exc)})
            raise RunStartError(str(exc)) from exc

    def _purge(self, agents: list[str]) -> None:
        """Supprime les noms déclarés déjà observés et attend leur disparition
        (temps mur, 10 s max). Zéro attente quand rien n'est observé — le cas
        des tests unitaires (WorldStore vierge)."""
        snap = self._world_store.snapshot()
        observed = [agent for agent in agents if agent in snap.positions]
        if not observed:
            return
        for agent in observed:
            self._transport.delete_vessel(agent)
            self._publish({'type': 'purge', 'agent': agent,
                           'sim_time_s': snap.sim_time_s})
        deadline = time.monotonic() + _PURGE_TIMEOUT_S
        while time.monotonic() < deadline:
            if not any(a in self._world_store.snapshot().positions for a in observed):
                return
            time.sleep(0.05)
        still = [a for a in observed if a in self._world_store.snapshot().positions]
        raise RunStartError(
            f'purge: agents encore observés après {_PURGE_TIMEOUT_S}s: {still}')

    def _spawn(self, force: str, agent: str) -> None:
        espec = self._profile.agents[agent]
        tspec = self._scenario.agents[agent]
        spawn = espec.spawn
        try:
            returned = self._transport.spawn_vessel(
                agent, (tspec.position.lat, tspec.position.lon),
                spawn['model'], spawn['linear_velocity'],
                spawn['angular_velocity_max'], spawn['heading_deg'])
        except Exception as exc:
            self._publish({'type': 'spawn_failed', 'agent': agent,
                           'force': force, 'reason': str(exc)})
            raise RunStartError(f'spawn de {agent!r} échoué: {exc}') from exc
        if returned != agent:
            self._publish({'type': 'spawn_failed', 'agent': agent, 'force': force,
                           'reason': f'nom canonique {returned!r} ≠ {agent!r}'})
            raise RunStartError(
                f'spawn de {agent!r}: nom canonique retourné {returned!r} ≠ demandé')
        self._publish({'type': 'spawn', 'agent': agent, 'force': force,
                       'sim_time_s': self._world_store.snapshot().sim_time_s})
        wait_ready = getattr(self._transport, 'wait_ready', None)
        if wait_ready is not None:  # câblé par le client réel en Task 7
            try:
                wait_ready(agent, _READINESS_TIMEOUT_S)
            except Exception as exc:
                self._publish({'type': 'spawn_failed', 'agent': agent,
                               'force': force, 'reason': f'service indisponible: {exc}'})
                raise RunStartError(
                    f'service waypoint indisponible pour {agent!r}: {exc}') from exc

    def _create_supervisors(self, force: str) -> None:
        for agent in sorted(self._graph.by_force[force]):
            self._supervisors[(force, agent)] = self._make_supervisor(force, agent)
        self._active_forces.add(force)

    def _make_supervisor(self, force: str, agent: str) -> MissionSupervisor:
        return MissionSupervisor(
            agent=agent, force=force, planner=self._planner,
            providers=self._providers_for(agent), objectives=self._objectives,
            mission_task=self._graph.by_force[force][agent].to_htn_task(),
            timeout_s=self._scenario.end.timeout_s,
            update_threshold_deg=self._update_threshold_for(agent),
            publish_event=self._publish)

    def _providers_for(self, agent: str) -> dict[str, _Provider]:
        """Capacités déclarées ∩ implémentations disponibles. Une capacité sans
        implémentation (engage.attack_target ici) est simplement absente : son
        objectif conclura FAILED('unsupported_capability') dans le superviseur."""
        declared = self._profile.agents[agent].capabilities
        return {cap: impl for cap, impl in self._provider_impls.items()
                if cap in declared}

    def _update_threshold_for(self, agent: str) -> float:
        for config in self._profile.agents[agent].providers.values():
            if 'navigation.follow_target' in config.get('capabilities', []):
                return float(config.get('update_threshold_deg',
                                        _DEFAULT_UPDATE_THRESHOLD_DEG))
        return _DEFAULT_UPDATE_THRESHOLD_DEG

    # ── Boucle de tick unique ────────────────────────────────────────────────

    def tick(self, world: WorldSnapshot) -> None:
        if self._stopped:
            return
        # La cellule blanche joue en PREMIER : ses complétions d'attaque sont
        # ainsi drainées par l'adaptateur d'engagement dans la boucle de
        # providers du MÊME tick. Un verdict terminal arrête le run (décision 2 ;
        # NoopWhiteCell renvoie None, traité comme PENDING).
        verdict = self._white_cell.tick(world)
        if verdict is not None and verdict is not Verdict.PENDING:
            if not self._verdict_published:
                self._verdict_published = True
                # getattr : NoopWhiteCell n'expose pas verdict_reason (décision 2).
                self._publish({'type': 'verdict', 'verdict': verdict.value,
                               'reason': getattr(self._white_cell, 'verdict_reason', None),
                               'sim_time_s': world.sim_time_s})
            self.stop(f'verdict:{verdict.value}')
            return
        # Changement de situation observé (§4.1 « changement d'état observé
        # significatif », « une injection ») : apparition d'un nouvel agent ou
        # perte adjugée ⇒ annuler les objectifs actifs AVANT le tour des
        # superviseurs — ils replanifient au même tick. Sans ça, un suivi non
        # borné ne devient jamais terminal et bloque à jamais la bascule de
        # branche doctrinale (escorte qui n'engage pas, vedette_2 qui ne se
        # replie pas — constaté au rig, runs r-000004/r-000005).
        # ponytail: détection globale, à scoper par force quand force_scoped
        # filtrera la perception (incrément 5).
        if self._seen_agents is None:
            self._seen_agents = frozenset(world.positions)
        else:
            appeared = frozenset(world.positions) - self._seen_agents
            if appeared or (world.destroyed - self._seen_destroyed):
                for supervisor in self._supervisors.values():
                    supervisor.cancel_active(world)
            # Comparaison au tick PRÉCÉDENT, pas une union cumulative : un agent
            # purgé puis respawné (ids stables) doit re-déclencher l'apparition.
            # Un faux positif sur trou de trame coûte un replan bénin.
            self._seen_agents = frozenset(world.positions)
        self._seen_destroyed = world.destroyed
        for force in sorted(self._active_forces):
            view = self.view_for(force, world)
            for agent in self._graph.by_force[force]:
                self._supervisors[(force, agent)].tick(view)
        for provider in self._provider_instances:
            for update in provider.tick(world):
                self._route_update(update)

    def _route_update(self, update: ObjectiveUpdate) -> None:
        # ids globalement uniques (factory partagée) : au plus un superviseur
        # possède l'objectif. Aucun propriétaire = update terminal déjà routé.
        for supervisor in self._supervisors.values():
            if supervisor.active_objective_id == update.objective_id:
                supervisor.handle_update(update)
                return

    def stop(self, reason: str) -> None:
        if self._stopped:
            return
        self._stopped = True
        world = self._world_store.snapshot()
        for supervisor in self._supervisors.values():
            supervisor.cancel_active(world)
        self._publish({'type': 'run_stop', 'reason': reason,
                       'sim_time_s': world.sim_time_s})
