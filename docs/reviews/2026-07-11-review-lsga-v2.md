# Note de review — LSGA Architecture v2

**Document reviewé** : LOTUSim Scenario Generation Architecture (LSGA), v2 clean
**Auteure** : Estelle (PO LOTUSim)
**Reviewer** : Cyril Moron (Architecte LOTUSim)
**Date** : 2026-07-11

---

## 1. Avis général

Très bon document d'architecture : le pipeline en cinq représentations avec « un
composant = une transformation », les contrats explicites (chapitre 6), l'immutabilité
amont, le déterminisme et la traçabilité versionnée constituent un socle rigoureux,
testable et durable. Les choix fondamentaux — HTN justifié par la nature procédurale
des doctrines navales, séparation stricte doctrine/scénario, LLM cantonné à la
proposition sous validation humaine, validation systématique — sont les bons, et ce
ne sont pas des paris : **ils sont déjà validés expérimentalement** par le POC
`tactical_scenario_maker` (ci-après tsm), qui implémente une tranche verticale de
cette architecture et l'exécute de bout en bout dans LOTUSim (démo vérifiée :
poursuite multi-agents avec replanification continue, suivi d'exécution temps réel).

La review propose donc deux lectures : des remarques sur le document lui-même (§3),
et une cartographie de l'existant (§4-5) montrant que l'Étape 1 de la roadmap
logicielle (« prototype minimal ») a de fait déjà un banc d'essai fonctionnel.

## 2. Points forts

- **Architecture orientée modèles** : cinq représentations à responsable unique,
  invariants explicites (§4.4), matrice « ne fait jamais » (§6.7) — le niveau
  d'exigence qu'il faut pour un composant central de plateforme.
- **Choix HTN argumenté métier** (MDMP, décomposition doctrinale OTAN) plutôt que
  technologique — c'est la bonne justification, la même qui a guidé tsm.
- **Positionnement du LLM** (§5.3) : outil d'assistance, jamais d'écriture de
  doctrine, validation obligatoire (P5). Aligné avec notre décision de parquer le
  générateur IA du POC derrière une étape de validation.
- **Prédicats calculés par le WAL** (§5.5) : abstraire les grandeurs physiques en
  prédicats symboliques est exactement le mécanisme que tsm emploie (préconditions
  de distance calculées depuis les positions observées) — il fonctionne.
- Les couches d'adaptation symétriques WAL/EAL, qui isolent le moteur : le pattern
  « wrapper » du moteur est également validé chez nous (voir §4).

## 3. Remarques et questions

**R1 — La boucle de retour est sous-spécifiée (remarque principale).**
La replanification (§5.7) exige la « capture de l'état courant », donc un flux
Simulation State → LSGA. Or aucun composant n'a la responsabilité du **monitoring
d'exécution ni du déclenchement** : qui détecte l'aléa ? qui décide de replanifier ?
qui suit l'avancement de l'Execution Graph ? Le document dessine l'aller
(génération) mais pas le retour (observation). Ce chaînon existe aujourd'hui dans
tsm (journal d'événements d'exécution, cycle de vie du run, états
idle/running/finished/failed, arrêt propre) et mérite un composant nommé dans LSGA
— ou une assignation explicite à l'Execution Environment, avec son contrat.

**R2 — Cadence de replanification : dimensionnement à expliciter.**
La replanification complète (re-pipeline entier : WAL → moteur → EAL) convient aux
aléas épisodiques. Nos expérimentations montrent qu'un scénario de poursuite
replanifie **toutes les ~2 secondes** (réaction au mouvement de la cible). Cette
boucle réactive appartient bien à l'Execution Environment comme le document le pose
(§5.6) — mais il faut alors dire explicitement que l'Exécutif embarque un
planificateur local rapide, et définir la frontière entre « replanification LSGA »
(épisodique, complète) et « adaptation exécutive » (continue, locale). Sinon la
première version découvrira cette frontière dans l'urgence.

**R3 — pandaPI : la réserve de licence est LE risque de l'Étape 1.**
Le document le flague lui-même (§5.8). Proposition de repli à coût nul : GTPyhop
(licence BSD, Python) est déjà **vendored et encapsulé** derrière une interface de
type Planning Engine Wrapper dans tsm. Le prototype minimal peut démarrer avec, et
le wrapper garantit la substitution ultérieure — c'est précisément ce que
l'architecture promet.

**R4 — Le profil HDDL est le pivot de faisabilité : le prioriser.**
Les méthodes HTN de tsm sont du code (calculs géométriques, résolution de
désignations de cibles au moment de la décomposition). Les méthodes HDDL sont
déclaratives. La migration doctrine-code → Domain HDDL n'est **pas un swap de
moteur, c'est un projet de traduction**, et sa faisabilité dépend entièrement des
choix du profil HDDL (extensions autorisées, expressivité des préconditions). Ce
document, listé « à définir » (Annexe D), devrait être le premier livrable après
LSGA v2 — avant l'ontologie au sens large.

**R5 — S'appuyer sur les standards existants.**
Le document ne référence aucun standard de description de scénario ou d'exécution.
Recommandation de croiser avec l'état de l'art déjà cartographié dans
`tactical_scenario_maker/docs/ARCHITECTURE.md` §16 : SISO **MSDL** (structure du
Scenario Request), **C2SIM/C-BML** (formalisation d'ordres), ASAM **OpenSCENARIO**
(séparation scénario/monde, déclencheurs), **Nav2/PlanSys2** (actions ROS 2 typées
et cycle de vie, pour l'Execution Graph côté exécution), scenario_runner de CARLA
(pattern générateur→exécuteur). L'alignement du Scenario Request sur MSDL, même
partiel, faciliterait l'interopérabilité défense.

**R6 — Roadmap très documentaire : ancrer chaque document dans le prototype.**
Six livrables documentaires précèdent l'industrialisation. Risque classique de
paralysie spécificatoire. Le prototype minimal (Étape 1) existe déjà de fait (§4) :
proposer que chaque document (profil HDDL, ontologie, Mission Catalog) soit validé
contre ce banc d'essai au fil de l'eau plutôt qu'en cascade.

**R7 — Mineures.**
Redondances entre §2.4/§4.2 et entre les rationales (§3.9/§4.8/§5.11) ; le composant
« Validation » comme *responsable* de la représentation Scenario Request est une
bizarrerie de la matrice (un validateur ne devrait pas posséder ce qu'il valide) ;
la place de l'éditeur/IHM dans la famille documentaire n'est pas définie alors que
la « saisie experte » est une source de première classe ; prévoir un mot sur la
gestion d'accès au patrimoine doctrinal (contexte industriel de défense).

## 4. Ce qui existe déjà : identifié, architecturé, implémenté

Le POC tsm (repo `tactical_scenario_maker`) implémente une tranche verticale du
pipeline LSGA, vérifiée e2e dans LOTUSim (gz + entity_manager + WaypointFollower).
Correspondance composant à composant :

| LSGA | Équivalent tsm | Statut |
|---|---|---|
| Scenario Request | Schéma de scénario **JSON v1** versionné (agents, positions, vitesses, conditions, mission), indépendant du planificateur | **Implémenté** — candidat pour la structure « à définir » (Annexe D) |
| Validation | Validation structurelle au chargement (`Scenario.from_dict`, gardes) | Implémenté (structurel) ; validation métier à spécifier des deux côtés |
| World Abstraction Layer | `build_state` + `sync_positions` : traduction des poses observées en état symbolique ; préconditions calculées (distances) | **Implémenté** — même frontière, mêmes « prédicats calculés » que §5.5 |
| Domain HDDL | `knowledge_base.json` (doctrine éditable via IHM) + méthodes HTN Python | Implémenté **en code** — c'est la divergence n°1 (cf. R4) |
| Planning Engine Wrapper | Classe `Planner` : GTPyhop entièrement confiné (état global du moteur isolé, verrou, interface stable) | **Implémenté** — le pattern wrapper est démontré ; moteur substituable |
| Raw Planning Result | Plan GTPyhop (transitoire, jamais exposé) | Implémenté |
| EAL / Execution Graph | `make_commands` + runner : plan → commandes LOTUSim (waypoints) | Implémenté en **flux** (pas d'artefact graphe versionnable) — divergence n°2 |
| Execution Environment | gz/entity_manager/WaypointFollower + **boucle exécutive tsm** : replanification événementielle par agent (réveil sur changement de position observée) | Implémenté — c'est la « coordination réactive » que LSGA délègue (cf. R1/R2) |
| Monitoring d'exécution | Journal d'événements de run (démarrages, spawns, plans, fin), gestionnaire de cycle de vie (un run à la fois, arrêt propre, états), suivi temps réel dans l'IHM (timeline + carte live) | **Implémenté** (2026-07-10) — sans équivalent dans LSGA v2 (cf. R1) |

S'y ajoutent, côté architecture : `docs/ARCHITECTURE.md` (composants logiques
convergents : Éditeur tactique / Domaine tactique / Exécutif de mission, principe
« le planificateur s'engage, l'exécutif surveille », cartographie des standards
§16) et l'incrément suivant déjà cadré : **cycle de vie des objectifs en actions
ROS 2 typées par famille (pattern Nav2)** — qui est précisément la matière du
contrat Execution Environment ↔ Execution Graph.

Preuves d'exécution disponibles : scénario multi-agents (veilleur / drone
poursuivant / intrus) joué de bout en bout — planification, spawn, poursuite avec
replanification continue, capture, retour de zone — piloté et observé depuis les
IHM. 41 tests unitaires sans ROS sur les couches domaine/planification/exécution/web.

## 5. Compatibilité et trajectoire de convergence

Verdict : **compatible dans les principes, convergent dans la structure ; deux
deltas réels, tous deux derrière des coutures déjà en place.**

1. **Doctrine → Domain HDDL** (R4) : la doctrine tsm est stockée dans un artefact
   dédié derrière un store — le point d'insertion d'un traducteur ou d'une
   réécriture HDDL est net. Faisabilité conditionnée par le profil HDDL.
2. **Flux de commandes → Execution Graph** : matérialiser le plan en artefact
   versionnable avant exécution est une évolution locale du runner (le journal
   d'événements en capture déjà une trace).

Trajectoire proposée : faire de tsm le **banc d'essai officiel de l'Étape 1** —
chaque livrable documentaire (profil HDDL, Scenario Request, contrat Execution
Environment) se valide contre lui, et les deux deltas se résorbent par incréments
sans big-bang.

## 6. Proposition — TODO Architecture (« LOTUSim Execution Environment »)

Le document m'assigne la définition du périmètre, du contrat et des interfaces de
l'Execution Environment (§3.8, §6.5, Annexe C). Le matériau existe : contrat
concret actuel (action de gestion d'entités, flux de positions, services de
waypoints), principes exécutifs d'ARCHITECTURE.md, cycle de vie des objectifs en
actions typées (pattern Nav2), et le monitoring d'exécution livré. Je propose de
répondre à ce TODO par un document court « Execution Environment — périmètre et
contrat » dans la même famille documentaire, en y intégrant la réponse à R1
(composant de monitoring/déclenchement) et la frontière de R2 (replanification
épisodique vs adaptation continue).
