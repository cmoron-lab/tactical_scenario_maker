"""tsm — Tactical Scenario Maker, découpé par couches.

domain/     : schéma canonique des scénarios, doctrine HTN, géométrie
planning/   : encapsulation GTPyhop (Planner), méthodes HTN
execution/  : actions/commands, boucle agent, assemblage runtime
lotusim/    : adaptateur ROS vers LOTUSim (seul module qui importe rclpy)
web/        : API HTTP locale et serveur
vendor/     : GTPyhop 1.1 (Dana Nau, BSD-3-Clause-Clear) — ne pas modifier
"""
