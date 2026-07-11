# Runbook — rig e2e LOTUSim + tsm sur le Mac

Séquence validée le 2026-07-11 (remontage manuel complet). Topologie :

```
Mac                              Conteneur tsm-e2e (image lotusim:jazzy, arm64 natif)
──────────────────────────      ─────────────────────────────────────────────
                                 ① daemon ROS (warmup)      sinon gz deadlock au boot
                                 ② gz sim headless          launcher upstream `lotusim run`
                                 ③ app.py :8080             serveur tsm → spawne les runtimes rclpy
                                 ④ backend rclnodejs :5000  pont ROS→WS, mappé :5050 côté Mac
⑤ vite :5173 (bun run dev)  ──► REST+WS :5050
navigateur ──► :5173 (carte LOTUSim) et :8080 (tsm, onglet Exécution)
```

Contraintes structurantes :
- **Un participant ROS doit exister avant gz** (sinon gz se bloque au démarrage).
- Le backend écoute sur **5000 hardcodé** ; AirPlay squatte 5000 sur macOS → mapping `5050:5000`.
- `FASTDDS_BUILTIN_TRANSPORTS=UDPv4` est un **ENV de l'image** — inutile de l'exporter.
- Tout ce qui n'est ni dans l'image ni sur `/lab` meurt avec le conteneur : le patch
  `max_step_size` du monde et l'installation de node sont à refaire à chaque recréation.

## Séquence

```bash
# 0. Conteneur inerte, lab monté, ports publiés
docker run -d --name tsm-e2e -p 8080:8080 -p 5050:5000 \
  -v ~/src/lotusim-lab:/lab lotusim:jazzy sleep infinity

# 1. Warmup ROS (participant DDS persistant avant gz)
docker exec tsm-e2e bash -lc 'source /opt/ros/jazzy/setup.bash && ros2 daemon start'

# 2. Pas de temps du monde : 0.2 (défaut image) → 0.005, sinon WaypointFollower haché
docker exec tsm-e2e sed -i 's|<max_step_size>0.2</max_step_size>|<max_step_size>0.005</max_step_size>|' \
  /lotusim_ws/src/LOTUSim/assets/worlds/lotusim.world

# 3. gz headless via le launcher upstream (sourcing + env gz + gz sim -s -r)
docker exec -d tsm-e2e bash -lc '/lotusim_ws/src/LOTUSim/launch/lotusim run > /tmp/gz.log 2>&1'
# vérif : ros2 topic list | grep lotusim  → /lotusim/poses et consorts

# 4. Serveur tsm (stdlib ; dans le conteneur parce que ses runtimes enfants sont rclpy)
docker exec -d tsm-e2e bash -lc 'source /opt/ros/jazzy/setup.bash && \
  source /lotusim_ws/install/setup.bash && cd /lab/tactical_scenario_maker && \
  python3 -u app.py 8080 > /tmp/app.log 2>&1'
# vérif : curl -s localhost:8080/api/run  → {"state": "idle", ...}

# 5. node n'est PAS dans l'image (les node_modules du backend survivent sur /lab)
docker exec tsm-e2e bash -c 'apt-get update -qq && apt-get install -y -qq nodejs npm'

# 6. Backend UI — depuis /lab (clone patché multi-clients), PAS la copie de l'image
docker exec -d tsm-e2e bash -lc 'source /opt/ros/jazzy/setup.bash && \
  source /lotusim_ws/install/setup.bash && cd /lab/LOTUSim-UI-backend && \
  npx ts-node src/main.ts > /tmp/backend.log 2>&1'
# vérif : curl -s localhost:5050/instances  → ["lotusim"]

# 7. Frontend, sur le Mac (seul étage sans ROS)
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
