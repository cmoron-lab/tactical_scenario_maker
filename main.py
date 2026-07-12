#!/usr/bin/env python3
# main.py — shim : l'implémentation vit dans tsm/execution/runtime.py.
import argparse
import sys

if __name__ == '__main__':
    if len(sys.argv) < 2:
        from tsm.domain.scenario import list_scenarios
        sys.exit(f"usage: python3 main.py <scenario> [--profile <nom>]  "
                 f"(disponibles : {', '.join(list_scenarios())})")

    parser = argparse.ArgumentParser(prog='main.py')
    parser.add_argument('scenario')
    parser.add_argument('--profile', default=None)
    args = parser.parse_args(sys.argv[1:])

    # Validation de version AVANT tout import ROS (tsm.execution.runtime importe
    # rclpy au niveau module) : peek_version ne fait qu'un json.load.
    from tsm.domain.reference import SCHEMA_VERSION as SCENARIO_V2
    from tsm.domain.scenario import ScenarioError, peek_version
    try:
        version = peek_version(args.scenario)
    except ScenarioError as e:
        sys.exit(f'erreur: {e}')
    if version == SCENARIO_V2 and args.profile is None:
        sys.exit(f"erreur: le scénario « {args.scenario} » (v2) nécessite --profile <nom>")
    if version != SCENARIO_V2 and args.profile is not None:
        sys.exit(f"erreur: le scénario « {args.scenario} » (v1) ne prend pas de --profile "
                 "(lancement legacy)")

    from tsm.execution.runtime import main
    main(args.scenario, args.profile)
