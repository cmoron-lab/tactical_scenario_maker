<!-- Conversion markdown du document « LSGA Architecture v2 clean.docx » (Estelle,
     PO LOTUSim) pour relecture — le .docx reste la source de référence. -->

# LOTUSim Scenario Generation Architecture (LSGA)


## 1. Introduction


### 1.1 Objet du document

Le présent document décrit la LOTUSim Scenario Generation Architecture (LSGA), l’architecture de référence du générateur de scénarios de LOTUSim.

LSGA définit les principes, les composants, les modèles de données, les interfaces et les décisions architecturales permettant de transformer une description de mission en un scénario exécutable dans l’environnement de simulation LOTUSim.

Cette architecture vise à fournir un cadre stable, extensible et indépendant des technologies sous-jacentes afin de faciliter l’évolution du générateur de scénarios, l’intégration de nouveaux moteurs de planification et le développement de nouvelles capacités de simulation.

Le document constitue la référence technique du projet et a vocation à être maintenu tout au long du cycle de vie de LOTUSim.


### 1.2 Contexte

LOTUSim est une plateforme de simulation destinée à l’étude, au développement et à l’évaluation de systèmes navals autonomes et collaboratifs.

Le générateur de scénarios constitue l’une des briques centrales de la plateforme. Il permet de produire automatiquement des scénarios cohérents à partir de différentes sources, telles qu’une description en langage naturel, une saisie experte ou une bibliothèque de scénarios existants.

Ces scénarios sont ensuite exécutés dans l’environnement de simulation de LOTUSim afin d’évaluer des architectures de systèmes, des algorithmes, des capteurs ou des concepts opérationnels.

La première version de LSGA cible principalement des scénarios navals multi-agents reposant sur une planification hiérarchique.


### 1.3 Objectifs

LSGA poursuit les objectifs suivants :

- fournir une architecture unique pour la génération de scénarios dans LOTUSim ;
- séparer explicitement la connaissance métier (doctrine) de l’instanciation des scénarios ;
- permettre la génération de scénarios à partir de multiples sources (LLM, expert, bibliothèque de scénarios) ;
- garantir la reproductibilité, la traçabilité et le versionnement des scénarios générés ;
- permettre le remplacement des moteurs de planification avec un impact minimal sur le reste de l’architecture ;
- maintenir une séparation claire entre le raisonnement symbolique et la simulation physique ;
- fournir une base logicielle pérenne pour les futurs développements de LOTUSim et les travaux de recherche associés.

### 1.4 Périmètre

LSGA couvre exclusivement la génération, la planification et la préparation à l’exécution des scénarios.

Le périmètre comprend notamment :

- la représentation des demandes de scénarios ;
- la validation des scénarios avant planification ;
- la construction du modèle de planification ;
- la planification hiérarchique ;
- la transformation du plan en graphe d’exécution ;
- la préparation de l’exécution dans LOTUSim.
En revanche, les éléments suivants sont considérés comme hors du périmètre de LSGA :

- les modèles physiques ;
- les modèles environnementaux ;
- les modèles de capteurs ;
- les algorithmes embarqués dans les plateformes ;
- la coordination réactive pendant l’exécution ;
- l’optimisation continue des trajectoires ;
- l’exécution distribuée de la simulation.
Ces fonctions appartiennent à l’environnement d’exécution de LOTUSim.


### 1.5 Public visé

Ce document s’adresse :

- aux architectes logiciels de LOTUSim ;
- aux développeurs contribuant au générateur de scénarios ;
- aux doctorants, stagiaires et chercheurs travaillant sur la planification ou les systèmes autonomes ;
- aux partenaires industriels et académiques impliqués dans l’évolution de LOTUSim.
Il constitue également le document de référence pour toute évolution de l’architecture du générateur de scénarios.


### 1.6 Principes d’architecture

Les choix décrits dans ce document reposent sur les principes suivants.

P1 — Séparation des responsabilités

Chaque composant possède une responsabilité unique et clairement définie. La génération de scénarios, la planification, l’exécution et la simulation sont découplées afin de limiter les dépendances entre modules.

P2 — Source unique de vérité

Chaque information possède une unique source de vérité.

En particulier :

- le Domain HDDL constitue la référence de la doctrine opérationnelle ;
- le Problem HDDL constitue la référence de l’état symbolique d’un scénario ;
- le Planning Model constitue la représentation officielle transmise au moteur de planification ;
- le Execution Graph constitue la représentation officielle du scénario exécutable ;
- le LOTUSim Execution Environment constitue l’unique source de vérité concernant le monde simulé.
Cette règle évite la coexistence de représentations concurrentes d’une même réalité.

P3 — Découplage par adaptation

LSGA isole les systèmes externes au moyen de composants dédiés d’adaptation.

Le World Abstraction Layer (WAL) assure la transition entre le monde simulé et le modèle symbolique utilisé pour la planification.

Le Execution Adaptation Layer (EAL) assure la transition entre le résultat du moteur de planification et le modèle d’exécution utilisé par LOTUSim.

Cette organisation limite le couplage entre les composants internes de LSGA et les technologies externes.

P4 — Reproductibilité

À domaine, problème et configuration identiques, LSGA doit produire un résultat reproductible.

Cette propriété est essentielle pour les campagnes de tests, les benchmarks et les travaux de recherche.

P5 — Validation systématique

Toute information produite automatiquement, notamment par un LLM, est considérée comme non fiable tant qu’elle n’a pas été validée.

La validation constitue une étape obligatoire du pipeline.

P6 — Séparation entre raisonnement symbolique et simulation

Le moteur de planification raisonne exclusivement sur une représentation symbolique du monde.

La simulation physique, les modèles environnementaux et les modèles de perception restent de la responsabilité du LOTUSim Execution Environment.

Cette séparation garantit que la doctrine opérationnelle demeure indépendante des modèles physiques utilisés.

P7 — Extensibilité

LSGA est conçu pour permettre l’ajout de nouveaux types de missions, de plateformes, de moteurs de planification ou de moteurs de simulation sans remise en cause des principes fondamentaux de l’architecture.


### 1.7 Structure du document

Le reste du document est organisé comme suit :

- Chapitre 2 – Vue d’ensemble de l’architecture.
- Chapitre 3 – Architecture logicielle et composants.
- Chapitre 4 – Modèle conceptuel et transformations de modèles.
- Chapitre 5 – Décisions d’architecture.
- Chapitre 6 – Contrats des composants.
- Chapitre 7 – Validation, vérification et évaluation.
- Chapitre 8 – Limites et perspectives.
- Chapitre 9 – Roadmap.
- Annexes – Glossaire, acronymes, conventions, références et éléments en cours de définition.

## 2. Vue d’ensemble de l’architecture


### 2.1 Objectif

La LOTUSim Scenario Generation Architecture (LSGA) transforme une description de mission en un scénario exécutable par LOTUSim.

Cette transformation est réalisée par une succession de composants spécialisés, chacun manipulant un niveau d’abstraction spécifique.

L’architecture repose sur trois principes fondamentaux :

- la séparation des responsabilités, chaque composant assurant une fonction unique ;
- la séparation des représentations, chaque étape manipulant un modèle adapté à son niveau d’abstraction ;
- le découplage des systèmes externes, réalisé au travers de couches d’adaptation dédiées.
Cette organisation permet de faire évoluer indépendamment le moteur de planification, l’environnement de simulation ou les interfaces utilisateur sans remettre en cause l’architecture globale.


### 2.2 Vue d’ensemble

Le pipeline complet de génération de scénarios est présenté Figure 2-1.

Figure 2-1 — Vue d’ensemble de LSGA

                                   SYSTÈMES EXTERNES
┌──────────────────────────────────────────────────────────────────────────────┐
│                                                                              │
│  LLM          Expert          Banque de scénarios                            │
│                                                                              │
└──────────────────────────────┬───────────────────────────────────────────────┘
                               │
                               ▼
                    ╔══════════════════════╗
                    ║ Validation            ║
                    ╚══════════════════════╝
                               │
                               ▼
                    ╔══════════════════════╗
                    ║ World Abstraction     ║
                    ║ Layer (WAL)           ║
                    ╚══════════════════════╝
                               │
                               ▼
                  ( Planning Model )
               Domain HDDL + Problem HDDL
                               │
                               ▼
                    ╔══════════════════════╗
                    ║ Planning Engine      ║
                    ║ Wrapper              ║
                    ╚══════════════════════╝
                               │
                               ▼
                 ( Raw Planning Result )
                               │
                               ▼
                    ╔══════════════════════╗
                    ║ Execution            ║
                    ║ Adaptation Layer     ║
                    ║ (EAL)                ║
                    ╚══════════════════════╝
                               │
                               ▼
                    ( Execution Graph )
                               │
                               ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│               LOTUSim Execution Environment                                  │
│      (Simulation, physique, capteurs, exécution, état du monde)              │
└──────────────────────────────────────────────────────────────────────────────┘
Convention graphique utilisée dans l’ensemble du document


| Élément | Convention |
|---|---|
| Composant LSGA | Rectangle à bord épais |
| Artefact / Modèle | Rectangle à coins arrondis |
| Système externe | Grand rectangle englobant |
| Flux de données | Flèche pleine |

Cette convention sera utilisée dans tous les diagrammes du document afin de distinguer clairement les composants logiciels des représentations manipulées.


### 2.3 Les grandes phases

Le pipeline LSGA est constitué de cinq phases principales.

Phase 1 — Acquisition

Une mission peut provenir de plusieurs sources :

- une description en langage naturel interprétée par un LLM ;
- une saisie experte ;
- une bibliothèque de scénarios ;
- un générateur automatique.
Toutes convergent vers une représentation commune indépendante de leur origine.

Phase 2 — Construction du modèle de planification

Après validation, le World Abstraction Layer construit le Planning Model.

Cette étape consiste à transformer une description métier en une représentation symbolique exploitable par le planificateur.

Le WAL réalise notamment :

- la construction du Problem HDDL ;
- la traduction des informations issues du monde simulé en prédicats symboliques ;
- la vérification de la cohérence du modèle obtenu.
Le Domain HDDL est quant à lui fourni par le référentiel officiel de LOTUSim et n’est jamais modifié par cette étape.

Phase 3 — Planification

Le Planning Engine Wrapper encapsule le moteur de planification choisi.

Il reçoit le Planning Model et produit un Raw Planning Result.

Cette architecture permet de remplacer le moteur de planification sans impact sur le reste de LSGA.

Phase 4 — Construction du modèle d’exécution

Le Execution Adaptation Layer transforme le résultat brut du planificateur en un Execution Graph.

Ce graphe constitue le contrat d’exécution entre LSGA et LOTUSim.

Il est totalement indépendant du moteur de planification utilisé.

Phase 5 — Exécution

Le LOTUSim Execution Environment exécute le scénario.

Il est responsable :

- de la simulation physique ;
- des modèles de plateformes ;
- des modèles de capteurs ;
- de la gestion de l’état du monde ;
- de la coordination avec les différents moteurs de simulation.
Les responsabilités détaillées de ce composant seront précisées en collaboration avec l’architecture globale de LOTUSim (voir TODO Architecture).


### 2.4 Les représentations manipulées

L’une des caractéristiques principales de LSGA est qu’il manipule successivement plusieurs représentations d’un même scénario.


| Représentation | Description | Responsable |
|---|---|---|
| Scenario Request | Description structurée d’une mission | Validation |
| Planning Model | Modèle de planification (Domain + Problem HDDL) | WAL |
| Raw Planning Result | Résultat brut du moteur de planification | Planning Engine Wrapper |
| Execution Graph | Modèle d’exécution LOTUSim | EAL |
| Simulation State | État courant du monde simulé | LOTUSim Execution Environment |

Chaque représentation possède un objectif spécifique et ne doit jamais être utilisée en dehors de son domaine de responsabilité.


### 2.5 Les flux de données

LSGA manipule exclusivement des flux de données entre composants.

Aucun composant ne dépend directement de l’implémentation interne d’un autre.

Chaque composant échange uniquement des représentations documentées.

Cette organisation permet :

- le remplacement d’un moteur de planification ;
- l’évolution indépendante du monde simulé ;
- le développement parallèle des différents composants ;
- la reproductibilité des scénarios.

### 2.6 Vue logique de l’architecture

LSGA peut être vu comme une chaîne de transformations de représentations.

    Scenario Request
        │
        ▼
Planning Model
        │
        ▼
Raw Planning Result
        │
        ▼
Execution Graph
        │
        ▼
Simulation State
Cette vision constitue le fil conducteur de toute l’architecture.

Chaque composant est responsable d’une unique transformation entre deux représentations.

Cette approche facilite l’extension, le test et la maintenance de l’architecture.


### 2.7 Rationale

L’architecture de LSGA privilégie un découplage fort entre les différentes étapes de la génération de scénarios.

Le moteur de planification n’est jamais exposé directement au monde simulé et ne produit jamais directement un scénario exécutable. De manière symétrique, l’environnement de simulation ne dépend pas du format interne du moteur de planification.

Cette séparation garantit une meilleure modularité, facilite le remplacement des technologies sous-jacentes et permet de faire évoluer indépendamment les différents composants de l’architecture.


## 3. Architecture logicielle


### 3.1 Principes

LSGA est constitué d’un nombre limité de composants logiciels, chacun responsable d’une unique transformation entre deux représentations.

Chaque composant manipule uniquement des représentations documentées et communique avec les autres composants au travers de contrats explicites.

Cette organisation permet de limiter les dépendances entre composants et de faciliter leur évolution indépendante.

La Figure 3-1 présente les composants principaux de LSGA.

(Référence vers la Figure 2-1 ; inutile de dupliquer le diagramme.)


### 3.2 Sources de scénarios

Les sources de scénarios constituent les points d’entrée de LSGA.

L’architecture ne privilégie aucune origine particulière. Une mission peut être décrite par un opérateur, générée automatiquement ou produite par un modèle d’intelligence artificielle.

Toutes ces sources convergent vers une représentation commune appelée Scenario Request.

Responsabilité

Produire une demande de génération de scénario.

Entrées

Aucune.

Sortie

Scenario Request

Dépendances

Aucune.

Description

Les sources actuellement identifiées sont :

- interface utilisateur ;
- LLM ;
- bibliothèque de scénarios ;
- génération automatique ;
- interfaces futures.
Leur évolution est indépendante de l’architecture interne de LSGA.


### 3.3 Validation

La validation constitue la première étape du pipeline.

Son objectif est de détecter les incohérences le plus tôt possible avant toute planification.

Elle garantit que les représentations manipulées par LSGA sont cohérentes avec les règles métier et avec le profil HDDL adopté.

Responsabilité

Garantir la cohérence des demandes de scénario.

Entrée

Scenario Request

Sortie

Scenario Request validée

Dépendances

Profil HDDL LOTUSim.

Description

La validation couvre notamment :

- la cohérence structurelle ;
- les contraintes métier ;
- les capacités des plateformes ;
- la cohérence des paramètres de mission.
Les différents niveaux de validation seront détaillés au Chapitre 7.


### 3.4 World Abstraction Layer (WAL)

Le World Abstraction Layer (WAL) constitue la frontière entre le monde simulé et le modèle symbolique utilisé pour la planification.

Il transforme les informations provenant de l’environnement LOTUSim en une représentation conforme au modèle de planification.

Le WAL représente le seul composant autorisé à construire un Problem HDDL.

Responsabilité

Construire le Planning Model à partir d’une demande validée et des informations disponibles sur le monde simulé.

Entrées

- Scenario Request validée ;
- informations provenant du LOTUSim Execution Environment.
Sorties

- Problem HDDL ;
- Planning Model.
Dépendances

LOTUSim Execution Environment.

Description

Le WAL :

- construit les objets du problème ;
- construit l’état initial ;
- construit le réseau initial de tâches ;
- traduit les informations physiques en prédicats symboliques ;
- applique les conventions du profil HDDL.
Il ne modifie jamais le Domain HDDL.

Remarques

Les règles d’abstraction utilisées par le WAL devront être documentées dans le Contrat d’Abstraction (document séparé).


### 3.5 Domaine HDDL

Le Domain HDDL constitue la formalisation de la doctrine opérationnelle.

Contrairement aux problèmes, il ne dépend d’aucun scénario particulier.

Il est écrit, revu et versionné par les experts métier.

Responsabilité

Décrire les connaissances permanentes du domaine.

Entrées

Aucune.

Sorties

Domain HDDL.

Dépendances

Profil HDDL LOTUSim.

Description

Le domaine contient :

- les types ;
- les prédicats ;
- les tâches ;
- les méthodes HTN ;
- les opérateurs primitifs.
Le domaine constitue le référentiel doctrinal officiel de LOTUSim.


### 3.6 Planning Engine Wrapper

Le Planning Engine Wrapper encapsule le moteur de planification utilisé par LSGA.

Il constitue l’unique point d’accès aux solveurs de planification.

Cette encapsulation permet de remplacer un moteur par un autre sans modifier le reste de l’architecture.

Responsabilité

Calculer un plan à partir d’un Planning Model.

Entrées

Planning Model.

Sorties

Raw Planning Result.

Dépendances

Moteur de planification.

Description

Le composant est notamment responsable :

- du chargement du domaine ;
- du chargement du problème ;
- de l’appel au moteur ;
- de la récupération des résultats ;
- de la traduction des erreurs du moteur vers les erreurs LSGA.
Le moteur retenu pour la première version de référence est pandaPI (sous réserve de validation définitive de la licence).

Remarques

Le Planning Engine Wrapper ne contient aucune logique métier.

Il constitue exclusivement une couche d’encapsulation.


### 3.7 Execution Adaptation Layer (EAL)

Le Execution Adaptation Layer (EAL) transforme la sortie brute du moteur de planification en un modèle d’exécution indépendant du moteur utilisé.

Il constitue la seconde couche d’adaptation de LSGA.

Responsabilité

Construire l’Execution Graph.

Entrées

Raw Planning Result.

Sorties

Execution Graph.

Dépendances

Planning Engine Wrapper.

Description

Le composant :

- interprète la sortie du moteur ;
- construit les dépendances d’exécution ;
- prépare les informations nécessaires à LOTUSim ;
- garantit un format d’exécution stable.
L’EAL ne réalise aucune décision de planification.


### 3.8 LOTUSim Execution Environment

Le LOTUSim Execution Environment représente l’ensemble des composants chargés de l’exécution des scénarios et de la maintenance du monde simulé.

Il constitue un système externe vis-à-vis de LSGA.

Responsabilité

Fournir les services nécessaires à l’exécution des scénarios ainsi que les informations permettant de représenter le monde simulé.

Entrées

À définir.

Sorties

À définir.

Dépendances

Architecture globale LOTUSim.

Description

Le LOTUSim Execution Environment englobe notamment :

- les moteurs de simulation ;
- les modèles physiques ;
- les modèles environnementaux ;
- les modèles de plateformes ;
- les modèles de capteurs ;
- les mécanismes d’exécution distribuée.
Les technologies utilisées pour implémenter ces fonctions (ROS 2, Gazebo, xdyn, etc.) sont considérées comme des détails d’implémentation et ne sont pas figées par LSGA.

TODO Architecture

Responsable : Cyril Moron (Architecte LOTUSim)

Définir précisément :

- le périmètre du LOTUSim Execution Environment ;
- son contrat fonctionnel ;
- ses responsabilités ;
- les flux de données échangés avec LSGA ;
- les interfaces publiques mises à disposition du WAL et de l’Execution Graph.

### 3.9 Rationale

L’organisation retenue repose sur un principe simple : chaque composant est responsable d’une unique transformation entre deux représentations.

Les deux couches d’adaptation (WAL et EAL) isolent le cœur de LSGA des technologies externes. Le Planning Engine Wrapper encapsule quant à lui le moteur de planification afin de garantir son interchangeabilité.

Cette architecture favorise le découplage, facilite les expérimentations avec différents solveurs et limite l’impact des évolutions de l’environnement LOTUSim sur le générateur de scénarios.


## 4. Modèle conceptuel


### 4.1 Philosophie

LSGA repose sur une architecture orientée modèles (Model-Driven Architecture).

Le générateur de scénarios ne manipule pas directement des composants logiciels ou des fichiers, mais une succession de représentations décrivant un même scénario à différents niveaux d’abstraction.

Chaque représentation possède :

- un objectif précis ;
- un responsable unique ;
- un cycle de vie propre ;
- un ensemble d’invariants.
Chaque composant de LSGA est responsable de la transformation d’une représentation vers une autre.

Cette approche permet de découpler les différentes étapes du pipeline, de faciliter les tests unitaires et de garantir l’indépendance des composants.


### 4.2 Les représentations manipulées

LSGA manipule cinq représentations principales.


#### 4.2.1 Scenario Request

Le Scenario Request constitue le point d’entrée logique de LSGA.

Il représente une demande de génération de scénario indépendante de toute technique de planification.

Il décrit notamment :

- le type de mission ;
- les plateformes concernées ;
- les contraintes utilisateur ;
- les paramètres de génération.
Le Scenario Request ne contient aucune information propre au langage HDDL.

Responsable

Validation.

Durée de vie

Jusqu’à la construction du Planning Model.


#### 4.2.2 Planning Model

Le Planning Model constitue la représentation officielle du problème de planification.

Il est composé de deux artefacts complémentaires.

    Planning Model
├── Domain HDDL
└── Problem HDDL
Le Domain HDDL décrit les connaissances permanentes.

Le Problem HDDL décrit une mission particulière.

Cette séparation constitue l’un des principes fondamentaux de LSGA.

Responsable

World Abstraction Layer.

Durée de vie

Jusqu’à la production du plan.


#### 4.2.3 Raw Planning Result

Le Raw Planning Result représente la sortie native du moteur de planification.

Son format dépend directement du moteur utilisé.

Cette représentation n’a pas vocation à être manipulée par les autres composants de LOTUSim.

Elle constitue une représentation transitoire.

Responsable

Planning Engine Wrapper.

Durée de vie

Uniquement pendant la phase de planification.


#### 4.2.4 Execution Graph

L’Execution Graph constitue la représentation officielle d’un scénario exécutable dans LOTUSim.

Il décrit :

- les actions primitives ;
- leurs dépendances ;
- les synchronisations ;
- les affectations aux agents.
Il est totalement indépendant du moteur de planification.

Tous les composants situés après LSGA manipulent exclusivement cette représentation.

Responsable

Execution Adaptation Layer.

Durée de vie

Pendant toute l’exécution du scénario.


#### 4.2.5 Simulation State

Le Simulation State représente l’état courant du monde simulé.

Il comprend notamment :

- les plateformes ;
- les positions ;
- les états internes ;
- les ressources ;
- les observations ;
- les événements.
Cette représentation est maintenue exclusivement par le LOTUSim Execution Environment.

Responsable

LOTUSim Execution Environment.

Durée de vie

Pendant toute la simulation.


### 4.3 Les transformations

Les composants de LSGA réalisent successivement les transformations suivantes.

    Scenario Request
        │
        ▼
Planning Model
        │
        ▼
Raw Planning Result
        │
        ▼
Execution Graph
        │
        ▼
Simulation State
Chaque transformation est réalisée par un composant unique.


| Transformation | Responsable |
|---|---|
| Scenario Request → Planning Model | World Abstraction Layer |
| Planning Model → Raw Planning Result | Planning Engine Wrapper |
| Raw Planning Result → Execution Graph | Execution Adaptation Layer |
| Execution Graph → Simulation State | LOTUSim Execution Environment |

Cette organisation garantit qu’une représentation n’est jamais produite par plusieurs composants simultanément.


### 4.4 Invariants des représentations

Chaque représentation possède des propriétés qui doivent toujours être vérifiées.

Scenario Request

Doit rester :

- indépendant du planificateur ;
- indépendant de HDDL ;
- indépendant de l’environnement de simulation.
Planning Model

Doit toujours être :

- syntaxiquement valide ;
- conforme au profil HDDL LOTUSim ;
- cohérent avec le domaine ;
- indépendant du moteur de planification.
Raw Planning Result

Doit représenter fidèlement la sortie du moteur.

Aucune hypothèse ne doit être faite sur son format interne.

Execution Graph

Doit être :

- indépendant du moteur de planification ;
- directement exécutable ;
- déterministe ;
- versionnable.
Simulation State

Doit représenter l’unique vérité du monde simulé.

Aucun autre composant ne peut maintenir une représentation concurrente.


### 4.5 Le Planning Model

Le Planning Model constitue le cœur du raisonnement symbolique de LSGA.

Il représente le contrat entre le WAL et le Planning Engine Wrapper.

Il est composé de :

- la doctrine (Domain HDDL) ;
- l’instanciation d’un scénario (Problem HDDL).
Cette distinction permet :

- la réutilisation des connaissances ;
- le versionnement indépendant de la doctrine et des scénarios ;
- la reproductibilité des expériences ;
- la comparaison de plusieurs scénarios utilisant une même doctrine.
Le Planning Model constitue ainsi la représentation de référence utilisée pour toute activité de planification dans LSGA.


### 4.6 Le principe de transformation

LSGA adopte une architecture où chaque composant réalise une unique transformation entre deux modèles.

Cette propriété constitue un invariant de l’architecture.

Aucun composant ne réalise simultanément :

- une transformation de modèle ;
- une décision métier ;
- une exécution.
Cette séparation simplifie :

- les tests unitaires ;
- les tests d’intégration ;
- le remplacement d’un composant ;
- la compréhension de l’architecture.

### 4.7 Le principe des couches d’adaptation

Le cœur de LSGA est volontairement isolé des systèmes externes.

Deux couches d’adaptation assurent ce découplage.

Le World Abstraction Layer (WAL) adapte les informations provenant du monde simulé afin de construire le Planning Model.

L’Execution Adaptation Layer (EAL) adapte la sortie du moteur de planification afin de construire l’Execution Graph.

Ces deux composants jouent un rôle architectural symétrique :

- le WAL adapte une représentation externe vers le modèle de planification ;
- l’EAL adapte une représentation propre au moteur vers le modèle d’exécution de LOTUSim.
Le Planning Engine Wrapper constitue le cœur de la chaîne de transformation.

Cette organisation garantit que les évolutions du monde simulé ou du moteur de planification n’ont qu’un impact limité sur le reste de l’architecture.


### 4.8 Rationale

Le choix d’une architecture orientée modèles permet de raisonner indépendamment :

- des technologies employées ;
- des moteurs de planification ;
- des moteurs de simulation.
Il facilite également l’introduction de nouvelles représentations sans remettre en cause les composants existants.

Cette approche offre enfin un cadre particulièrement adapté à la validation, à la reproductibilité des expériences et à la comparaison de différentes implémentations d’un même composant.


## 5. Décisions d’architecture


### 5.1 Choix du paradigme de planification


#### 5.1.1 Contexte

Le premier choix structurant de LSGA concerne le paradigme de planification adopté.

Deux grandes familles étaient envisageables :

- la planification classique orientée objectifs (PDDL) ;
- la planification hiérarchique (HTN).
Le choix du langage de description découle directement de ce premier choix.


#### 5.1.2 Choix retenu

LSGA adopte une planification hiérarchique (HTN) exprimée au moyen du langage HDDL.


#### 5.1.3 Justification

Les opérations navales sont traditionnellement décrites sous forme de doctrines, de procédures et de modes opératoires.

Le raisonnement suivi par un opérateur ne consiste généralement pas à rechercher une suite quelconque d’actions atteignant un objectif final, mais à décomposer progressivement une mission en sous-missions jusqu’à obtenir des actions directement exécutables.

Cette approche correspond naturellement au paradigme HTN.

Par exemple :

    Sécuriser un chenal
        │
        ▼
Rechercher des mines
        │
        ▼
Détecter
        │
        ▼
Classifier
        │
        ▼
Neutraliser
Cette représentation est très proche des processus de planification opérationnelle utilisés dans les états-majors, notamment du Military Decision-Making Process (MDMP) et, plus généralement, des démarches doctrinales OTAN fondées sur la décomposition des missions.

Le choix de HTN permet donc d’exprimer explicitement cette doctrine plutôt que de laisser le planificateur découvrir librement une séquence d’actions.


#### 5.1.4 Pourquoi HDDL ?

Une fois le paradigme HTN retenu, HDDL apparaît comme le langage le plus adapté.

Les principales raisons sont :

- standard ouvert de la communauté HTN ;
- séparation explicite entre domaine et problème ;
- disponibilité de plusieurs moteurs compatibles ;
- format textuel facilement versionnable ;
- validation syntaxique automatique ;
- indépendance vis-à-vis d’un moteur particulier.
LSGA adopte par ailleurs un profil HDDL LOTUSim, définissant le sous-ensemble officiel du langage utilisé dans le projet.


### 5.2 Séparation entre doctrine et scénario

LSGA distingue explicitement :

- les connaissances permanentes ;
- les scénarios.
Les connaissances permanentes sont décrites dans le Domain HDDL.

Les scénarios sont décrits dans le Problem HDDL.

Cette séparation constitue un principe fondamental de l’architecture.

Elle permet :

- le versionnement indépendant ;
- la réutilisation des connaissances ;
- la comparaison de scénarios ;
- la reproductibilité des expérimentations.
Le domaine constitue ainsi le patrimoine doctrinal de LOTUSim.


### 5.3 Positionnement du LLM

Le LLM est considéré comme un outil d’assistance à la génération de scénarios.

Son rôle est volontairement limité.

Il peut :

- interpréter une demande utilisateur ;
- produire un Scenario Request ;
- proposer un Problem HDDL conforme au domaine.
Il ne peut pas :

- modifier la doctrine ;
- créer de nouvelles méthodes HTN ;
- modifier le Domain HDDL.
Cette limitation garantit que la doctrine reste sous le contrôle des experts métier.

Une évolution future pourra permettre à un LLM de proposer des extensions du domaine dans un espace de travail dédié, soumises à validation humaine avant intégration.


### 5.4 Gestion du temps

LSGA distingue clairement :

- le raisonnement symbolique ;
- le temps physique.
Le planificateur ne raisonne pas sur le temps continu.

Les synchronisations nécessaires à la structure du plan sont exprimées sous forme de dépendances causales entre tâches.

Les phénomènes continus (durées réelles, cinématique, propagation, consommation énergétique, etc.) restent de la responsabilité du LOTUSim Execution Environment.

Cette séparation évite la coexistence de plusieurs modèles temporels concurrents.


### 5.5 Gestion des ressources

Les ressources physiques ne sont pas représentées directement dans le Planning Model.

Lorsque ces ressources influencent la structure d’une mission, elles sont abstraites sous forme de prédicats symboliques calculés par le WAL.

Par exemple :

- autonomie suffisante ;
- zone accessible ;
- communication disponible ;
- capteur exploitable.
Le planificateur ne manipule donc jamais directement des valeurs numériques issues de la simulation.


### 5.6 Coordination multi-agent

LSGA adopte une planification globale.

Le planificateur produit un plan unique couvrant l’ensemble des agents impliqués dans le scénario.

Les dépendances entre agents sont représentées directement dans le plan.

En revanche, la coordination réactive (gestion d’aléas, réallocation dynamique, négociation, etc.) reste en dehors de LSGA.

Cette responsabilité appartient au LOTUSim Execution Environment.

Cette séparation permet de conserver un plan global cohérent tout en laissant la simulation gérer les phénomènes dynamiques.


### 5.7 Replanification

En cas d’aléa, LSGA réalise une replanification complète.

Le processus est le suivant :

- capture de l’état courant ;
- construction d’un nouveau Planning Model par le WAL ;
- nouvel appel au Planning Engine Wrapper ;
- génération d’un nouvel Execution Graph ;
- reprise de l’exécution.
Ce choix privilégie la simplicité, la robustesse et la reproductibilité.

Le replanning incrémental est identifié comme une piste de recherche mais ne fait pas partie du périmètre de la première version.


### 5.8 Interchangeabilité du moteur de planification

LSGA ne dépend d’aucun moteur particulier.

Le moteur est entièrement encapsulé par le Planning Engine Wrapper.

La première implémentation de référence s’appuie sur pandaPI, sous réserve de validation définitive de la licence.

Le remplacement ultérieur par un autre moteur ne doit entraîner aucune modification des autres composants de LSGA.


### 5.9 Validation systématique

Toute représentation produite automatiquement est soumise à validation avant utilisation.

La validation fait partie intégrante de l’architecture.

Elle s’applique notamment :

- aux productions du LLM ;
- aux fichiers HDDL ;
- aux résultats du planificateur ;
- aux transformations entre représentations.
Cette décision garantit la robustesse du pipeline.


### 5.10 Architecture orientée modèles

LSGA considère les différentes représentations manipulées comme des modèles successifs décrivant un même scénario.

Les composants de l’architecture réalisent exclusivement des transformations entre ces modèles.

Cette approche permet :

- un découplage fort des composants ;
- une meilleure testabilité ;
- une meilleure traçabilité ;
- une plus grande indépendance vis-à-vis des technologies employées.
Elle constitue l’un des principes structurants de LSGA.


### 5.11 Rationale

Les décisions présentées dans ce chapitre ne résultent pas d’une préférence technologique mais d’une volonté de construire une architecture durable, modulaire et adaptée au contexte naval.

Le choix de HTN/HDDL découle directement de la nature procédurale des doctrines opérationnelles. La séparation stricte entre doctrine, planification et simulation permet de maintenir un découplage fort entre les différents niveaux de responsabilité.

Enfin, l’adoption d’une architecture orientée modèles garantit que les évolutions futures — nouveaux moteurs de planification, nouvelles interfaces utilisateur ou nouveaux environnements de simulation — pourront être intégrées avec un impact limité sur le reste de l’architecture.


## 6. Contrats des composants


### 6.1 Objectif

Les contrats définissent les responsabilités et les garanties fournies par chaque composant de LSGA.

Contrairement aux interfaces d’implémentation, ils ne décrivent pas les mécanismes logiciels utilisés mais les propriétés qui doivent rester vraies indépendamment de l’implémentation.

Ils constituent les engagements architecturaux entre les différents composants de LSGA.


### 6.2 Contrat du World Abstraction Layer (WAL)

Le World Abstraction Layer constitue l’interface entre le monde simulé et le modèle symbolique utilisé pour la planification.

Responsabilité

Construire le Planning Model à partir :

- d’une demande de scénario validée ;
- des informations disponibles sur le monde simulé.
Produit

Le WAL produit exclusivement :

- un Problem HDDL ;
- le Planning Model associé.
Il ne produit jamais directement un plan.

Garanties

Le WAL garantit que :

- un même état du monde produit toujours le même Planning Model ;
- le Problem HDDL est conforme au profil HDDL LOTUSim ;
- les prédicats générés appartiennent au domaine officiel ;
- le Domain HDDL n’est jamais modifié ;
- le Planning Model est indépendant du moteur de planification.
Ne garantit pas

Le WAL ne garantit pas :

- qu’un plan existe ;
- qu’un scénario est réalisable ;
- qu’une mission est optimale.
Ces propriétés relèvent du moteur de planification.

Dépendances

Le WAL dépend uniquement :

- du contrat du LOTUSim Execution Environment ;
- du profil HDDL LOTUSim.

### 6.3 Contrat du Planning Engine Wrapper

Le Planning Engine Wrapper encapsule le moteur de planification.

Il constitue le seul composant autorisé à invoquer un solveur HTN.

Responsabilité

Transformer un Planning Model en Raw Planning Result.

Produit

Le Planning Engine Wrapper produit exclusivement :

- un Raw Planning Result.
Garanties

Le composant garantit :

- qu’il ne modifie jamais le Planning Model ;
- qu’il ne modifie jamais le Domain HDDL ;
- qu’il encapsule complètement le moteur utilisé ;
- que les erreurs du moteur sont traduites vers des erreurs LSGA.
Ne garantit pas

Le composant ne garantit pas :

- l’existence d’un plan ;
- l’optimalité du résultat ;
- les performances du moteur.
Ces propriétés dépendent du solveur utilisé.

Dépendances

Le composant dépend uniquement :

- du contrat du moteur de planification.

### 6.4 Contrat du Execution Adaptation Layer (EAL)

L’Execution Adaptation Layer transforme la représentation produite par le moteur en modèle d’exécution LOTUSim.

Responsabilité

Construire l’Execution Graph.

Produit

Le composant produit exclusivement :

- un Execution Graph.
Garanties

L’EAL garantit :

- l’indépendance du format vis-à-vis du moteur de planification ;
- la conservation des dépendances causales ;
- la conservation des affectations des tâches ;
- la production d’un graphe directement exploitable par LOTUSim.
Ne garantit pas

L’EAL ne réalise :

- aucune décision métier ;
- aucune optimisation ;
- aucune replanification.
Il adapte uniquement les représentations.

Dépendances

Le composant dépend uniquement :

- du contrat du Planning Engine Wrapper.

### 6.5 Contrat du LOTUSim Execution Environment

Le LOTUSim Execution Environment constitue un système externe vis-à-vis de LSGA.

Son contrat détaillé relève de l’architecture globale de LOTUSim et n’est donc pas figé dans le présent document.

LSGA considère uniquement les services exposés par cet environnement.

Responsabilité

Assurer l’exécution des scénarios et maintenir la représentation du monde simulé.

Produit

À définir avec l’architecture LOTUSim.

Garanties

À définir avec l’architecture LOTUSim.

Dépendances

Architecture globale LOTUSim.

TODO Architecture

Responsable : Cyril Moron — Architecte LOTUSim

Définir :

- le périmètre fonctionnel du LOTUSim Execution Environment ;
- les services mis à disposition de LSGA ;
- les informations accessibles au WAL ;
- les informations consommées par l’Execution Graph ;
- les contrats d’échange entre LSGA et LOTUSim.
Le présent document considère volontairement le LOTUSim Execution Environment comme une boîte noire afin de préserver le découplage entre les deux architectures.


### 6.6 Contrats transverses

Les contrats précédents sont complétés par un ensemble de règles communes applicables à l’ensemble des composants.

Déterminisme

À entrées identiques, un composant doit produire une sortie identique.

Cette propriété garantit la reproductibilité des expériences.

Immutabilité des représentations

Une représentation produite par un composant ne peut être modifiée par un composant aval.

Par exemple :

- le WAL ne modifie jamais le Domain HDDL ;
- le Planning Engine Wrapper ne modifie jamais le Planning Model ;
- l’EAL ne modifie jamais le Raw Planning Result.
Cette règle garantit la traçabilité des transformations.

Versionnement

Chaque représentation possède un identifiant de version.

Une version comprend notamment :

- l’identifiant du scénario ;
- la version du Domain HDDL ;
- la version du profil HDDL ;
- la version du moteur de planification ;
- la version de LSGA.
Cette information permet de reproduire exactement une génération de scénario.

Gestion des erreurs

Les composants ne propagent jamais directement des erreurs issues de bibliothèques externes.

Chaque erreur est traduite vers une erreur appartenant au modèle d’erreurs de LSGA.

Cette règle garantit l’indépendance vis-à-vis des implémentations.

Journalisation

Chaque transformation de représentation doit être journalisée.

Les journaux doivent permettre de reconstituer intégralement la chaîne de génération d’un scénario.

Cette propriété est essentielle pour :

- le débogage ;
- les campagnes de benchmark ;
- les travaux de recherche.

### 6.7 Matrice des responsabilités

Afin de synthétiser les contrats précédents, le Tableau 6-1 récapitule les responsabilités des principaux composants.


| Composant | Produit | Responsable de | Ne fait jamais |
|---|---|---|---|
| WAL | Planning Model | Construire le modèle de planification | Planifier |
| Planning Engine Wrapper | Raw Planning Result | Encapsuler le moteur | Modifier le modèle |
| EAL | Execution Graph | Construire le modèle d’exécution | Planifier |
| LOTUSim Execution Environment | Simulation State | Exécuter le scénario | Modifier le Planning Model |

Ce tableau constitue un résumé opérationnel de l’architecture et pourra servir de référence lors du développement des différents composants.


### 6.8 Rationale

LSGA privilégie une architecture fondée sur des contrats plutôt que sur des dépendances d’implémentation.

Cette approche présente plusieurs avantages :

- elle facilite le remplacement d’un composant sans impact sur les autres ;
- elle permet de développer les composants en parallèle ;
- elle simplifie les tests d’intégration ;
- elle favorise une séparation claire des responsabilités.
Les contrats constituent ainsi le principal mécanisme de découplage de LSGA.


## 7. Validation, vérification et évaluation


### 7.1 Objectif

L’objectif de cette section est de définir la stratégie de qualité associée à LSGA.

Cette stratégie poursuit quatre objectifs :

- garantir la cohérence des représentations manipulées par LSGA ;
- détecter les erreurs le plus tôt possible dans le pipeline ;
- assurer la reproductibilité des scénarios générés ;
- permettre une évaluation objective de l’architecture.
La validation fait partie intégrante de l’architecture et ne constitue pas une étape optionnelle.


### 7.2 Stratégie générale

LSGA distingue trois activités complémentaires :


| Activité | Question |
|---|---|
| Vérification | Le composant respecte-t-il son contrat ? |
| Validation | Le scénario répond-il au besoin utilisateur ? |
| Évaluation | Les performances et la qualité sont-elles satisfaisantes ? |

Cette distinction sera utilisée dans tout le projet.


### 7.3 Vérification

La vérification consiste à démontrer que chaque composant respecte les contrats définis au Chapitre 6.

Chaque transformation de représentation doit être vérifiable indépendamment des autres composants.

Les principaux niveaux de vérification sont les suivants.

Vérification structurelle

Vérifie notamment :

- présence des informations obligatoires ;
- cohérence des identifiants ;
- cohérence des références.
Vérification syntaxique

Vérifie :

- conformité au profil HDDL ;
- validité du Domain HDDL ;
- validité du Problem HDDL.
Vérification des contrats

Chaque composant doit respecter les garanties définies dans son contrat.

Par exemple :

- le WAL ne modifie jamais le Domain HDDL ;
- l’EAL ne réalise jamais de planification ;
- le Planning Engine Wrapper encapsule complètement le moteur.
Vérification des transformations

Chaque transformation doit préserver les propriétés attendues.

Par exemple :

- conservation des affectations ;
- conservation des dépendances causales ;
- absence de perte d’information non justifiée.

### 7.4 Validation métier

La validation consiste à vérifier que le scénario obtenu répond bien à l’intention initiale.

Elle est réalisée à partir de critères métier.

Quelques exemples :

- la mission demandée est bien réalisée ;
- les plateformes sélectionnées sont cohérentes ;
- les contraintes opérationnelles sont respectées ;
- les procédures imposées par la doctrine sont suivies.
La validation métier relève principalement des experts opérationnels.


### 7.5 Évaluation

L’évaluation consiste à mesurer objectivement la qualité de LSGA.

Elle s’appuie sur une campagne de benchmarks reproductibles.

Les objectifs principaux sont :

- mesurer les performances ;
- mesurer la robustesse ;
- mesurer la montée en charge ;
- comparer différentes implémentations.
Indicateurs

Les indicateurs actuellement envisagés comprennent notamment :

Performances

- temps de génération ;
- temps de planification ;
- temps de transformation.
Scalabilité

- nombre de plateformes ;
- nombre d’objets ;
- taille du domaine ;
- taille du problème.
Qualité des scénarios

- taux de succès de la planification ;
- respect des contraintes métier ;
- reproductibilité.
Robustesse

- comportement face à des données incomplètes ;
- comportement face à des scénarios impossibles ;
- comportement en cas de replanification.

### 7.6 Benchmark Suite

La Benchmark Suite constitue un livrable indépendant de LSGA.

Elle fera l’objet d’un document spécifique.

Ce document décrira notamment :

- les scénarios de référence ;
- les jeux de données ;
- les métriques ;
- les protocoles expérimentaux ;
- les résultats attendus.
Le présent document ne définit que les principes généraux de cette stratégie.

TODO

Une fois l’ontologie stabilisée, une première version de la LSGA Benchmark Suite sera construite.

Les benchmarks devront couvrir l’ensemble des concepts définis dans l’ontologie et les principales familles de missions supportées par LOTUSim.


### 7.7 Traçabilité

Chaque génération de scénario doit être entièrement reproductible.

À cette fin, les informations suivantes devront être conservées :

- identifiant du scénario ;
- version du Domain HDDL ;
- version du Problem HDDL ;
- version du profil HDDL ;
- version de LSGA ;
- version du moteur de planification ;
- paramètres de génération.
Cette traçabilité permet :

- le débogage ;
- les campagnes de benchmark ;
- la comparaison entre versions ;
- les publications scientifiques.

### 7.8 Journalisation

Chaque transformation réalisée par LSGA doit être journalisée.

Les journaux doivent permettre de reconstruire intégralement le pipeline de génération.

Ils doivent notamment enregistrer :

- les représentations manipulées ;
- les erreurs rencontrées ;
- les temps d’exécution ;
- les versions utilisées.

### 7.9 Roadmap qualité

La stratégie qualité sera enrichie progressivement.

Les évolutions prévues comprennent notamment :

- une campagne automatisée de tests de non-régression ;
- une Benchmark Suite publique ;
- des jeux de scénarios de référence ;
- une intégration continue dédiée à la validation des domaines HDDL ;
- des comparaisons entre moteurs de planification.

### 7.10 Rationale

La qualité d’un générateur de scénarios ne peut être évaluée uniquement au travers de son moteur de planification.

Elle dépend de l’ensemble de la chaîne de transformation, depuis la formulation initiale d’une mission jusqu’au scénario effectivement exécuté.

LSGA adopte donc une stratégie de qualité couvrant simultanément :

- la vérification des composants ;
- la validation des scénarios ;
- l’évaluation globale de l’architecture.
Cette approche permet de garantir la robustesse, la reproductibilité et l’évolutivité du système.


## 8. Limites et perspectives


### 8.1 Objectif

Cette section recense les limites actuellement connues de LSGA.

Certaines résultent de choix d’architecture assumés afin de privilégier la simplicité, la robustesse ou la modularité de la première version.

D’autres constituent des pistes d’évolution identifiées pour les versions futures.


### 8.2 Limites actuelles

Temps continu

Le moteur de planification ne raisonne pas sur le temps continu.

Les phénomènes physiques (durées, cinématique, propagation, consommation énergétique, etc.) sont gérés exclusivement par le LOTUSim Execution Environment.

Cette séparation est volontaire afin de maintenir un découplage entre raisonnement symbolique et simulation physique.

Gestion des ressources

Les ressources sont représentées uniquement sous forme symbolique lorsque cela est nécessaire à la structure du plan.

Les modèles numériques détaillés restent hors du périmètre de LSGA.

Replanification

La première version repose exclusivement sur une replanification complète.

Le plan courant est abandonné puis entièrement régénéré à partir de l’état courant du monde.

Cette approche privilégie :

- la simplicité ;
- la robustesse ;
- la reproductibilité.
Coordination distribuée

La coordination réactive entre agents n’est pas réalisée par LSGA.

Les comportements locaux restent de la responsabilité du LOTUSim Execution Environment.

Dépendance au domaine

La qualité des scénarios produits dépend directement de la qualité du Domain HDDL.

Le générateur ne peut produire que des comportements explicitement représentés dans la doctrine.


### 8.3 Perspectives

Les principales évolutions envisagées sont :

- prise en charge de plusieurs moteurs de planification ;
- support de plusieurs domaines doctrinaux ;
- comparaison automatique de solveurs ;
- assistance à la conception de domaines HDDL ;
- validation automatique des domaines ;
- benchmark continu.

### 8.4 Pistes de recherche

Les travaux de recherche identifiés comprennent notamment :

- replanning incrémental ;
- apprentissage automatique de méthodes HTN ;
- hybridation HTN + planification temporelle ;
- génération automatique de doctrines ;
- explication des plans générés ;
- interaction homme-planificateur.
Ces travaux ne remettent pas en cause les principes fondamentaux de LSGA.


### 8.5 Rationale

Les limites identifiées dans cette section ne sont pas des insuffisances de l’architecture mais des choix visant à maintenir un périmètre maîtrisé pour une première version.

La modularité de LSGA permettra d’introduire progressivement ces capacités sans remettre en cause les fondations de l’architecture.


## 9. Roadmap


### 9.1 Vision

LSGA est conçu comme une architecture évolutive.

La feuille de route est organisée autour de plusieurs livrables successifs, chacun apportant une brique structurante à l’écosystème LOTUSim.


### 9.2 Roadmap documentaire

LSGA v2

Architecture de référence du générateur de scénarios.

Statut : en cours de rédaction.

LOTUSim Naval Ontology v1.0

Définition des concepts fondamentaux du domaine naval.

Cette ontologie constitue le socle sémantique de l’ensemble des développements futurs.

LOTUSim Mission Catalog

Catalogue structuré des familles de missions supportées par LOTUSim.

Ce document permettra de relier l’ontologie aux scénarios opérationnels.

HDDL Profile

Définition du sous-ensemble officiel de HDDL utilisé dans LOTUSim.

Ce profil garantira la portabilité entre moteurs.

Naval Domain

Formalisation de la doctrine opérationnelle sous forme de Domain HDDL.

Benchmark Suite

Jeu de scénarios de référence permettant d’évaluer objectivement les performances de LSGA.


### 9.3 Roadmap logicielle

Étape 1

Prototype minimal.

- premier Domain HDDL ;
- WAL simplifié ;
- intégration de pandaPI ;
- premier Execution Graph.
Étape 2

Premier démonstrateur opérationnel.

- missions multi-agents ;
- benchmark initial ;
- validation métier.
Étape 3

Industrialisation.

- intégration continue ;
- benchmark automatisé ;
- comparaison de solveurs ;
- amélioration des performances.

### 9.4 Vision à long terme

À terme, LSGA a vocation à devenir le cadre de référence pour l’ensemble de la génération de scénarios de LOTUSim.

L’architecture doit permettre l’intégration de nouveaux paradigmes de planification, de nouvelles interfaces utilisateur et de nouveaux environnements de simulation tout en préservant les principes fondateurs du système.


## Annexes


### Annexe A — Glossaire


| Terme | Définition |
|---|---|
| LSGA | LOTUSim Scenario Generation Architecture. |
| Scenario Request | Description structurée d’une mission, indépendante de toute technique de planification. |
| Planning Model | Représentation officielle du problème de planification, composée du Domain HDDL et du Problem HDDL. |
| Domain HDDL | Formalisation de la doctrine opérationnelle. |
| Problem HDDL | Instanciation d’une mission particulière. |
| Planning Engine Wrapper | Composant encapsulant le moteur de planification. |
| Raw Planning Result | Résultat natif produit par le moteur de planification. |
| Execution Adaptation Layer (EAL) | Composant transformant le résultat brut du planificateur en modèle d’exécution LOTUSim. |
| Execution Graph | Représentation officielle d’un scénario exécutable dans LOTUSim. |
| World Abstraction Layer (WAL) | Composant construisant le Planning Model à partir du monde simulé. |
| LOTUSim Execution Environment | Ensemble des composants responsables de l’exécution des scénarios et du maintien du monde simulé. |
| Profil HDDL LOTUSim | Sous-ensemble officiel de HDDL utilisé par LOTUSim. |


### Annexe B — Documents de référence

Cette architecture s’inscrit dans une famille de documents complémentaires :

    LSGA
    │
├── LOTUSim Naval Ontology
│
├── LOTUSim Mission Catalog
│
├── LOTUSim HDDL Profile
│
├── LOTUSim Naval Domain
│
└── LSGA Benchmark Suite
Chaque document possède un objectif spécifique et constitue un livrable indépendant.


### Annexe C — TODO Architecture

À valider avec l’architecture LOTUSim

Responsable : Cyril Moron (Architecte LOTUSim)

Définir :

- le périmètre fonctionnel du LOTUSim Execution Environment ;
- les responsabilités détaillées de ce composant ;
- les contrats d’échange avec LSGA ;
- les flux de données échangés avec le WAL ;
- les flux de données consommés par l’Execution Graph ;
- les règles de synchronisation avec les moteurs de simulation.

### Annexe D — Évolutions identifiées

Les éléments suivants ne sont pas figés dans la présente version :

- Profil HDDL LOTUSim ;
- structure détaillée du Scenario Request ;
- contrat du LOTUSim Execution Environment ;
- structure interne de l’Execution Graph ;
- stratégie de benchmark ;
- ontologie navale.
Ces éléments feront l’objet de documents dédiés.

