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
