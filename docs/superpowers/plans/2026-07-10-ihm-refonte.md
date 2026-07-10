# Refonte IHM — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development.
> Note d'adaptation : exécution autonome à budget contraint — les tâches UI donnent des
> specs prescriptives + critères d'acceptation plutôt que du JSX complet ; le code
> critique (RunManager, useVesselFeed, events) est fourni. L'orchestrateur review
> chaque diff + captures d'écran.

**Goal :** feedback d'exécution temps réel dans tsm/web + refonte console d'opérations
sombre de LOTUSim-UI-frontend (spec : `docs/superpowers/specs/2026-07-10-ihm-refonte-design.md`).

**Tech stack :** tsm = Python stdlib only (serveur) + HTML/CSS/JS inline + Leaflet CDN ;
frontend = React 18, Vite, MUI v6, react-leaflet, axios, bun.

## Global Constraints

- tsm : serveur web stdlib-only, aucun import rclpy hors `tsm/lotusim/client.py` +
  `tsm/execution/runtime.py`, tests exécutables sans ROS, ruff + mypy verts.
- Frontend : bun (jamais npm/yarn), `tsc --noEmit` = 0 erreur, eslint vert,
  contrat REST/WS backend inchangé.
- Git linéaire ; tsm sur branche `refonte-ihm` (ff-merge en fin) ; frontend sur `lab-patches`.
- Tokens couleurs : voir design doc (§ Tokens). Statuts communs aux deux IHM.
- Textes UI en français (cohérent avec l'existant tsm) ; frontend LOTUSim reste en anglais (existant).

---

## Piste B — tsm/web

### Task B1 : événements de run (`events.jsonl`)

**Files :** Modify `tsm/execution/runner.py`, `tsm/execution/runtime.py`,
Test `tests/test_runner_logs.py`.

**Produces :** `RunLogs.log_event(kind: str, **fields: Any) -> None` — écrit une ligne
JSON `{"t": "<iso UTC ms>", "kind": kind, **fields}` dans `logs/events.jsonl`
(ouvert 'w' au constructeur, flush par ligne, fermé dans `close()`, protégé par le
même pattern lock que `log_waypoint` — appelé depuis les threads agents).

Émissions :
- `runtime.main` : `run_start` (scenario, agents=list), `spawn` (agent) après chaque
  spawn OK, `spawn_error` (agent, error=str) dans le except, `run_end` dans le finally
  (avant `logs.close()`), `plan_preview` (agent, plan=str) pour la préview initiale.
- `runner.run_agent` : nouveau param `logs` (après `client`) ; émet `plan`
  (agent, plan=[str(a) for a in plan]) **uniquement quand la repr du plan change**
  (variable locale `last_plan`), y compris le passage à plan vide/False
  (plan=[] et un champ note='inactif'). `runtime` passe `logs` au thread.

Steps : test d'abord (log_event écrit du JSON valide flushé lisible avant close ;
deux events → deux lignes ; thread-safe smoke), run pytest rouge, implémenter,
pytest vert, ruff+mypy, commit `feat(execution): journal d'événements de run (events.jsonl)`.

### Task B2 : RunManager + routes run

**Files :** Create `tsm/web/runs.py`, Modify `tsm/web/api.py`, `tsm/web/server.py`,
Test `tests/test_run_manager.py` (+ routes dans `tests/test_web_api.py`).

**Interfaces produced :**
```python
class RunBusyError(Exception): ...

class RunManager:
    def __init__(self, cmd: Callable[[str], list[str]] | None = None,
                 logs_dir: str | Path = 'logs') -> None: ...
    def launch(self, name: str) -> int: ...      # pid ; RunBusyError si run vivant
    def stop(self) -> bool: ...                   # SIGINT ; False si rien à arrêter
    def status(self) -> dict[str, Any]: ...
    def events_since(self, since: int) -> dict[str, Any]: ...
    def poses(self) -> dict[str, Any]: ...
```
- `cmd` défaut : `lambda name: [sys.executable, 'main.py', name]`, cwd=REPO_ROOT,
  stdout+stderr → `logs/run.log` (fichier ouvert au launch, fermé au launch suivant).
- `status()` → `{'state': 'idle'|'running'|'finished'|'failed', 'scenario': str|None,
  'pid': int|None, 'started_at': iso|None, 'returncode': int|None,
  'stop_requested': bool}`. state dérivé de `proc.poll()` (rc 0 → finished, ≠0 → failed).
- `stop()` : SIGINT + `threading.Timer(8.0, kill)` (kill seulement si encore vivant).
- `events_since(n)` : lit `logs/events.jsonl` complet (petit fichier), parse les lignes
  valides, retourne `{'events': lines[n:], 'next': total}`. Lignes JSON invalides
  (écriture en cours) ignorées silencieusement SEULEMENT si dernière ligne.
- `poses()` : lecture **incrémentale** de poses.csv/waypoints.csv (offset conservé,
  remis à 0 au launch et si la taille du fichier < offset — troncature détectée).
  Retourne `{'agents': {name: {'lat','lon','t','trail': [[lat,lon]...max 120],
  'waypoint': [lat,lon]|None}}}`.
- Serveur mono-threadé (`HTTPServer`) : pas de verrou requis côté requêtes ; le Timer
  de kill ne touche que `proc.kill()` (sûr).

Routes (server.py `_route` + `_dispatch`) : `GET /api/run` → status ;
`GET /api/run/events?since=N` (query parsée via `parse_qs`) ; `GET /api/run/poses` ;
`POST /api/run/stop` → `{'ok': bool}`. `POST /api/scenario/{name}/launch` passe par
`RunManager.launch` → 409 `{'error': 'run déjà en cours', 'scenario': ...}` sur
RunBusyError. `Api.__init__` crée son RunManager (injectable pour les tests).

Tests (sans ROS, sous-processus factice `sys.executable -c 'import time; time.sleep(30)'`) :
launch → running ; double launch → RunBusyError/409 ; stop → finished (le factice
gère SIGINT par défaut → rc -2 : utiliser un factice qui catch KeyboardInterrupt et
exit 0 pour le cas finished, et un `exit(3)` pour failed) ; events_since incrémental ;
poses() incrémental + reset sur troncature ; état idle initial.

Commit `feat(web): RunManager — cycle de vie, stop, events et poses du run`.

### Task B3 : IHM tsm — pastille run, onglet Exécution, mini-carte

**Files :** Modify `templates/index.html` (seul fichier).

**Consumes :** routes B2. Spec prescriptive :

1. **Pastille d'état globale** dans le header (à droite des tabs) : point coloré +
   libellé (`Aucun run` / `Run : <scenario>` + durée écoulée mm:ss / `Terminé` /
   `Échec` / `Arrêt en cours…`). Couleurs = tokens statuts du design doc (CSS custom
   properties à ajouter à `:root`). Clic → bascule sur l'onglet Exécution.
2. **Onglet « Exécution »** (3e tab, même mécanique `switchTab`) — layout 2 colonnes
   (grid, responsive) :
   - Gauche : carte « Contrôle » (scénario courant, état, PID, démarré à, durée,
     bouton **Arrêter** rouge — confirm() natif — visible si running) + **timeline
     d'événements** scrollable auto-suiveuse (une entrée par event : icône par kind
     — ▶ run_start, ⚓ spawn, ⚠ spawn_error/failed, ⇄ plan, ■ run_end —, chip agent
     coloré (couleur stable dérivée du nom, même hash que la mini-carte), texte
     lisible : « drone1 · nouveau plan : aller_a → … », horodatage relatif).
   - Droite : **mini-carte Leaflet** (CDN unpkg leaflet@1.9, fond OSM maxNativeZoom 19)
     : marker circulaire par agent (couleur stable), traînée polyline (trail du
     /api/run/poses), croix/marker discret sur le dernier waypoint par agent,
     fitBounds automatique tant que l'utilisateur n'a pas zoomé/pané manuellement
     (flag désactivé au premier interact, bouton ⌖ pour re-suivre).
   - Lien discret « Ouvrir l'IHM LOTUSim ↗ » (URL localStorage `lotusim_ui_url`,
     défaut `http://localhost:5173`).
3. **Polling** : une seule boucle `setInterval` 1000 ms qui appelle `/api/run` toujours,
   et `/api/run/events?since` + `/api/run/poses` seulement si state=running ou si
   l'onglet Exécution est actif. `since` cursor en variable JS. Gestion réseau : un
   échec de fetch n'arrête pas la boucle (pastille passe en « ? » grise).
4. **Launch grisé** : le bouton launch existant (`launchScenario()`) est `disabled`
   avec tooltip natif (title) quand state=running ; après un launch réussi, bascule
   automatique sur l'onglet Exécution. Réponse 409 → message d'erreur dans
   `#launch-status` (classe .error existante).
5. Cohérence visuelle avec l'existant (custom properties, cards, boutons .btn-*).
   Pas de framework, pas de build step. Leaflet = seul ajout CDN.

Vérif : serveur lancé (`uv run python app.py 8090`), scénario factice, curls sur les
routes, contrôle visuel par capture Playwright (l'orchestrateur la fait). Commit
`feat(web): suivi d'exécution — pastille, timeline, mini-carte, stop`.

---

## Piste A — LOTUSim-UI-frontend (branche `lab-patches`)

### Task A1 : assainissement (types verts, deps, code mort)

**Files :** Modify `package.json`, `src/**` (fixes ciblés) ; Delete
`src/components/scenarios/`, `src/components/instances/` + routes dans `App.tsx`.

- Deps : retirer `express`, `cors`, `three`, `react-leaflet-markercluster`,
  `leaflet.markercluster` ; ajouter explicitement `react-leaflet@^4.2.1`, `leaflet`,
  dev `@types/leaflet`. `bun install` (lockfile committé).
- Corriger TOUTES les erreurs `tsc --noEmit` (47) : imports cassés (`mapMarker.tsx`
  VesselData depuis interfaces), `vessel.additionalInfo` fantôme, props non typées
  (gzBase, gzSensors), `React.FC` sans generic, unused (TS6133 — supprimer le code
  mort signalé : classes CSS light/dark jamais appliquées, bloc marker commenté de
  map.tsx, `goToInstances`/`goToScenarios`), props react-leaflet v4 (typer via les
  APIs v4 réelles : `center`/`zoom` sur MapContainer sont valides en v4 — vérifier
  avec les types installés ; si l'erreur venait de l'absence de @types/leaflet, elle
  tombe d'elle-même). Ne PAS toucher au comportement.
- Scripts : `"type-check": "tsc --noEmit"` si absent.
- Preuve : `bun run type-check` → 0 erreur ; `bun run lint` → 0 erreur (warnings
  tolérés) ; `bun run build` OK ; `bun run dev` démarre.

Commit `chore: assainissement — types verts, deps réelles, pages mortes supprimées`.

### Task A2 : thème sombre + shell (header, toasts, réglages)

**Files :** Create `src/theme.ts`, `src/components/common/toast.tsx`,
`src/components/common/SettingsDialog.tsx` ; Modify `App.tsx`, `App.css`,
`src/components/common/header.tsx`, `src/components/home/home_dashboard.tsx`,
`src/components/home/sidebar.tsx` (suppression).

- `theme.ts` : `createTheme` mode dark — palette du design doc (§ Tokens), typo
  system-ui/Inter, `shape.borderRadius: 10`, overrides Paper (fond #1E293B,
  border 1px #334155), Button (textTransform none, fontWeight 600), Dialog, Tooltip.
  Exporter `STATUS_COLORS = {running:'#22C55E', finished:'#3B82F6', failed:'#EF4444',
  idle:'#64748B', warning:'#F59E0B'}` et `vesselColor(name: string): string`
  (hash djb2 → palette 8 teintes vives lisibles sur fond sombre).
- `toast.tsx` : `ToastProvider` + `useToast(): {success(msg), error(msg), info(msg)}`
  — MUI Snackbar+Alert, file d'attente simple (un à la fois suffit).
- Header refondu : barre fine (56px) fond #0F172A border-bottom #334155 — gauche :
  marque « LOTUSim » + tag « Operations Console » ; nav (Map, Models) en boutons
  discrets avec état actif ; droite : chip instance (icône dns), pastille connexion
  (props `status` — dot pulsant si online, ambre si reconnecting, rouge offline,
  libellés Online/Reconnecting…/Offline), IconButton réglages (ouvre SettingsDialog).
- `SettingsDialog` : champs Server IP (non vide), Port (1-65535, number), Instance
  (Select alimenté par `listInstances()` + saisie libre), bouton Save → localStorage
  + callback `onSaved` (le feed reconnecte). Validation inline (helperText).
- `home_dashboard` : supprime SideBar (fichier supprimé), la carte prend tout
  (100vh - header). Les états ip/port/instance vivent ici (source localStorage),
  passés au header/dialog. Le câblage WS reste l'existant dans cette tâche
  (remplacé en A3) — adapter minimalement pour compiler.
- `App.css` : réduit aux resets utiles.
- Preuve : type-check + lint + build verts, `bun run dev` : rendu sombre cohérent.

Commit `feat: thème console d'opérations sombre, header, toasts, réglages`.

### Task A3 : couche connexion — useVesselFeed + erreurs REST visibles

**Files :** Create `src/components/common/useVesselFeed.ts` ; Delete
`src/components/common/websocket.tsx` ; Modify `apis.tsx`, `home_dashboard.tsx`,
call-sites des APIs (addVesselMenu, modelDashboard, modelAdd…).

```ts
export type FeedStatus = 'connecting' | 'online' | 'reconnecting' | 'offline';
export function useVesselFeed(ip: string, port: number, instance: string): {
  vessels: VesselData[]; status: FeedStatus; lastUpdate: number | null;
}
```
- WebSocket natif ; onopen → envoie `{instance}` puis status online, reset backoff ;
  onmessage → validation forme (comme l'existante) → setVessels ; onclose/onerror →
  si démonté rien, sinon status reconnecting et retry après `min(15000, 1000*2^n)` ;
  après 4 échecs consécutifs status offline (mais retry continue) ; cleanup complet
  au unmount/changement de deps (close + clearTimeout, garde `disposed`).
- `apis.tsx` : les fonctions **jettent** (plus de catch→false/[]) ; payloads typés
  `Record<string, unknown>` ; `getAddress()` valide (port NaN/hors bornes → défauts) ;
  call-sites : try/catch → `toast.error('...' + message serveur si présent)`,
  succès création/suppression → `toast.success`.
- `home_dashboard` : remplace la classe WS par le hook ; `status` alimente le header.
- Preuve : type-check/lint/build verts + `bun test` sur un util pur extrait si besoin
  (le backoff : exporter `nextDelay(attempt): number` et le tester).

Commit `feat: flux navires robuste (reconnexion, statut) et erreurs REST visibles`.

### Task A4 : carte pro — fond sombre, markers stables, traînées, panneau Flotte

**Files :** Create `src/components/map/FleetPanel.tsx`,
`src/components/map/tracks.ts` ; Modify `map.tsx`, `mapMarker.tsx`,
`home_dashboard.tsx`.

- `tracks.ts` (pur, testé avec `bun test` — fichier `tracks.test.ts`) :
  `updateTracks(prev: Tracks, vessels: VesselData[], now: number): Tracks` — par
  navire : anneau des 60 dernières positions (poussée seulement si déplacement
  > ~0.5 m), `speedKn` calculée sur les ~5 derniers points (haversine/dt, 0 si stale),
  `lastSeen`. Navires disparus purgés après 30 s.
- `map.tsx` : BaseLayer par défaut « Dark » = CARTO dark_all
  (`https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png`, attribution CARTO,
  maxNativeZoom 19 aussi) ; puis OSM et Satellite existants. Traînées : une
  `<Polyline>` par navire (positions du track, couleur `vesselColor(name)`,
  weight 2, opacity .7). Markers : `key={vessel.vessel_name}` (fini l'index).
- `mapMarker.tsx` : popup enrichi — nom (gras, couleur du navire), lat/lon (mono,
  5 décimales), cap (°), vitesse (kn), âge de la donnée ; l'icône garde la rotation
  heading (filtre/teinte selon vesselColor si simple, sinon icône existante).
- `FleetPanel.tsx` : panneau flottant gauche (absolute, top 16 left 16, z-index
  au-dessus de la carte, fond rgba(30,41,59,.85) + backdrop-blur, radius 12) —
  titre « Fleet » + badge count, repliable (chevron). Par navire : pastille couleur,
  nom, flèche de cap (rotate), vitesse kn, lat/lon mono petit, âge (« 2s ago »,
  ambre si > 10 s). Clic → `flyTo` la position (map ref exposée) + openPopup.
  Vide : « No vessels — right-click the map to add one ».
- `home_dashboard` : `useVesselFeed` → `updateTracks` (useMemo/useState) → Map +
  FleetPanel.
- Preuve : type-check/lint/build + `bun test` verts.

Commit `feat: carte opérationnelle — fond sombre, traînées, panneau flotte live`.

### Task A5 : pages Models + AddVessel au niveau du thème

**Files :** Modify `modelDashboard.tsx`, `modelPanel.tsx`, `modelAdd.tsx`,
`addVesselMenu.tsx`, `MapContextMenu.tsx` (retouches légères).

- Models : container max-width 1200 centré, titre + sous-titre, cards du grid avec
  hover (elevation), bouton « Add model » en position claire, empty state propre,
  suppressions avec confirm + toast. Pas de refonte des formulaires internes.
- AddVesselMenu / MapContextMenu : hérite du thème (vérifier lisibilité fond sombre),
  espacements sections (Divider + subtitles), boutons cohérents. Aucun changement
  des champs ni du XML généré.
- Preuve : type-check/lint/build verts, rendu visuel vérifié par l'orchestrateur.

Commit `feat: pages Models et dialogs au niveau du thème sombre`.

---

## Reviews & e2e

- Review opus après B2 (cycle de vie subprocess) et A3 (hook reconnexion).
- Review finale de branche (opus) par repo avant e2e.
- E2E (orchestrateur) : rig conteneur `tsm-e2e` — run lancé depuis l'IHM tsm,
  timeline + mini-carte vivantes, stop propre, launch grisé pendant le run ;
  IHM LOTUSim sombre, flotte + traînées pendant la poursuite. Captures Playwright.
- Fin : ff-merge `refonte-ihm` → main (tsm), commits sur `lab-patches` (frontend),
  PAS de push, mémoire + rapport final.
