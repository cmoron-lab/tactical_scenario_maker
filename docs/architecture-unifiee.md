# Architecture unifiée — simulation de scénarios tactiques LOTUSim

**Statut** : v0.1 — brouillon de convergence, à discuter avec Estelle
**Auteurs** : Cyril Moron (Architecte LOTUSim), à partir des travaux d'Estelle Chauveau (PO LOTUSim)
**Date** : 2026-07-12

**Documents de référence** :

- [LSGA Architecture v2](lsga-architecture-v2.md) (Estelle) — le pipeline de génération ;
- [ARCHITECTURE.md](ARCHITECTURE.md) (tsm) — les décisions D1–D8 et l'architecture cible côté exécution.

Les échanges qui ont mené à ce document — review LSGA v2 (Cyril, 11/07,
remarques R1–R7) et note « Trois niveaux de décision » (Estelle, 12/07) — sont
**absorbés ici** ; leur texte intégral reste dans l'historique git
(`docs/reviews/`, nettoyé le 2026-07-12).

---

## 1. Objet

Ce document consolide en un seul modèle les travaux LSGA (génération de scénarios)
et les travaux tsm (exécution), enrichis des concepts qui manquaient aux deux :
la **cellule blanche**, les **forces multiples**, et l'**end state** d'un scénario.
Il sert de socle commun — le document « Execution Environment — périmètre et
contrat » commandé par la note du 12/07 en approfondira le chapitre 4.

Il répond au passage à la question ouverte §9 de la note (la boucle à ~2 s de
tsm : niveau 2 ou niveau 3 ? — voir §4.3).

## 2. Vue d'ensemble : des forces, une cellule blanche

Le constat fondateur : une simulation tactique a la même anatomie qu'un exercice
naval réel (ou qu'un jeu vidéo de simulation) — plusieurs **forces** qui décident
chacune pour elle-même, et une **cellule blanche** qui tient l'exercice.

```
                    ┌─────────────────────────────────────────┐
                    │  CELLULE BLANCHE (unique, transverse)   │
                    │  autorat scénario · règles du monde ·   │
                    │  injections (triggers) · adjudication · │
                    │  end state / verdict · fin du run       │
                    │  → seule vue de dieu légitime           │
                    └──────────────┬──────────────────────────┘
                                   │ observe tout, arbitre tout
        ┌──────────────────────────┼──────────────────────────┐
        │ FORCE bleue              │ FORCE rouge       FORCE verte …
        │ ┌──────────────────┐     │  (même gabarit)   (même gabarit)
        │ │ N1 Planification │     │
        │ │ N2 Supervision   │     │  ← relations entre forces :
        │ │    (par agent)   │     │    hostile / neutre / allié,
        │ │ N3 Guidage       │     │    évolutives par trigger
        │ └──────────────────┘     │
        └──────────────────────────┴──────────────────────────┘
```

### 2.1 Le gabarit à trois niveaux, instancié par force

Le tableau de la note du 12/07 est repris tel quel — avec un amendement de
multiplicité : ce n'est pas UNE pile, c'est un **gabarit instancié par force**.

| Niveau | Analogie | Nature | Horizon | Responsable |
|---|---|---|---|---|
| **1. Planification** | Commandement de la force | HTN symbolique complet, tous les agents *de cette force* | Mission — épisodique | LSGA |
| **2. Supervision** | Commandant de bord | HTN local par agent, réparation de plan | Secondes — continu | Exécutif de mission |
| **3. Guidage** | Homme de barre | Continu, non symbolique : consignes, asservissements | Hertz | Plateforme |

Chaque force a son commandement (niveau 1), ses superviseurs d'agents
(niveau 2), ses plateformes (niveau 3). Une force peut être réduite à un agent
(la pile s'effondre en une mission simple) ou à une trajectoire scriptée (pas
de niveau 1-2 du tout — un figurant).

### 2.2 La cellule blanche, quatrième layer orthogonal

La cellule blanche n'est **pas un niveau de décision** : les niveaux 1-2-3 sont
la chaîne de commandement d'une force *dans la fiction* ; la cellule blanche est
*hors de la fiction*. C'est le composant dont la review LSGA (R1) signalait
l'absence — vu ici dans sa version complète. Ses responsabilités :

1. **Autorat** : le Scenario Request décrit toutes les forces, camps confondus
   — c'est un travail de cellule blanche (voir §2.4) ;
2. **Injections** : déclencher les événements scriptés du scénario (l'équivalent
   de la MSEL d'un exercice réel) — apparition d'une force, changement de météo,
   bascule d'allégeance ;
3. **Adjudication** : appliquer les règles du monde que la physique ne simule
   pas — engagements, dégâts, destruction (voir §5.3) ;
4. **Verdict et fin** : évaluer en continu l'end state du scénario
   (succès / échec / timeout) et terminer le run (voir §5.1) ;
5. **Monitoring** : journaliser l'exécution et porter le critère d'escalade
   vers la replanification de niveau 1 (la réponse à R1).

Elle est la **seule détentrice légitime de la vérité terrain** : elle voit tout,
par définition. Elle est **neutre** : elle applique les règles uniformément,
quelle que soit la force.

### 2.3 Forces et allégeances

Ce qui définit une force n'est pas « ennemie de bleu » mais **un commandement
unifié** : mêmes objectifs, même information partagée, un seul plan cohérent.
Deux groupes adverses entre eux sont deux forces — un même commandement ne peut
pas produire un plan qui se combat lui-même.

Il en découle deux objets de première classe dans le modèle de scénario :

- **La force** : un commandement, des agents, une information propre. N forces,
  sans limite ni symétrie (les couleurs bleu/rouge/vert ne sont qu'une
  convention de nommage relative à l'audience de l'exercice).
- **L'allégeance** : une *relation entre forces* (hostile / neutre / allié) —
  pas une propriété d'une force. Elle peut être non-symétrique (le pêcheur
  ignore que le pirate le considère comme une proie) et évoluer en cours de
  scénario par trigger (le neutre devient hostile quand on lui tire dessus).

Cas limites qui valident le modèle : deux forces alliées sans liaison = deux
cellules (coalition sans partage d'information) ; du rouge contre rouge ne coûte
rien (l'arbitre applique les mêmes règles, la matrice de relations fait le reste).

### 2.4 La vue de dieu, requalifiée

LSGA v2 qualifie la planification initiale de « vue de dieu, intégrant tous les
agents ». Ce n'est pas une erreur, c'est un amalgame entre deux rôles :

- **L'auteur d'exercice** (cellule blanche) écrit les missions de *toutes* les
  forces — l'intrus a une mission parce que l'auteur la lui a écrite. Vue de
  dieu **légitime** : c'est de l'autorat, hors ligne.
- **Le commandement d'une force** (niveau 1) planifie avec la seule information
  de sa force — la situation initiale que le scénario déclare connue d'elle.
  Vue de dieu **à proscrire** dès que la simulation évalue quelque chose : si
  le niveau 1 bleu connaît le plan rouge, l'escorte « sait » d'où viendra
  l'embuscade et le résultat est biaisé.

L'asymétrie d'information est donc un **curseur explicite du scénario**, pas un
tout-ou-rien : vue de dieu partout pour une démo scriptée ; information par
force pour de l'évaluation de tactiques ou d'autonomie. Le même curseur
s'applique au niveau 2 (la perception des superviseurs — voir §8, angle mort
senseurs).

## 3. Niveau 1 — la génération (LSGA)

Le pipeline LSGA v2 est repris sans modification structurelle — cinq
représentations, quatre transformations, un composant = une transformation :

```
Scenario Request ─► Planning Model ─► Raw Planning Result ─► Execution Graph ─► Simulation State
       (validation)     │ WAL │        Planning Engine │        EAL │           (exécution)
```

Le WAL abstrait le monde en prédicats symboliques ; le moteur HTN (pandaPI ou
HyperTensioN, sous réserve du profil HDDL) décompose ; l'EAL retraduit en tâches
affectées par agent. WAL et EAL isolent le moteur, qui reste substituable.

Ce que le modèle multi-forces y change :

- le **Scenario Request** est un artefact de cellule blanche : il décrit toutes
  les forces, leurs relations, les triggers et l'end state (voir §5) ;
- la planification produit **un plan par force** — un Problem HDDL par force,
  restreint à l'information que le scénario lui accorde (curseur §2.4). Pour
  une première version, un seul appel moteur par force suffit ; la vue de dieu
  à l'autorat garantit la cohérence d'ensemble ;
- l'**Execution Graph** descend vers les superviseurs de chaque force,
  tâches affectées par agent (contrat 1 ↔ 2 de la note du 12/07).

## 4. Niveaux 2 et 3 — l'Execution Environment

Chapitre à approfondir dans « Execution Environment — périmètre et contrat ».
Critères d'acceptation posés par la note du 12/07 :

1. distinguer explicitement supervision (niveau 2) et guidage (niveau 3), avec
   leurs responsabilités respectives — sans reconduire leur fusion actuelle
   dans tsm ;
2. spécifier le contrat 2 ↔ 3 en actions typées avec cycle de vie ;
3. positionner le modèle de données du monitoring par rapport aux
   *achievements* de la thèse d'Antoine Milot ;
4. faire figurer le critère d'escalade vers la replanification LSGA (§4.4)
   comme élément du contrat.

### 4.1 Supervision (niveau 2)

Un superviseur **par agent** : HTN local léger (type GTPyhop — qui trouve ici sa
juste place sans porter le pipeline HDDL), état local observé, tâches acquises
depuis l'Execution Graph. Il répare son plan localement quand une action échoue,
et remonte ce qu'il ne peut pas rattraper (critère d'escalade, §4.4). C'est
la structure actuelle de tsm (un thread par agent) — la migration est naturelle.

### 4.2 Guidage (niveau 3) et actions typées

Le contrat 2 ↔ 3 est spécifié en **actions typées avec cycle de vie**
(décision D5 d'ARCHITECTURE.md, pattern Nav2) :

```
soumis → accepté → en cours (feedback continu) → réussi | échoué | annulé | timeout
```

Familles d'actions minimales pour le scénario de référence (§6) :

| Famille | Exemple | Note |
|---|---|---|
| `navigation.goto` | rejoindre un point/zone | l'existant (waypoints) |
| `navigation.follow_target` | tenir une poursuite/un poste sur cible **mobile** | **la primitive qui manque** — voir §4.3 |
| `engage.attack_target` | engager une cible désignée | résolue par l'arbitre (§5.3) |

Sans `follow_target`, tout exécutif doit re-décider un point fixe en boucle —
c'est exactement la pathologie actuelle de tsm.

### 4.3 Réponse à la question §9 — la boucle à ~2 s

La boucle actuelle de tsm fait **les deux niveaux dans le même mécanisme** :

- Le *mécanisme* est du niveau 2 : à chaque réveil, re-décomposition HTN
  complète depuis la mission racine, préconditions réévaluées — c'est ce qui
  permet les vraies bascules de branche (patrouille → poursuite → capture →
  retour base). Ces bascules sont **épisodiques** : quelques-unes par mission.
- Ce qui tourne à ~2 s est du **niveau 3 déguisé** : pendant une poursuite,
  chaque cycle produit le même plan à une action — `aller_a (lat, lon)` — avec
  des coordonnées rafraîchies. La preuve : la cadence n'est pas décidée par le
  planificateur mais par une hystérésis métrique (`MIN_MOVE_DEG` ≈ 33 m entre
  deux waypoints émis) — signature d'une boucle de guidage, pas d'une
  replanification au sens du vocabulaire de la note.

Cause racine : le WaypointFollower de LOTUSim ne connaît que des points fixes —
pas de primitive « suis cette cible mobile ». tsm compense en re-décidant le
point fixe depuis le symbolique. La sortie est l'action `follow_target` du §4.2 :
le superviseur commande « poursuis l'intrus » une fois ; le niveau 3 tient la
poursuite en continu ; le niveau 2 ne replanifie plus que sur événement.

Conformément au vocabulaire de la note : les entrées « plan » à ~2 s de notre
journal d'exécution sont presque toutes des **recalculs de consigne**
(niveau 3), pas des replanifications.

### 4.4 Critère d'escalade

Repris de la note du 12/07 : *chaque niveau rattrape ce qu'il peut et remonte ce
qu'il ne peut pas.*

- Guidage en échec (waypoint inatteignable, cible perdue) → **réparation
  locale** par le superviseur de l'agent (niveau 2) ;
- Réparation locale en échec, ou nouvel objectif hors des tâches acquises →
  **escalade** vers la replanification complète de la force (niveau 1), portée
  par le monitoring de la cellule blanche.

### 4.5 Discipline de vocabulaire

Reprise de la note du 12/07 :

- **replanification** : production d'un nouveau plan symbolique — réservé aux
  niveaux 1 et 2 ;
- **réparation locale** : replanification de niveau 2, par agent, sur
  représentation réduite ;
- **recalcul de consigne / guidage** : niveau 3, continu, sans planificateur —
  ce que fait en réalité la boucle à ~2 s de tsm (§4.3).

## 5. La cellule blanche en détail

### 5.1 End state et verdict

Constat partagé (manquant dans LSGA v2 **et** dans ARCHITECTURE.md) : un
scénario de simulation, comme une mission de jeu vidéo ou un exercice réel, a
des **critères de succès / échec / fin**. Aujourd'hui rien ne les porte : D5
donne un verdict *par objectif*, §9.4 d'ARCHITECTURE.md dit quoi *archiver* —
personne ne dit **quand ni pourquoi un run se termine** (symptôme : un run tsm
ne se termine jamais seul, et `finished/failed` parle du process, pas de la
mission).

Le concept a des noms établis : **end state** (planification opérationnelle),
critères pass/fail et **StopTrigger** (OpenSCENARIO). Le scénario les déclare
(§5.5) ; la cellule blanche les évalue en continu et prononce le verdict.

### 5.2 Injections (triggers)

Des couples condition → actions, évalués par la cellule blanche sur l'état
simulé : apparition d'une force (embuscade), événement d'environnement,
bascule d'allégeance. L'horloge de référence est le **temps simulé** (point
déjà flaggé par ARCHITECTURE.md §8.3).

### 5.3 Adjudication — le combat n'est pas de la physique

L'engagement se traite comme dans tout jeu de simulation : un **arbitre**
(portée + cadence + probabilité + points de vie), pas de la balistique. Mort →
suppression de l'entité. Architecturalement :

- `engage.attack_target` est une **capacité** (D3) dont le backend v1 est
  « arbitré » (littéralement le backend *scénarisé* de D6) — un backend
  balistique pourra s'y substituer sans toucher au contrat ;
- l'arbitre est un composant de cellule blanche, pur logiciel côté exécution
  (aucun plugin Gazebo requis : il consomme les poses, adjuge, émet des
  suppressions d'entités).

### 5.4 Un seul langage de conditions

Les conditions des triggers, de l'end state et des préconditions HTN partagent
le **même vocabulaire** (`in_zone`, `distance_below`, temps simulé, état d'un
agent…). Un seul formalisme, deux consommateurs : la doctrine (décisions
d'agent, niveau 2) et la cellule blanche (décisions d'exercice). C'est déjà le
vocabulaire implémenté dans tsm — on ne crée pas un deuxième langage.

### 5.5 Références

Alignement **conceptuel** (pas de reprise du format) :

- **ASAM OpenSCENARIO** : storyboard, conditions/triggers, StopTrigger ;
  critères pass/fail à la manière du `scenario_runner` de CARLA. Le XML,
  couplé à OpenDRIVE (routier), n'est pas repris — le schéma reste notre JSON.
- **Vocabulaire exercice** : cellule blanche / EXCON, MSEL (liste d'injections),
  end state, MOE. SISO MSDL reste la référence pour l'ordre de bataille initial
  (structure du Scenario Request), pas pour les triggers.

## 6. Scénario de référence — « Escorte du détroit d'Ormuz »

Un scénario type mission de jeu de simulation navale, d'actualité, qui exerce
**tous** les contrats du document. Il sert de banc d'essai : chaque incrément de
la trajectoire (§7) doit en faire tourner un morceau de plus.

### 6.1 Narratif

> Un convoi de deux cargos (force **verte**, civile) transite le détroit
> d'Ormuz vers l'ouest, escorté par une frégate (force **bleue**). Quand le
> convoi entre dans la passe, deux vedettes rapides (force **rouge**) surgissent
> de la côte nord et foncent sur les cargos. La frégate doit les détecter,
> s'interposer et les neutraliser.
> **Succès** : les deux cargos atteignent la zone de sortie ouest.
> **Échec** : un cargo est détruit. **Timeout** : 30 min simulées.

Relations : rouge hostile envers vert et bleu ; bleu protège vert ; vert neutre
(il subit). Trois forces, relations non-symétriques — le modèle §2.3 au complet.

### 6.2 Déroulé annoté — qui décide quoi

| # | Événement | Qui décide | Contrat exercé |
|---|---|---|---|
| 1 | Spawn initial : convoi + escorte à l'entrée est | Cellule blanche (autorat) | Scenario Request multi-forces |
| 2 | Plans initiaux : route du convoi, station de l'escorte, consigne d'attente rouge | Niveau 1 **par force** | Un Problem HDDL par force ; Execution Graph |
| 3 | Le convoi entre dans la passe → apparition des vedettes | Cellule blanche (injection) | Trigger `in_zone` → spawn |
| 4 | L'escorte détecte les vedettes (seuil de portée) | Niveau 2 bleu (bascule de branche) | Prédicat calculé (WAL runtime) |
| 5 | L'escorte s'interpose entre vedettes et cargo | Niveau 2 bleu → niveau 3 | `follow_target` (poste sur cible mobile) |
| 6 | Les vedettes foncent sur le cargo le plus proche | Niveau 2 rouge → niveau 3 | `follow_target` (poursuite) |
| 7 | L'escorte engage la vedette de tête | Niveau 2 bleu → arbitre | `engage.attack_target` + adjudication (HP, portée, cadence) |
| 8 | Vedette 1 détruite → suppression de l'entité | Cellule blanche (adjudication) | Verdict d'action typée : `réussi` |
| 9 | Vedette 2 : effectif sous le seuil doctrinal → repli | Niveau 2 rouge (réparation locale) | Bascule de branche HTN, aucune escalade |
| 10 | Les cargos atteignent la zone ouest → fin du run | Cellule blanche (verdict) | End state `success`, rapport de provenance (§9.4 ARCHITECTURE.md) |

Chaque ligne est un test d'intégration en puissance.

### 6.3 Esquisse de schéma v2

Évolutions du JSON v1 : les forces et relations deviennent de première classe,
les triggers et l'end state apparaissent, le vocabulaire de conditions est
réutilisé tel quel.

```json
{
  "version": 2,
  "forces": {
    "bleue": {"agents": ["escorte"]},
    "rouge": {"agents": ["vedette_1", "vedette_2"], "spawn": "deferred"},
    "verte": {"agents": ["cargo_1", "cargo_2"]}
  },
  "relations": [
    {"from": "rouge", "to": ["bleue", "verte"], "attitude": "hostile"},
    {"from": "bleue", "to": "verte", "attitude": "protect"}
  ],
  "agents": { "…": "inchangé (position, modèle, mission, conditions)" },
  "triggers": [
    { "when": {"type": "in_zone", "agent": "cargo_1", "zone": "passe_ormuz"},
      "do":   [{"action": "spawn_force", "force": "rouge"}] }
  ],
  "end": {
    "success": [{"type": "all_in_zone", "force": "verte", "zone": "sortie_ouest"}],
    "failure": [{"type": "agent_destroyed", "force": "verte"}],
    "timeout": "PT30M"
  }
}
```

## 7. Existant et trajectoire de convergence

### 7.1 Correspondance LSGA ↔ tsm

tsm implémente une tranche verticale du pipeline, vérifiée e2e dans LOTUSim
(démo : poursuite multi-agents avec suivi d'exécution temps réel) :

| LSGA | Équivalent tsm | Statut |
|---|---|---|
| Scenario Request | Schéma JSON v1 versionné | Implémenté — candidat pour la structure « à définir » (Annexe D LSGA) |
| Validation | Validation structurelle au chargement | Implémenté (structurel) ; validation métier à spécifier |
| World Abstraction Layer | `build_state` + `sync_positions`, préconditions calculées | Implémenté — mêmes « prédicats calculés » |
| Domain HDDL | `knowledge_base.json` + méthodes HTN Python | Implémenté **en code** — delta n°1 : traduction HDDL |
| Planning Engine Wrapper | Classe `Planner` (GTPyhop confiné, substituable) | Implémenté |
| Raw Planning Result | Plan GTPyhop (transitoire, jamais exposé) | Implémenté |
| EAL / Execution Graph | `make_commands` + runner | Implémenté en **flux** — delta n°2 : artefact versionnable |
| Execution Environment | gz/WaypointFollower + boucle exécutive par agent | Implémenté — fusion N2/N3 à résorber (§4.3) |
| Monitoring d'exécution | Journal d'événements, cycle de vie du run, IHM temps réel | Implémenté — à rattacher à la cellule blanche (§2.2) |

Les deux deltas LSGA restent derrière des coutures en place (doctrine derrière
un store dédié, commandes derrière le runner) — résorbables par incréments.

### 7.2 Incréments

Incréments proposés, chacun petit et validé sur le scénario de référence :

| # | Incrément | Porte | Débloque (déroulé §6.2) |
|---|---|---|---|
| 1 | Schéma v2 : forces, relations, `end` (timeout + zones) | Domaine | Lignes 1, 10 — un run qui se termine seul |
| 2 | Superviseur de scénario (cellule blanche runtime) : évalue conditions, injecte, termine | Exécution | Lignes 3, 10 |
| 3 | Actions typées D5 (cycle de vie), dont `follow_target` | Exécution ↔ LOTUSim | Lignes 5, 6 — sépare N2/N3, réponse au critère d'acceptation n°1 de la note |
| 4 | Combat arbitré : `engage.attack_target`, HP, destruction | Cellule blanche | Lignes 7, 8, 9 |
| 5 | Perception par force (curseur d'asymétrie, §2.4) | Exécution | Qualité d'évaluation — différable |
| 6 | Doctrine → HDDL, Execution Graph versionnable | Niveau 1 | Trajectoire LSGA de fond |

Les incréments 1–4 suffisent à jouer le scénario de référence de bout en bout.

## 8. Points ouverts

1. **Achievements** (critère d'acceptation n°3 de la note) : accès à la thèse
   d'Antoine Milot nécessaire pour positionner le modèle de données du
   monitoring — demandé à Estelle.
2. **Où vit la cellule blanche runtime** : composant tsm (POC) à terme candidat
   à l'Orchestrateur de simulation (ARCHITECTURE.md §7.4) — à trancher avec le
   contrat Execution Environment.
3. **Perception / senseurs** : angle mort partagé des deux architectures. Le
   seuil de distance (modèle « concealment » de jeu vidéo) est assumé comme
   modèle de détection v1 ; un vrai modèle senseur par agent est hors périmètre
   pour l'instant — le curseur §2.4 le prépare.
4. **État numérique persistant du niveau 2** (`orbit_angle`, `last_waypoint`) :
   à répartir explicitement entre supervision et guidage dans le contrat 2 ↔ 3.
5. **Profil HDDL** (R4 de la review) : reste le premier livrable côté niveau 1.
