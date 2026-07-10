# Refonte des IHM — LOTUSim-UI-frontend + tsm/web

Date : 2026-07-10. Décisions prises en autonomie (mandat Cyril : « refonte, effet wow,
professionnalisation, on comprend ce qu'il se passe quand les deux systèmes interagissent »).

## Vision

Deux IHM, deux rôles, une même famille visuelle :

- **tsm/web** (création + pilotage) : thème clair navy existant, conservé. Gagne un
  **suivi d'exécution temps réel** : état du run, timeline d'événements HTN, mini-carte
  live, bouton launch grisé pendant un run, bouton Stop.
- **LOTUSim-UI-frontend** (supervision live) : refonte en **console d'opérations sombre**
  (slate/navy), robuste : reconnexion WS automatique + état de connexion visible,
  erreurs REST remontées en toasts, panneau flotte live, traînées de trajectoire.

Vocabulaire d'état commun (mêmes couleurs dans les deux IHM) :
`running` #22C55E · `finished` #3B82F6 · `failed` #EF4444 · `idle` #64748B ·
`reconnecting/warning` #F59E0B.

## Architecture tsm — feedback d'exécution

Topologie inchangée : le serveur web (stdlib, ROS-free) spawne `main.py <scenario>`
(runtime rclpy) en sous-processus. Le canal de feedback est **le système de fichiers**
(même pattern flush-par-ligne que poses.csv — zéro dépendance, zéro import ROS côté web) :

1. **`RunLogs.log_event(kind, **fields)`** → `logs/events.jsonl` (une ligne JSON par
   événement, flush). Émetteurs : `runtime.py` (run_start, spawn, spawn_error, run_end)
   et `runner.run_agent` (plan — seulement quand le plan d'un agent change).
2. **`RunManager`** (`tsm/web/runs.py`) : détient le `Popen` du run courant (le PID
   n'est plus jeté). `launch()` refuse (409) si un run est vivant. `stop()` = SIGINT
   (→ KeyboardInterrupt → finally propre du runtime, rc 0) puis SIGKILL après 8 s.
   Lit `events.jsonl` / `poses.csv` / `waypoints.csv` en incrémental (offsets remis à
   zéro au launch — RunLogs tronque à l'ouverture).
3. **Routes** : `GET /api/run` (état), `GET /api/run/events?since=N` (incrémental),
   `GET /api/run/poses` (dernière pose + traîne + dernier waypoint par agent),
   `POST /api/run/stop`. Le launch passe par RunManager.
4. **UI** : polling `fetch` 1 Hz (pas de SSE/WS — serveur mono-threadé, la simplicité
   gagne). Pastille d'état globale dans le header, onglet « Exécution » (timeline
   d'événements + mini-carte Leaflet CDN), launch grisé si run actif.

États du run : `idle` / `running` / `finished` (rc = 0, y compris arrêt opérateur —
le runtime sort proprement sur SIGINT) / `failed` (rc ≠ 0). Un run ne se termine
jamais seul (surveillance continue par design) : `stop_requested` est exposé pour
afficher « Arrêt en cours… ».

## Architecture LOTUSim-UI-frontend

Stack conservée (React 18 + Vite + MUI v6 + react-leaflet + axios), contrat
REST/WS backend inchangé. Changements structurels :

1. **Assainissement** : les 47 erreurs `tsc --noEmit` tombent à 0 ; suppression des
   pages mortes `/scenarios` et `/instances` (inaccessibles, formulaires hardcodés,
   imports cassés) et des deps fantômes (`express`, `cors`, `three`, markercluster×2) ;
   `react-leaflet` + `@types/leaflet` déclarés explicitement.
2. **`src/theme.ts`** : thème MUI sombre complet (tokens ci-dessous) — plus aucune
   couleur en dur dans les composants.
3. **`useVesselFeed`** (remplace la classe `WebSocketClient`) : reconnexion backoff
   exponentiel 1→15 s, expose `{vessels, status, lastUpdate}`,
   `status ∈ connecting|online|reconnecting|offline` affiché en pastille header.
4. **Erreurs visibles** : `apis.tsx` propage les erreurs (fini les `catch → false`),
   `ToastProvider` (MUI Snackbar) les affiche.
5. **Home = plein écran carte** : header fin (marque, nav, chip instance, pastille
   connexion, réglages) ; panneau « Flotte » flottant (liste live : cap, vitesse
   calculée, position, âge de la donnée, clic → flyTo) ; réglages ip/port/instance en
   dialog (validés) au lieu de la sidebar à champs bruts ; suppression des boutons
   no-op (Launch/Clear/Environment not implemented).
6. **Carte** : fond sombre CARTO par défaut (+ OSM, satellite), markers à clé stable
   (plus de popup qui se ferme à chaque tick), traînées par navire (60 derniers points,
   couleur dérivée du nom).
7. **Modèles / AddVessel** : conservés fonctionnellement, re-skinnés par le thème,
   types corrigés. Pas de refonte des formulaires physiciens (hors périmètre wow).

### Tokens (les deux IHM)

| Token | LOTUSim UI (sombre) | tsm (clair, existant) |
|---|---|---|
| fond | #0F172A | blanc cassé existant |
| surface/panneau | #1E293B (+ blur panneaux flottants) | cards existantes |
| bordure | #334155 | existante |
| texte | #E2E8F0 / #94A3B8 secondaire | existant |
| accent | #38BDF8 | navy #0B1F3A existant |
| statuts | communs (cf. ci-dessus) | communs |
| mono (coordonnées) | ui-monospace | ui-monospace |

## Ce qu'on ne fait pas (assumé)

- Pas de SSE/WebSocket côté tsm (polling 1 Hz suffit, serveur mono-threadé).
- Pas de refonte des formulaires xdyn/gz (valeur faible vs coût, UX physicien).
- Pas de fix du segfault backend `removeAllVessel` (bug upstream déjà documenté).
- Le backend LOTUSim-UI-backend n'est pas touché.
- Leaflet via CDN dans tsm (dépendance navigateur, pas serveur — la contrainte
  stdlib-only porte sur le serveur).

## Vérification

Tests unitaires sans ROS (RunManager avec sous-processus factice, events, offsets),
`tsc --noEmit` + eslint verts côté frontend, `bun test` sur les utilitaires purs
(tracks/vitesse), e2e final sur le rig conteneurisé : run lancé depuis l'IHM tsm,
timeline + mini-carte vivantes, launch grisé, stop propre, carte LOTUSim sombre avec
traînées — captures Playwright avant/après.
