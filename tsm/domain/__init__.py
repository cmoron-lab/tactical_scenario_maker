"""Domaine : schémas de scénario v1 (tsm.domain.scenario) et v2 (Scenario
Request + profil d'exécution). Les modules v1 restent accessibles via leur
sous-module ; ce paquet re-exporte la surface publique v2 pour un import
court depuis tsm.domain.
"""
from tsm.domain.profile import (
    AgentExecutionSpec,
    ExecutionProfile,
    ProfileError,
    load_profile,
    validate_profile,
)
from tsm.domain.reference import (
    EndState,
    ExecutionGraph,
    ForceSpec,
    ReferenceScenario,
    Relation,
    TacticalAgentSpec,
    Trigger,
    Zone,
    compile_authored_graph,
    load_reference_scenario,
    parse_duration,
)

__all__ = [
    "AgentExecutionSpec",
    "EndState",
    "ExecutionGraph",
    "ExecutionProfile",
    "ForceSpec",
    "ProfileError",
    "ReferenceScenario",
    "Relation",
    "TacticalAgentSpec",
    "Trigger",
    "Zone",
    "compile_authored_graph",
    "load_profile",
    "load_reference_scenario",
    "parse_duration",
    "validate_profile",
]
