# Tactical Scenario Maker

Créateur et exécuteur de scénarios tactiques pour LOTUSim (POC).
Décrit des agents et leurs missions, les décompose en HTN (GTPyhop),
envoie des waypoints au WaypointFollower de LOTUSim et replanifie sur
les positions observées. Architecture cible : docs/lsga-architecture-v3.md.

## Lancer

    python3 app.py [port]          # UI locale (défaut : 8080) — sans ROS
    python3 main.py <scenario>     # runtime v1 (legacy) — dans l'environnement
                                   # ROS, instance LOTUSim déjà démarrée
    python3 main.py escorte_ormuz --profile kinematic-ormuz
                                   # runtime v3 : scénario de référence + profil
                                   # d'exécution — cellule blanche et verdict

En pratique on ne lance jamais `main.py` à la main : l'UI le fait au clic
(launch → suivi temps réel dans l'onglet Exécution → arrêt).

### Stack complète (avec simulation, conteneur Docker)

    # 0. Conteneur (une fois) : /lab monte les checkouts en live,
    #    5050:5000 car AirPlay squatte le port 5000 sur macOS.
    docker run -d --name tsm-e2e -p 8080:8080 -p 5050:5000 \
      -v ~/src/lotusim-lab:/lab lotusim:jazzy sleep infinity

    # 1. Simulation : le launcher upstream lance gz, les nœuds ROS
    #    vivent dans les plugins gz — rien d'autre à démarrer.
    #    hormuz.world ancre la scène dans le vrai détroit (scénario de
    #    référence) ; sans argument : lotusim.world (Singapour, scénarios v1).
    docker exec -d tsm-e2e bash -lc \
      '/lotusim_ws/src/LOTUSim/launch/lotusim run hormuz.world > /tmp/gz.log 2>&1'

    # 2. Ce serveur, dans le conteneur (les runtimes spawnés sont rclpy).
    docker exec -d tsm-e2e bash -lc 'source /opt/ros/jazzy/setup.bash && \
      source /lotusim_ws/install/setup.bash && cd /lab/tactical_scenario_maker && \
      python3 -u app.py 8080 > /tmp/app.log 2>&1'
    # vérif : curl -s localhost:8080/api/run → {"state": "idle", ...}

Puis `http://localhost:8080` → scénario « escorte_ormuz », profil
« kinematic-ormuz », Lancer. ⚠️ Le code Python du serveur est figé au
démarrage : après un changement de checkout, relancer `app.py`.

    # 3. Optionnel — carte LOTUSim (:5173). Backend dans le conteneur
    #    (node à réinstaller à chaque recréation ; lancer depuis /lab,
    #    clone patché multi-clients, pas la copie de l'image) :
    docker exec tsm-e2e bash -c 'apt-get update -qq && apt-get install -y -qq nodejs npm'
    docker exec -d tsm-e2e bash -lc 'source /opt/ros/jazzy/setup.bash && \
      source /lotusim_ws/install/setup.bash && cd /lab/LOTUSim-UI-backend && \
      npx ts-node src/main.ts > /tmp/backend.log 2>&1'
    # vérif : curl -s localhost:5050/instances → ["lotusim"]

    # 4. Frontend, sur le Mac (REST/WS :5050 uniquement, pas de ROS) :
    cd ~/src/lotusim-lab/LOTUSim-UI-frontend && bun run dev   # → :5173

Suivre un run sur la carte LOTUSim : `http://localhost:5173` (ou le lien
« Ouvrir l'IHM LOTUSim » de l'onglet Exécution) — flotte en direct,
vitesses, traînées ; l'embuscade et la disparition de vedette_1 s'y
observent en temps réel. L'onglet Exécution de tsm (:8080) reste la vue
« cellule blanche » : timeline d'événements, verdict, provenance.

Séquence détaillée, vérifications, teardown et pièges : `docs/rig-e2e.md`.

## Développement

    uv run pytest                  # tests (sans ROS)
    uv run ruff check . && uv run mypy

## Structure

| Répertoire | Rôle | Composant logique (lsga-architecture-v3.md) |
|---|---|---|
| tsm/domain/ | schéma de scénario v1, doctrine HTN, géométrie | Domaine doctrinal (niveau 1) |
| tsm/planning/ | Planner (GTPyhop confiné), méthodes HTN | Planning Engine Wrapper |
| tsm/execution/ | actions/commands, boucle agent, assemblage | Exécutif de mission / supervision (niveau 2) |
| tsm/lotusim/ | adaptateur ROS (seule frontière de transport ROS ; runtime.py importe aussi rclpy pour init/shutdown) | Frontière LOTUSim / future autonomie (niveau 3) |
| tsm/web/ | API HTTP locale | Éditeur tactique (provisoire) |
| scenarios/ | scénarios JSON v1 (l'identité = le nom de fichier) |  |
| doctrine/ | knowledge_base.json — la doctrine HTN |  |
| attic/ | générateur IA parqué (voir attic/README.md) |  |

## Format de scénario (v1)

```json
{
  "version": 1,
  "agents": {
    "veilleur": {
      "position": {"lat": 1.260, "lon": 103.750},
      "heading_deg": 0.0,
      "model": "wamv",
      "velocity": {"linear": [0.0, 5.0], "angular_max": 0.05},
      "conditions": {"role": "patrol", "base_location": "1.260 103.750"},
      "mission": {"task": "veiller", "args": ["veilleur"]}
    }
  }
}
```

## Limites connues

- Sauvegarder un scénario via l'UI perd les conditions non affichées par l'éditeur (celles que la tâche sélectionnée ne référence pas, ex. role/is_intruder) — défaut antérieur au refactor, correctif envisagé dans un incrément suivant.
- Un seul run à la fois : le launch renvoie 409 si un run est en cours (suivi temps réel — état, timeline d'événements, mini-carte, arrêt — dans l'onglet Exécution).
