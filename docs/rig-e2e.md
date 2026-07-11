# Runbook — rig e2e LOTUSim + tsm sur le Mac

Séquence validée le 2026-07-11, **simplifiée après test empirique** : deux étapes des
recettes historiques (warmup ROS avant gz, patch `max_step_size` 0.005) étaient des
reliques des conteneurs Rosetta/amd64 et de la co-sim xdyn — inutiles sur l'image
arm64 native en mode cinématique (vérifié : gz démarre sur graphe ROS vide ; à 0.2 le
mouvement est régulier, poursuite nominale, RTF≈1).

## Topologie — qui lance quoi

```
Mac                              Conteneur tsm-e2e (image lotusim:jazzy, arm64 natif)
──────────────────────────      ─────────────────────────────────────────────
                                 ① lotusim run              gz headless ; les nœuds ROS
                                                            vivent DANS les plugins gz
                                 ② app.py :8080             serveur tsm → spawne les runtimes rclpy
                                 ③ backend rclnodejs :5000  pont ROS→WS, mappé :5050 côté Mac
④ vite :5173 (bun run dev)  ──► REST+WS :5050
navigateur ──► :5173 (carte LOTUSim) et :8080 (tsm, onglet Exécution)
```

Point conceptuel : **on ne lance jamais ROS ni gz à la main** dans l'écosystème LOTUSim.
Le launcher upstream (`LOTUSim/launch/lotusim run`) source l'environnement, règle les
chemins de plugins gz et lance `gz sim` ; ce sont les plugins (entity_manager,
WaypointFollower, RenderPlugin) qui créent les nœuds ROS — le publisher de
`/lotusim/poses` est `gz_entity_management_node`.

## Séquence

```bash
# 0. Conteneur inerte, lab monté, ports publiés.
#    5050:5000 : le backend écoute sur 5000 hardcodé, et AirPlay squatte 5000 sur macOS.
#    /lab : les checkouts du Mac, vus en live par le conteneur.
docker run -d --name tsm-e2e -p 8080:8080 -p 5050:5000 \
  -v ~/src/lotusim-lab:/lab lotusim:jazzy sleep infinity

# 1. La simulation — le launcher upstream fait tout (env gz + monde + plugins).
#    FASTDDS_BUILTIN_TRANSPORTS=UDPv4 est déjà un ENV de l'image.
docker exec -d tsm-e2e bash -lc '/lotusim_ws/src/LOTUSim/launch/lotusim run > /tmp/gz.log 2>&1'
# vérif : docker exec tsm-e2e bash -lc 'source /opt/ros/jazzy/setup.bash && ros2 topic list'
#         → /lotusim/poses et consorts

# 2. Serveur tsm. Lui-même est stdlib pur, mais il vit dans le conteneur parce que les
#    runtimes qu'il spawne au launch (main.py <scenario>) sont rclpy et doivent partager
#    le graphe ROS de gz.
docker exec -d tsm-e2e bash -lc 'source /opt/ros/jazzy/setup.bash && \
  source /lotusim_ws/install/setup.bash && cd /lab/tactical_scenario_maker && \
  python3 -u app.py 8080 > /tmp/app.log 2>&1'
# vérif : curl -s localhost:8080/api/run → {"state": "idle", ...}

# 3. Backend UI. node n'est PAS dans l'image (à réinstaller à chaque recréation de
#    conteneur — les node_modules, eux, survivent sur /lab). Lancer depuis /lab
#    (clone patché multi-clients), PAS depuis la copie de l'image.
docker exec tsm-e2e bash -c 'apt-get update -qq && apt-get install -y -qq nodejs npm'
docker exec -d tsm-e2e bash -lc 'source /opt/ros/jazzy/setup.bash && \
  source /lotusim_ws/install/setup.bash && cd /lab/LOTUSim-UI-backend && \
  npx ts-node src/main.ts > /tmp/backend.log 2>&1'
# vérif : curl -s localhost:5050/instances → ["lotusim"]

# 4. Frontend, sur le Mac — seul étage sans ROS, il ne parle que REST/WS sur :5050.
cd ~/src/lotusim-lab/LOTUSim-UI-frontend && bun run dev
```

IHM : `http://localhost:5173` (console d'opérations) · `http://localhost:8080` (tsm).

## Teardown

```bash
docker rm -f tsm-e2e && pkill -f "[b]un.*vite"
# si :5173 répond encore : un enfant `node .../vite` survit à bun — lsof -nP -iTCP:5173, kill
```

## Pièges connus

- Le serveur tsm sert `templates/index.html` à chaque requête (édition live via /lab),
  mais le **code Python** du serveur est figé au démarrage → restart d'`app.py` après un
  changement dans `tsm/web/`.
- `lotusim ui` (launcher upstream) lance le backend **de l'image** et le frontend au npm
  dans le conteneur — ne pas l'utiliser ici (on veut le backend `/lab` patché et bun côté Mac).
- La subscription poses du backend rclnodejs peut mourir silencieusement après un long
  uptime (REST vivant, WS muet) → restart du backend.
- Les navires gz survivent aux runs ; un respawn homonyme est suffixé `_0`. Purge par
  action : `ros2 action send_goal /lotusim/mas_cmd lotusim_msgs/action/MASCmd
  "{cmd: {cmd_type: 1, vessel_name: <nom>}}"`.
- Tuer par PID (`docker exec … kill <pid>`), jamais `pkill -f <motif>` — le motif matche
  le shell qui le porte, y compris à travers `docker exec` (astuce : `pkill -f "[t]s-node"`).
- Co-sim **xdyn** (physique, hors périmètre de ce runbook) : là, le petit pas de temps
  (0.005) et les précautions historiques restent de mise — voir la mémoire de session
  « lotusim gz Rosetta runtime ».
