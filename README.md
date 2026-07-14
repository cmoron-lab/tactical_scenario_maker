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

    # Tout le conteneur (gz + ce serveur + backend UI) en une commande.
    # Prérequis : image lotusim:jazzy construite depuis le checkout LOTUSim.
    docker compose up -d --build
    # vérif : curl -s localhost:8080/api/run → {"state": "idle", ...}
    #         curl -s localhost:5050/instances → ["lotusim"]

    # Frontend, sur le Mac (REST/WS :5050 uniquement, pas de ROS) :
    cd ~/src/lotusim-lab/LOTUSim-UI-frontend && bun run dev   # → :5173

Puis `http://localhost:8080` → scénario « escorte_ormuz », profil
« kinematic-ormuz », Lancer. ⚠️ Le code Python du serveur est figé au
démarrage : après un changement de checkout, relancer `app.py`
(`docker compose restart` relance tout le conteneur).

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
| scenarios/ | scénarios JSON v2 — Scenario Request (l'identité = le nom de fichier) |  |
| doctrine/ | knowledge_base.json — la doctrine HTN |  |
| docker/ | image et entrypoint du rig e2e (voir compose.yaml, docs/rig-e2e.md) |  |
| attic/ | générateur IA parqué (voir attic/README.md) |  |

## Format de scénario (v2 — Scenario Request)

Exemple canonique : `scenarios/escorte_ormuz.json` (extrait — forces, relations,
zones, agents, triggers, end state) :

```json
{
  "version": 2,
  "information_policy": "omniscient",
  "forces": {
    "bleue": {"agents": ["escorte"]},
    "rouge": {"agents": ["vedette_1", "vedette_2"], "spawn": "deferred"}
  },
  "relations": [
    {"from": "rouge", "to": ["bleue", "verte"], "attitude": "hostile"}
  ],
  "zones": {
    "passe_ormuz": {"center": {"lat": 26.552, "lon": 56.400}, "radius_deg": 0.0008}
  },
  "agents": {
    "escorte": {
      "platform": "surface_vessel",
      "position": {"lat": 26.5496, "lon": 56.400},
      "mission": {"task": "escorter_convoi", "args": ["escorte"]},
      "conditions": {}
    }
  },
  "triggers": [
    {"id": "embuscade-rouge",
     "when": {"type": "in_zone", "agent": "cargo_1", "zone": "passe_ormuz"},
     "do": [{"type": "spawn_force", "force": "rouge"}]}
  ],
  "end": {
    "success": [{"type": "all_in_zone", "force": "verte", "zone": "sortie_ouest"}],
    "failure": [{"type": "agent_destroyed", "force": "verte"}],
    "timeout": "PT240S"
  }
}
```

Les scénarios v1 historiques sont parqués dans `attic/scenarios-v1/` ; le
format v1 reste lisible par `main.py` sans profil.

## Limites connues

- Sauvegarder un scénario via l'UI perd les conditions non affichées par l'éditeur (celles que la tâche sélectionnée ne référence pas, ex. role/is_intruder) — défaut antérieur au refactor, correctif envisagé dans un incrément suivant.
- Un seul run à la fois : le launch renvoie 409 si un run est en cours (suivi temps réel — état, timeline d'événements, mini-carte, arrêt — dans l'onglet Exécution).
