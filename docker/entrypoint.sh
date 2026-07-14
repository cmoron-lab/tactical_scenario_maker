#!/bin/bash
# Entrée du conteneur rig e2e : rejoue la séquence du runbook (docs/rig-e2e.md).
# Chaque processus logge dans /tmp/*.log ; si l'un meurt, le conteneur reste
# debout pour le diagnostic (docker exec), comme avec l'ancien `sleep infinity`.
set -eo pipefail  # pas de -u : les setup.bash ROS lisent des variables non définies

# hormuz.world n'est pas commité dans LOTUSim et le launcher lit /lotusim_ws
# (pas /lab) : la copie à chaque démarrage supprime l'autre piège récurrent.
cp /lab/LOTUSim/assets/worlds/hormuz.world /lotusim_ws/src/LOTUSim/assets/worlds/

source /opt/ros/jazzy/setup.bash
source /lotusim_ws/install/setup.bash

# Le launcher upstream fait tout (env gz + monde + plugins) ; les nœuds ROS
# vivent dans les plugins gz. WORLD=lotusim.world pour la scène v1 (Singapour).
/lotusim_ws/src/LOTUSim/launch/lotusim run "${WORLD:-hormuz.world}" > /tmp/gz.log 2>&1 &

# Serveur tsm : stdlib pur, mais les runtimes qu'il spawne sont rclpy et
# doivent partager le graphe ROS de gz.
(cd /lab/tactical_scenario_maker && exec python3 -u app.py 8080 > /tmp/app.log 2>&1) &

# Backend UI : depuis /lab (clone patché multi-clients), node_modules sur /lab.
(cd /lab/LOTUSim-UI-backend && exec npx ts-node src/main.ts > /tmp/backend.log 2>&1) &

wait
