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

Les étapes conteneur sont encodées dans `compose.yaml` + `docker/`
(image dérivée de lotusim:jazzy avec node préinstallé ; l'entrypoint
copie hormuz.world vers /lotusim_ws puis lance gz, app.py et le backend —
mêmes logs /tmp/*.log qu'avant).

```bash
# 1. Tout le conteneur (ports 8080 et 5050:5000, /lab monté en live).
#    FASTDDS_BUILTIN_TRANSPORTS=UDPv4 est déjà un ENV de l'image.
#    WORLD=lotusim.world pour la scène v1 (Singapour) ; défaut : hormuz.world
#    (vrai détroit, scénarios de référence). Changer de monde = recréer.
docker compose up -d --build
# vérifs : docker ps → tsm-e2e (healthy)  [healthcheck = curl :8080/api/run]
#          curl -s localhost:8080/api/run → {"state": "idle", ...}
#          curl -s localhost:5050/instances → ["lotusim"]
#          docker exec tsm-e2e bash -lc 'source /opt/ros/jazzy/setup.bash && ros2 topic list'
#          → /lotusim/poses et consorts

# 2. Frontend, sur le Mac — seul étage sans ROS, il ne parle que REST/WS sur :5050.
cd ~/src/lotusim-lab/LOTUSim-UI-frontend && bun run dev
```

Pourquoi un seul service : gz, le serveur tsm et le backend partagent le
graphe ROS/DDS — les séparer en conteneurs casserait FastDDS sur Docker
macOS. Compose n'orchestre que le cycle de vie du conteneur ; si un
processus meurt, le conteneur reste debout pour le diagnostic
(`docker exec tsm-e2e tail /tmp/gz.log` etc.).

IHM : `http://localhost:5173` (console d'opérations) · `http://localhost:8080` (tsm).

## Recette — scénario de référence Escorte Ormuz (v3)

Une fois la stack montée (§Séquence, étapes 0–4), ce scénario prouve la chaîne
v3 complète sur le rig : cellule blanche, injection de force, adjudication,
verdict. La même chaîne est vérifiée sans ROS par
`tests/test_reference_e2e_memory.py` (`uv run pytest`) — le rig ne fait que la
rejouer avec la navigation physique de gz.

```bash
# 1. Lancer le run v3 : scénario escorte_ormuz + profil d'exécution kinematic-ormuz.
#    Depuis l'IHM tsm (:8080, onglet Exécution) : sélectionner « Escorte Ormuz »,
#    profil « kinematic-ormuz », puis Lancer. Équivalent API :
curl -s -X POST localhost:8080/api/scenario/escorte_ormuz/launch \
  -H 'Content-Type: application/json' -d '{"profile": "kinematic-ormuz"}'

# 2. Observer le déroulé (IHM onglet Exécution, ou timeline d'événements) :
#    - cargo_1 transite vers sortie_ouest ; escorte tient le poste ;
#    - cargo_1 entre dans passe_ormuz → trigger `embuscade-rouge` → spawn de la
#      force rouge (vedette_1, vedette_2) ;
#    - escorte engage vedette_1 → la cellule blanche adjuge (PT2S) → vedette_1
#      détruite et supprimée ;
#    - cargo_1 atteint sortie_ouest → verdict `succeeded`.

# 3. Vérifier l'état final et la timeline.
curl -s localhost:8080/api/run                 # state=finished, verdict=succeeded
curl -s localhost:8080/api/run/events?since=0  # trigger_fired, objective_succeeded,
                                               # adjudication, verdict, run_end
```

Provenance : chaque run écrit `logs/<run_id>/` (inputs figés + `events.jsonl`).
Contrôle final — `report.json` porte le même verdict et un temps simulé de fin
strictement supérieur au temps de début :

```bash
RUN=$(docker exec tsm-e2e bash -lc 'ls -1 /lab/tactical_scenario_maker/logs | tail -1')
docker exec tsm-e2e bash -lc "cat /lab/tactical_scenario_maker/logs/$RUN/report.json"
# {"verdict": "succeeded", "reason": null,
#  "started_sim_time_s": <t0>, "finished_sim_time_s": <t1 > t0>}
```

## Teardown

```bash
docker compose down && pkill -f "[b]un.*vite"
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
