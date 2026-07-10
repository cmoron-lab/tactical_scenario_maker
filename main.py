#!/usr/bin/env python3
# main.py — shim : l'implémentation vit dans tsm/execution/runtime.py.
import sys

if __name__ == '__main__':
    if len(sys.argv) < 2:
        from tsm.domain.scenario import list_scenarios
        sys.exit(f"usage: python3 main.py <scenario>  (disponibles : {', '.join(list_scenarios())})")
    from tsm.execution.runtime import main
    main(sys.argv[1])
