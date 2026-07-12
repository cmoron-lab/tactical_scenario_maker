# Tactical Scenario Maker

Créateur et exécuteur de scénarios tactiques pour LOTUSim (POC).
Décrit des agents et leurs missions, les décompose en HTN (GTPyhop),
envoie des waypoints au WaypointFollower de LOTUSim et replanifie sur
les positions observées. Architecture cible : docs/lsga-architecture-v3.md.

## Lancer

    python3 app.py [port]          # UI locale (défaut : 8080) — sans ROS
    python3 main.py <scenario>     # runtime — dans l'environnement ROS,
                                   # instance LOTUSim déjà démarrée

En pratique on ne lance jamais `main.py` à la main : l'UI le fait au clic
(launch → suivi temps réel dans l'onglet Exécution → arrêt).

### Stack complète (avec simulation)

1. **Simulation** : `lotusim run` (launcher upstream de LOTUSim) — lance gz ;
   les nœuds ROS vivent dans les plugins gz, rien d'autre à démarrer.
2. **Ce serveur** : `python3 app.py`, dans le même environnement ROS que gz
   (les runtimes spawnés au launch sont rclpy).
3. **Optionnel, la carte LOTUSim** : backend + frontend LOTUSim-UI.

Séquence détaillée sur le rig conteneurisé (commandes exactes, vérifications,
teardown, pièges) : `docs/rig-e2e.md`.

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
