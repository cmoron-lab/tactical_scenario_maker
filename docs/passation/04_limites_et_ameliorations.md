<a id="p4"></a>

# Partie 4 — Limites et améliorations

> **Nature de ce document.** Relecture critique du code tel qu'il existe au
> moment de la rédaction (branche `htn_implementation`), pas une liste de
> vœux. Chaque point ci-dessous a été retrouvé dans le code réel — cité par
> fichier et fonction — et, quand une simple lecture ne suffisait pas à
> trancher, vérifié par un test exécuté en direct (signalé explicitement).
> Rien n'est présenté comme certain sans preuve.
>
> **Convention d'effort.** Faute d'historique de vélocité d'équipe sur ce
> projet, les pistes de correction sont chiffrées en taille de tee-shirt, avec
> un ordre de grandeur en temps pour rester concret :
> **XS** (< 1 h), **S** (quelques heures à une journée), **M** (quelques
> jours), **L** (plus d'une semaine / repense un morceau d'architecture).
> Ces ordres de grandeur sont des estimations de lecture de code, pas des
> engagements.

---

<a id="p4-sommaire"></a>

## Sommaire de la partie

1. [Axe IA : fiabilité du générateur de scénarios](#p4-41)
2. [Axe Modularité](#p4-42)
3. [Axe Optimisation / robustesse](#p4-43)
4. [Tableau récapitulatif, par taille d'effort](#p4-44)
5. [Pièges déjà rencontrés et résolus — à ne pas réintroduire](#p4-45)

---

<a id="p4-41"></a>

## 4.1 — Axe IA : fiabilité du générateur de scénarios

<a id="p4-411"></a>

### 4.1.1 — La « vérification de complétude » ne vérifie rien

**Symptôme.** Un scénario généré par l'IA peut être annoncé « sans erreur » par
l'interface (`issues.missing_tasks` vide) alors même que l'une de ses missions
réelles pointe vers une tâche inexistante ou mal formée dans la base de
connaissances.

**Cause, dans le code.** `bdd/ai_scenario_generator.py::validate_scenario_completeness()`
vérifie `scenario.get("mission", [])` — mais ce champ **scénario-niveau** est
mis à une valeur littérale constante juste avant, dans
`generate_scenario_from_description()` :

```python
# Every acting agent already carries its own resolved mission (set above) —
# this scenario-level field is only a display fallback, never LLM-authored.
mission_list = ["veiller __self__"]
...
scenario = {"name": slug, "agents": agents, "mission": mission_list}
```

`validate_scenario_completeness()` ne regarde **jamais**
`scenario["agents"][nom]["mission"]` (le champ qui contient les *vraies*
missions, une par agent, potentiellement `"reagir_conditions __self__"` ou
n'importe quelle tâche personnalisée). Elle vérifie systématiquement une seule
chaîne fixe, `"veiller __self__"` — et `veiller` existe *toujours* dans la
base de connaissances (c'est l'une des tâches les plus basiques). Le champ
`issues["missing_tasks"]` retourné est donc **structurellement toujours
vide**, quel que soit ce que l'IA a réellement généré.

**Impact.** L'utilisateur peut importer et tenter de lancer un scénario dont
une mission ne se résoudra jamais (précondition irréaliste, token non
résolvable, tâche personnalisée mal construite malgré les gardes-fous
structurels de `_validate_suggested_method`) sans le moindre avertissement de
cette fonction — le seul signal viendrait alors, bien plus tard, d'une erreur
brute au moment de « Calculer plan HTN » ou du lancement réel.

**Piste de correction.** Remplacer cette vérification vacuité par ce que le
bouton « Calculer plan HTN » fait déjà pour un scénario sauvegardé
(`app.py::_compute_plan`) : construire un `state` minimal à partir de
`scenario["agents"]` et appeler réellement
`gtpyhop.find_plan(state, [agent['mission']])` pour **chaque agent**, en
rapportant tout agent dont le plan vaut `False` ou lève une exception — pas
seulement une vérification de nom de tâche, une vérification que le plan se
calcule *effectivement*. Piège à anticiper : cette vérification tournerait
dans le même processus `app.py` que l'appel qui vient d'écrire une éventuelle
nouvelle tâche dans `knowledge_base.json` — sans un appel explicite à
`bdd.tasks_methods.load_kb()` juste avant, elle se heurterait exactement au
piège de fraîcheur documenté en [Partie 3, § 3.1.9](#p3-319), et échouerait à tort sur
toute tâche fraîchement ajoutée par l'IA elle-même. **Taille : S** (la
mécanique de calcul de plan existe déjà et est directement réutilisable ;
l'essentiel du travail est de construire un `state` équivalent à celui
qu'utilise `_compute_plan`, et d'ajouter le rechargement de KB manquant).

<a id="p4-412"></a>

### 4.1.2 — Un seul retry, donc deux appels LLM au maximum

**Symptôme.** Sur une description complexe (plusieurs agents, plusieurs
branches conditionnelles, rôles mixtes), le modèle 7B peut échouer sur les
deux tentatives autorisées et le générateur renvoie `cannot_model` — y compris
pour des scénarios qui seraient modélisables si le LLM les avait mieux
compris.

**Cause, dans le code.** `bdd/ai_scenario_generator.py` :
`MAX_RETRIES = 1`, utilisé dans
`for attempt in range(MAX_RETRIES + 1):` (`_parse_scenario_from_description`)
— deux appels à `_query_ollama` au maximum, quel que soit le nombre de
problèmes détectés au premier essai.

**Impact.** Compromis assumé entre fiabilité et temps de réponse (chaque appel
prend 30 à 90 s d'après `AI_GENERATOR_README.md` et le `timeout=90` de
`_query_ollama`) — mais non mesuré : rien dans le dépôt ne quantifie le taux
de réussite réel à 1 vs 2 vs 3 tentatives sur un jeu de descriptions
représentatif.

**Piste de correction.** Avant de toucher à la constante elle-même, construire
un petit jeu de descriptions de test (voir § 4.1.5) et mesurer le taux de
succès selon le nombre de tentatives — augmenter `MAX_RETRIES` sans données
ne serait qu'un pari sur le temps d'attente utilisateur. **Taille : XS** pour
le changement de constante seul ; **S** pour la mesure qui doit le précéder et
le justifier.

<a id="p4-413"></a>

### 4.1.3 — Le filet déterministe ne couvre qu'une syntaxe rigide

**Symptôme.** Une description qui exprime une logique conditionnelle en prose
libre (sans la forme exacte « si `<condition>` : `<comportement>` ») échappe
entièrement à la détection déterministe des branches et repose alors sur la
seule interprétation du LLM, sans le filet de sécurité qui, pour la syntaxe
reconnue, refuse explicitement plutôt que de deviner.

**Cause, dans le code.** `_GENERIC_BRANCH_LINE_PATTERN` dans
`bdd/ai_scenario_generator.py` :

```python
_GENERIC_BRANCH_LINE_PATTERN = re.compile(
    r'(?:^|[-*]\s*)(?:si|if)\s+([^:\n]+?)\s*:\s*([^\n]+)',
    re.IGNORECASE | re.MULTILINE,
)
```

Cette expression exige un « si »/« if » suivi d'un `:` séparant clairement
condition et comportement, sur une ligne. Une description telle que *« Quand
l'intrus s'approche à moins de 200 mètres, le patrouilleur doit l'intercepter,
sinon il continue sa ronde »* — sémantiquement identique à un « si...  :... »
— ne matche pas ce motif : `_detect_multi_condition_branches` renvoie
`(None, [])`, et le comportement retombe entièrement sur la génération LLM
libre, avec uniquement les vérifications structurelles génériques (comptage
d'agents, validité de mission) pour la rattraper — pas la vérification fine,
clause par clause, que ce détecteur offre pour la syntaxe reconnue.

**Impact.** Fiabilité inégale selon la façon dont l'utilisateur formule sa
description — un utilisateur qui ne connaît pas la syntaxe « si : » attendue
(documentée seulement dans l'aide contextuelle de l'onglet IA) obtient une
garantie plus faible sans le savoir.

**Piste de correction.** Élargir `_GENERIC_BRANCH_LINE_PATTERN` pour capturer
quelques tournures supplémentaires fréquentes (« quand X, Y », « dès que X,
Y », « si X alors Y ») serait un gain rapide mais incomplet par nature (la
prose libre est infinie). Une piste plus robuste : demander explicitement au
LLM, dans un pré-traitement, de reformuler la description en lignes « si :
» avant de lancer la détection déterministe — ce qui déplace le problème
plutôt que de le résoudre (le LLM peut mal reformuler), mais donne au moins un
texte reformulé affichable à l'utilisateur pour validation avant génération.
**Taille : S** pour l'extension du regex (gain partiel, rapide) ; **M** pour
la piste de reformulation assistée (nouveau détour LLM à concevoir et
valider).

<a id="p4-414"></a>

### 4.1.4 — Le comptage d'agents a des angles morts documentables

**Symptôme.** `expected_count` (le seul signal qui active la vérification
déterministe du nombre d'agents produits) reste `None` pour certaines
formulations légitimes, désactivant silencieusement ce garde-fou précis.

**Cause, dans le code.** `_expected_agent_count()` reconnaît deux formes : des
agents numérotés partageant un nom générique (`agent1`, `agent2`… via
`r'\b(?:agent|bateau|drone|usv|navire)[\s_]?(\d+)\b'`) et un compte explicite
suivi d'un nom générique (« deux bateaux », « 3 drones »). Une description qui
nomme les agents par des noms propres arbitraires (« Alpha, Bravo et Charlie
patrouillent la zone ») ne matche ni l'une ni l'autre forme —
`_expected_agent_count` renvoie `None`, et `count_wrong` (la vérification qui
compare le nombre d'agents produits au nombre attendu) ne se déclenche alors
plus jamais pour cette génération : `count_wrong = expected_count is not None and len(acting) != expected_count`.

**Impact.** Sur ce type de formulation, si le LLM oublie un agent ou en
invente un de trop, rien ne le détecte — contrairement au cas « deux
bateaux », où une erreur de comptage du LLM déclenche systématiquement un
second essai avec feedback correctif.

**Piste de correction.** Étendre la détection pour repérer une liste de noms
propres séparés par des virgules/« et » suivie d'un verbe d'action commun
(heuristique plus fragile, faux positifs probables sur des phrases qui ne
sont pas des énumérations d'agents) — à traiter avec prudence, un faux
positif ici *ajoute* une contrainte fausse plutôt que d'en retirer une
vraie. **Taille : M** (nécessite un jeu de descriptions de test pour calibrer
le taux de faux positifs avant activation, pas seulement écrire le regex).

<a id="p4-415"></a>

### 4.1.5 — Zéro test automatisé sur 1704 lignes de logique

**Symptôme.** `bdd/ai_scenario_generator.py` est, de très loin, le fichier le
plus dense en logique du dépôt (comptage regex, détection de branches,
validation structurelle, réparation de tokens, retry avec feedback) — et
`tests/` ne contient qu'un seul fichier, `test_intruder_resolution.py`, qui ne
le teste pas du tout.

**Cause.** Aucune, dans le code — c'est une absence, pas un choix documenté.

**Impact.** Toute modification du prompt, d'un regex ou d'une règle de
validation peut casser silencieusement un cas qui fonctionnait auparavant ; la
seule façon de le savoir aujourd'hui est un test manuel via l'UI, avec Ollama
réellement lancé, ce qui est lent et non reproductible à l'identique (le LLM
n'est pas déterministe malgré la température basse de `0.15`).

**Impact positif à noter, pour cadrer l'effort correctement :** la
**majorité** du fichier est en réalité du code Python pur, sans appel réseau —
`_expected_agent_count`, `_mentions_intruder`, `_mentions_passive_agent`,
`_detect_multi_condition_branches`, `_validate_suggested_method`,
`_repair_suggested_tokens`, `_clamp_coord`, `_normalize_mission`… toutes ces
fonctions ne dépendent que de leur texte d'entrée et sont testables
**immédiatement**, sans mock d'Ollama.

**Piste de correction.** Un premier lot de tests unitaires sur ces fonctions
pures (entrée texte → sortie attendue), sans toucher au réseau, couvrirait
déjà l'essentiel du risque de régression silencieuse. Un second lot, plus
coûteux, testerait le pipeline complet avec `_query_ollama` mocké (réponses
JSON enregistrées une fois, format « cassette », rejouées en boucle) pour
couvrir `_parse_scenario_from_description` et le mécanisme de retry sans
dépendre d'Ollama à chaque exécution de `pytest`. **Taille : M** pour le
premier lot (fonctions pures, un ou deux jours) ; **M** supplémentaire pour le
second lot (mock/cassettes du LLM, machinerie à construire).

<a id="p4-416"></a>

### 4.1.6 — Un plafond structurel, pas un bug : validation syntaxique, jamais sémantique

**À noter explicitement, pour cadrer les attentes du repreneur** : toutes les
vérifications décrites dans cette section (comptage, validité de mission,
tokens reconnus, structure des méthodes suggérées) sont **structurelles** — «
est-ce que ça va planter » — jamais **sémantiques** — « est-ce que ça fait
réellement ce que l'utilisateur a demandé ». Rien dans l'architecture actuelle
ne peut garantir qu'un scénario syntaxiquement valide correspond à l'intention
tactique décrite ; par exemple, rien n'empêche structurellement le LLM
d'assigner « eviter » à un agent alors que la description voulait clairement
« encercler » — les deux missions sont également valides pour la structure
du générateur, avec les mêmes exigences (`conditions.cible`, pas besoin de
rôle « intruder »).

Ce n'est pas un défaut réparable par un correctif ponctuel : c'est la limite
inhérente d'un modèle 7B local associé à des vérifications structurelles.
L'atténuation réaliste n'est pas dans le code du générateur, mais dans le
**processus** — le pipeline actuel encourage déjà ceci (l'écran de
prévisualisation avant import, [Partie 2](#p2)), mais rien ne le rend obligatoire. Une
piste concrète et peu coûteuse : appeler « Calculer plan HTN » **automatiquement**
sur le scénario généré avant même de le présenter à l'utilisateur (en
réutilisant le correctif de § 4.1.1), et **afficher le plan résultant** en
plus des seuls warnings texte — donner à l'utilisateur de quoi juger le
comportement réel, pas seulement la structure. **Taille : S**, une fois § 4.1.1
en place.

---

<a id="p4-42"></a>

## 4.2 — Axe Modularité

<a id="p4-421"></a>

### 4.2.1 — L'interface tient dans un unique fichier de ~2670 lignes

**Symptôme.** `templates/index.html` mélange HTML, CSS et JavaScript dans un
seul fichier. Toute modification de l'UI — même minime — touche ce même
fichier, quelle que soit la partie concernée (éditeur de scénario, éditeur de
KB, onglet IA).

**Cause.** Choix délibéré, documenté en [Partie 1 § 1.5](#p1-15) : zéro dépendance,
zéro étape de build, déployable sur n'importe quelle machine avec juste
Python. Ce n'est pas un oubli — c'est un compromis assumé dont le prix est
maintenant à chiffrer.

**Impact concret, observable dans ce dépôt même** : le diff non committé au
moment de la rédaction touche `templates/index.html` en même temps que
`bdd/ai_scenario_generator.py` et `bdd/knowledge_base.json`, sur des
préoccupations pourtant différentes (documentation UI d'un côté, logique IA de
l'autre) — un seul fichier géant augmente mécaniquement la probabilité de
conflits de fusion Git dès que deux changements simultanés touchent l'UI,
même pour des raisons sans rapport.

**Piste de correction, qui préserve la philosophie « zéro dépendance ».**
Scinder au minimum le CSS et le JS dans des fichiers statiques séparés
(`static/style.css`, `static/app.js`), servis par une route statique simple
ajoutée à `app.py::Handler` (quelques lignes, pas de nouvelle dépendance).
Pour aller plus loin sans introduire de bundler, découper le JavaScript en
modules ES natifs (`<script type="module">`, `import`/`export` supportés
nativement par tous les navigateurs modernes depuis longtemps, aucune
compilation nécessaire) — par exemple un module par onglet
(`scenarios.js`, `kb.js`, `ia.js`) plus un module d'utilitaires partagés.
**Taille : S** pour la séparation CSS/JS en fichiers statiques simples ;
**M** pour le découpage en modules ES (implique de vérifier soigneusement
tous les points de couplage implicite actuels, par exemple `kbData` utilisé
comme variable globale partagée entre plusieurs fonctions aujourd'hui
adjacentes dans le même fichier).

<a id="p4-422"></a>

### 4.2.2 — Aucun fichier de dépendances

**Symptôme.** Aucun `requirements.txt`, `pyproject.toml`, `setup.py` ni
`Pipfile` dans le dépôt.

**Cause.** Absence, constatée dans l'arborescence entière — pas un choix
documenté.

**Impact.** La seule dépendance PyPI réelle du projet, `requests` (utilisée
par `bdd/ai_scenario_generator.py` pour parler à Ollama en HTTP), n'est
déclarée nulle part formellement. Un nouveau poste de développement ne peut
pas faire `pip install -r requirements.txt` ; la reproductibilité de
l'environnement repose entièrement sur la mémoire de la personne qui l'a
installé. (Les dépendances ROS — `rclpy`, `geographic_msgs`, `lotusim_msgs` —
ne sont de toute façon pas installables par pip : elles viennent du workspace
ROS 2 externe et devraient être documentées séparément, pas dans ce fichier.)

**Piste de correction.** Un `requirements.txt` d'une ligne
(`requests>=2.25`) réglerait déjà l'essentiel. **Taille : XS** — l'un des
correctifs les moins coûteux de tout ce document.

<a id="p4-423"></a>

### 4.2.3 — Accumulation non maîtrisée des tâches générées par l'IA

**Symptôme.** Chaque génération IA qui produit un `suggested_methods` (ou une
branche `reagir_conditions` déterministe) ajoute une tâche à
`bdd/knowledge_base.json`, sans jamais rien fusionner de similaire ni marquer
ce qui vient de l'IA par opposition aux tâches de référence.

**Cause, dans le code.** `bdd/ai_scenario_generator.py::_enrich_kb_with_methods()` :

```python
tasks = kb.setdefault("tasks", {})
is_new_task = task_name not in tasks
task_def = tasks.setdefault(task_name, {"label": ..., "methods": []})
```

La déduplication ne se fait que **par nom exact de tâche** — si le LLM choisit
`reagir_conditions` deux fois pour deux descriptions différentes, les méthodes
s'accumulent proprement dans une seule tâche (c'est le cas normal,
fonctionnel). Mais si le LLM nomme différemment deux besoins pourtant proches
(par exemple `reagir_menace` puis `reagir_danger` sur deux générations
successives), rien ne les rapproche : deux tâches quasi-redondantes
apparaissent dans la base. De plus, **aucune suppression automatique** n'est
jamais déclenchée — `app.py::delete_scenario` retire uniquement le fichier de
scénario (`os.remove(path)`), jamais les tâches KB que ce scénario utilisait ;
une tâche générée par l'IA reste dans `knowledge_base.json` indéfiniment, même
si plus aucun scénario ne la référence. (La suppression manuelle, elle,
existe bel et bien — bouton « Supprimer la tâche » de l'onglet Connaissances
HTN — mais rien ne guide l'utilisateur vers ce qui est sûr ou utile à
supprimer.)

**Impact.** La base de connaissances grossit de façon monotone avec l'usage
du générateur IA. À terme, l'onglet Connaissances HTN se remplit de tâches à
usage unique, rendant plus difficile pour l'expert métier de distinguer les
tâches de référence (les 8 missions + les tâches feuilles) des tâches
générées ponctuellement — l'inverse de l'objectif d'accessibilité de la
[Partie 1, § 1.2](#p1-12).

**Piste de correction.** Deux mesures indépendantes et cumulables : (a)
préfixer automatiquement toute tâche créée via `_enrich_kb_with_methods` (par
exemple `ia_<nom>`) pour la distinguer visuellement dans l'éditeur, et
grouper ces tâches dans une section séparée de l'UI ; (b) un outil de
« purge » qui parcourt tous les fichiers `scenarios/*.py`, collecte tous les
noms de tâche réellement référencés (missions directes **et** tâches
composites imbriquées, via `subtasks[].task` récursivement — la même logique
que `collect_watched_tokens` sait déjà faire pour les tokens), et propose à
l'utilisateur de supprimer les tâches KB orphelines. **Taille : S** pour le
préfixage seul (quelques heures) ; **M** pour l'outil de purge (la traversée
récursive existe déjà en partie dans le code, mais l'outil lui-même, son UI
et ses tests sont à construire).

<a id="p4-424"></a>

### 4.2.4 — Aucun mécanisme de spawn dynamique en cours de simulation

**Symptôme.** Tous les agents d'un scénario doivent être connus à l'avance et
sont spawnés une fois pour toutes au démarrage de `main.py`. Il n'existe aucun
moyen de faire apparaître un nouvel agent une fois la simulation en cours
(un renfort qui arrive après un délai, une réponse dynamique à un événement).

**Cause, dans le code.** `main()` construit la liste des threads une seule
fois, avant de les démarrer :

```python
threads = [
    threading.Thread(target=run_agent, args=(name, info['mission'], state, node, watched), daemon=True)
    for name, info in AGENTS.items()
]
for t in threads:
    t.start()
```

Rien, ensuite, ne revient jamais ajouter un thread à cette liste. La tâche
`creation_agent` — celle qui, sémantiquement, devrait « déployer » un agent —
ne fait, par conception documentée dans son propre docstring
(`bdd/primitives_actions.py::creation_agent`), que **poser un marqueur d'état**
sur un agent déjà pré-déclaré et déjà actif depuis le début : « this action
does NOT spawn a new ROS entity […] there is currently no mechanism to spawn
a brand-new ROS entity *and* its own planning thread mid-plan ». Ce n'est pas
une lacune cachée : c'est documentée comme une limite volontaire, avec un
pointeur explicite vers ce qu'il faudrait faire pour l'étendre.

**Impact.** Force à « pré-spawner » tous les agents potentiellement
nécessaires dès le départ (avec une mission passive jusqu'à activation), ce
qui est un contournement fonctionnel mais alourdit la composition des
scénarios et limite le réalisme de situations où le nombre d'acteurs doit
évoluer (renfort tardif, intrusion imprévue en cours de route plutôt que
positionnée dès le début avec un délai de trajectoire).

**Piste de correction.** Faire évoluer `creation_agent` pour qu'elle appelle
réellement `spawn_vessel()` (au lieu du seul marqueur d'état actuel) pour un
agent défini dans le scénario mais marqué « spawn différé », puis démarre
dynamiquement un nouveau thread `run_agent` pour lui — ce qui suppose de
synchroniser l'ajout à une liste de threads déjà en cours d'exécution (la
liste actuelle est construite une fois, statiquement, avant tout `t.start()`)
et d'étendre le schéma de scénario (`AGENTS`) pour permettre un statut
« non spawné au démarrage » par agent. <a id="warn-5"></a>**⚠️ À VÉRIFIER —**
**Taille : L** — implique de repenser la boucle principale de `main.py`, de
valider le comportement avec LOTUSim réel (le comportement d'un spawn tardif
côté simulateur n'est pas documenté dans ce dépôt), et d'étendre les tests ;
plusieurs jours de travail, pas une correction ponctuelle.

---

<a id="p4-43"></a>

## 4.3 — Axe Optimisation / robustesse

<a id="p4-431"></a>

### 4.3.1 — Timeout de sécurité fixe, indépendant du nombre d'agents

**Symptôme.** Chaque agent réévalue tout son plan (`gtpyhop.find_plan`, avec
sa descente HTN et son retour-arrière potentiel) au minimum toutes les 5
secondes, même en l'absence de tout changement pertinent — c'est le rôle
assumé du filet de sécurité ([Partie 3, § 3.1.4](#p3-314)), mais sa valeur est unique et
fixe.

**Cause, dans le code.** `main.py` : `REPLAN_SAFETY_TIMEOUT = 5.0`, utilisée
telle quelle dans `wake.wait(timeout=REPLAN_SAFETY_TIMEOUT)` pour tous les
agents, sans égard au nombre d'agents actifs ni à la profondeur de leur arbre
de tâches.

**Impact.** Négligeable aux échelles actuellement démontrées dans le dépôt (2
à 3 agents par scénario). Le risque est de sérialisation au niveau du GIL de
CPython si le nombre d'agents et la fréquence de replanification
augmentaient significativement en même temps — non mesuré, non observé dans
ce dépôt, mais plausible par construction (tous les threads d'agents
partagent un seul interpréteur Python).

**Piste de correction.** Rendre `REPLAN_SAFETY_TIMEOUT` configurable par
scénario (ajout d'une clé optionnelle lue dans `AGENTS` ou dans un futur
réglage global de scénario) avant d'envisager quoi que ce soit de plus
sophistiqué. **Taille : S.** Une piste plus ambitieuse — ne recalculer
réellement que si `_update_state_from_tracker` a détecté un changement
significatif, au lieu de recalculer inconditionnellement à chaque réveil, y
compris celui du timeout de sécurité — demande d'abord de mesurer si le
recalcul périodique a un coût réel avant de complexifier le mécanisme.
**Taille : M**, et seulement après profilage.

<a id="p4-432"></a>

### 4.3.2 — Les pauses de 3 secondes entre chaque spawn ne sont pas justifiées dans le code

**Symptôme.** Le temps de démarrage d'une exécution réelle croît linéairement
avec le nombre d'agents : `time.sleep(3.0)` après **chaque** spawn réussi,
en plus de l'attente déjà faite pour la confirmation ROS elle-même
(`main._wait(fut, timeout=10.0)` puis `main._wait(res_fut, timeout=10.0)`).
Pour 5 agents, c'est un minimum de ~15 secondes rien que pour ce délai
supplémentaire, avant même que le premier thread de planification démarre.

**Cause, dans le code.** `main.py`, boucle de spawn :

```python
for name, info in AGENTS.items():
    try:
        spawn_vessel(node, name, (info['x'], info['y']), info['model'], ...)
    except Exception as e:
        node.get_logger().error(...)
    time.sleep(3.0)
```

Aucun commentaire n'explique ce délai (même point déjà relevé en
[Partie 3, § 3.1.3](#warn-4)). Comme le spawn attend déjà explicitement la
confirmation ROS de l'Action `/lotusim/mas_cmd` avant ce `sleep`, ce n'est pas
un correctif de synchronisation manquante — c'est un délai *ajouté après* une
confirmation déjà reçue, ce qui suggère un contournement empirique d'un
comportement de LOTUSim non documenté ici (entités qui interfèrent si spawnées
trop vite, peut-être).

**Impact.** Ralentit chaque itération de test/debug d'un scénario à plusieurs
agents ; coût cumulatif à chaque relance pendant le développement.

**Piste de correction.** Chiffrée précisément : mesurer empiriquement, contre
une instance LOTUSim réelle, le délai minimal réellement nécessaire (essais à
0.5 s, 1 s, 2 s) avant de le réduire — ne pas le supprimer sans preuve, car il
peut masquer un vrai problème de course còté simulateur. Si LOTUSim expose un
signal explicite de « entité prête » (par exemple une première publication de
sa position sur `/lotusim/poses`, déjà reçue par `PoseTracker`), l'attendre
activement remplacerait un délai fixe par une confirmation réelle. **Taille :
S** pour la mesure empirique par essais successifs ; **M** si un vrai signal
de disponibilité existe côté LOTUSim et doit être câblé (nécessite une
investigation côté simulateur, hors du périmètre de ce dépôt).

<a id="p4-433"></a>

### 4.3.3 — Logs écrasés à chaque run, flush systématique à chaque message

**Symptôme.** `logs/poses.csv` et `logs/waypoints.csv` sont **écrasés** (pas
concaténés) à chaque lancement de `main.py` — aucun historique automatique
des runs précédents. Par ailleurs, chaque position reçue déclenche un flush
disque immédiat, systématiquement.

**Cause, dans le code.** `main.py::init_logs()` :
`pf = open('logs/poses.csv', 'w', newline='')` (mode `'w'`, pas `'a'`). Et
`PoseTracker._cb()` : `_pose_log_file.flush()` inconditionnel, à **chaque**
message `/lotusim/poses` reçu, changement de position ou non (le commentaire
en tête de fichier l'explique : éviter la perte de données/corruption en
octets NUL sur un arrêt brutal — comportement déjà documenté comme
intentionnel, pas un oubli).

**Impact.** (a) Aucune trace automatique d'un run précédent si on relance
sans copier les fichiers à la main au préalable — déjà arrivé dans ce dépôt :
`logs/poses.csv` observé à 7273 lignes ne représente qu'un seul run, le
dernier. (b) Le flush systématique a un coût I/O réel à chaque message ROS
reçu — non mesuré ici, donc à profiler avant de le changer, puisqu'il s'agit
d'un compromis déjà pesé et documenté (perte de données vs performance), pas
d'un oubli à corriger aveuglément.

**Piste de correction.** (a) Horodater le nom de fichier par run
(`logs/poses_<timestamp>.csv`) pour ne plus écraser l'historique — gain
immédiat, aucun risque. **Taille : XS.** (b) Ne toucher au flush systématique
qu'après une mesure réelle de son coût en usage représentatif (nombre
d'agents et fréquence de publication typiques) — un changement non mesuré
d'un comportement déjà justifié serait exactement le genre de correction à
éviter. **Taille : S** pour le profilage, correction elle-même **XS** à **S**
selon ce qu'il révèle.

<a id="p4-434"></a>

### 4.3.4 — État partagé entre threads sans verrou dédié

**Symptôme** et **cause** : détaillés en [Partie 3, § 3.1.7](#p3-317) — un seul objet
`state` est passé par référence à tous les threads d'agents ; seules les
structures internes de `PoseTracker` sont protégées par un verrou, jamais
`state.agents` lui-même. Repris ici uniquement pour le chiffrage, dans l'esprit
de cette partie.

**Impact.** Aucune anomalie observée à ce jour dans ce dépôt (les
préconditions de distance recalculent tout à chaque cycle, donc un état
légèrement périmé se corrige de lui-même au cycle suivant) — mais aucune
garantie formelle non plus. Le risque croît avec le nombre d'agents et la
fréquence de replanification simultanée.

**Piste de correction.** Un verrou explicite (`threading.Lock`) autour des
sections critiques de lecture/écriture de `state.agents`
(`_update_state_from_tracker`, `_check` dans `bdd/tasks_methods.py`) réglerait
le problème au prix d'une contention accrue entre threads. Une alternative
plus proche de l'esprit actuel du code : chaque agent travaille, à chaque
cycle, sur un **instantané** cohérent de l'état (copie légère prise en début
de cycle) plutôt que sur la structure partagée en direct. **Taille : M** —
touche potentiellement de nombreux points de lecture dans
`bdd/tasks_methods.py` et `main.py`, et nécessite un test de charge à
plusieurs agents pour vérifier qu'un problème réel est bien résolu, puisque
aucun n'est actuellement reproduit.

<a id="p4-435"></a>

### 4.3.5 — `c_aller_a` ne vérifie jamais que le waypoint a réellement été reçu

**Symptôme.** Un waypoint envoyé à un agent peut échouer côté ROS (timeout,
service indisponible) sans que rien dans le code ne le détecte : l'état
interne et les logs indiquent un succès alors que le bateau réel n'a peut-être
jamais reçu la commande.

**Cause, dans le code.** Comparer `bdd/primitives_actions.py::c_aller_a` à
`spawn_vessel`, dans le même fichier. `spawn_vessel` vérifie explicitement le
résultat de chaque attente :

```python
main._wait(fut, timeout=10.0)
if not fut.done() or fut.result() is None:
    raise RuntimeError(f"spawn_vessel: pas de réponse pour '{vessel}'")
```

`c_aller_a`, elle, ne fait **aucune** vérification équivalente :

```python
fut = cli.call_async(req)
main._wait(fut)
node.get_logger().info(f"[{agent}] → ({pos[0]:.5f}, {pos[1]:.5f})")
...
state.agents[agent]['pos'] = {'lat': pos[0], 'lon': pos[1]}
state.agents[agent]['last_waypoint'] = pos
```

Que `fut` soit réellement terminée ou non après `main._wait(fut)` (qui, par
défaut, attend au plus 10 s puis rend la main sans lever d'exception si rien
ne s'est passé — voir sa définition, `main.py::_wait`), le code continue :
il logue un succès, écrit dans `waypoints.csv`, et surtout met à jour
`last_waypoint`.

**Impact — et c'est le point important.** `last_waypoint` est précisément le
champ que **toutes** les méthodes de mouvement de `bdd/tasks_methods.py`
utilisent comme garde d'idempotence (§ 4.5, pièges déjà résolus, point 1 et
2) pour décider de ne **pas** renvoyer une commande déjà envoyée. Si
`c_aller_a` marque `last_waypoint` comme atteint alors que la commande ROS
réelle n'a jamais abouti, l'agent croira pour toujours avoir déjà envoyé
l'ordre — et ne le retentera **jamais**, cycle après cycle, tant que la
position réelle ne change pas d'elle-même. Un échec silencieux du service
ROS peut donc produire un bateau qui n'a jamais reçu sa consigne, sans
qu'aucune replanification ultérieure ne corrige la situation.

**Piste de correction.** Reprendre exactement le motif déjà utilisé dans
`spawn_vessel`, dans le même fichier : vérifier `fut.done()`/`fut.result()`
après `main._wait(fut)`, ne mettre à jour `state.agents[agent]['pos']` /
`last_waypoint` **que** sur confirmation réelle, et sur échec, loguer une
erreur explicite sans marquer `last_waypoint` — ce qui laisse la garde
d'idempotence autoriser un nouvel essai au cycle suivant. **Taille : S** — le
patron à suivre existe déjà, dans le même fichier, à 40 lignes de distance.

<a id="p4-436"></a>

### 4.3.6 — La base de connaissances vit en mémoire, pas seulement sur disque (rappel chiffré)

Documenté et **vérifié par un test exécuté en direct** en [Partie 3, § 3.1.9](#p3-319) :
le `Domain` gtpyhop d'un `app.py` déjà démarré ne se resynchronise avec
`bdd/knowledge_base.json` que sur un appel explicite à `POST /api/kb` — jamais
automatiquement, y compris juste après qu'une génération IA a écrit une
nouvelle tâche sur disque via `_save_kb()`. Repris ici uniquement pour le
chiffrage.

**Piste de correction la plus directe.** Dans `app.py`, handler
`generate_scenario` (route `POST /api/generate-scenario`) : après avoir
obtenu `kb_updates` de `generate_scenario_from_description()`, si
`kb_updates.get('added_tasks') or kb_updates.get('added_methods')`, appeler
`bdd.tasks_methods.load_kb()` avant de répondre — exactement l'appel que fait
déjà `save_kb()` un peu plus haut dans le même fichier. **Taille : XS** (une
poignée de lignes, dans un fichier déjà importé et déjà utilisé dans ce
handler) — l'un des correctifs à plus fort impact pour le coût le plus
faible de tout ce document, puisqu'il supprime un piège qui affecte
directement la fiabilité perçue du générateur IA (§ 4.1.1 en dépend
également).

---

<a id="p4-44"></a>

## 4.4 — Tableau récapitulatif, par taille d'effort

| # | Axe | Point | Taille |
|---|---|---|---|
| 4.3.6 | Optimisation | Recharger la KB en mémoire après une génération IA | **XS** |
| 4.2.2 | Modularité | Ajouter un `requirements.txt` minimal | **XS** |
| 4.3.3(a) | Optimisation | Horodater les fichiers de logs par run | **XS** |
| 4.1.2 | IA | Revoir `MAX_RETRIES` (changement de constante seul) | **XS** |
| 4.3.5 | Optimisation | Vérifier le résultat réel de `c_aller_a` (copier le motif de `spawn_vessel`) | **S** |
| 4.1.1 | IA | Remplacer la vérification vacuité par un vrai calcul de plan | **S** |
| 4.1.6 | IA | Afficher le plan calculé avant import (une fois 4.1.1 fait) | **S** |
| 4.2.1(a) | Modularité | Séparer CSS/JS de `index.html` en fichiers statiques | **S** |
| 4.2.3(a) | Modularité | Préfixer les tâches générées par l'IA (`ia_...`) | **S** |
| 4.3.1 | Optimisation | Rendre `REPLAN_SAFETY_TIMEOUT` configurable | **S** |
| 4.3.2 | Optimisation | Mesurer le délai minimal réel entre spawns | **S** |
| 4.1.3(a) | IA | Étendre le regex de détection de branches à d'autres tournures | **S** |
| 4.1.2 (mesure) | IA | Jeu de descriptions-tests pour mesurer le taux de succès par nombre de retries | **S** |
| 4.1.5 | IA | Tests unitaires sur les fonctions pures du générateur | **M** |
| 4.1.4 | IA | Détection de comptage sur noms propres arbitraires | **M** |
| 4.1.3(b) | IA | Reformulation assistée par LLM avant détection déterministe | **M** |
| 4.2.1(b) | Modularité | Découper le JS en modules ES natifs | **M** |
| 4.2.3(b) | Modularité | Outil de purge des tâches KB orphelines | **M** |
| 4.3.4 | Optimisation | Verrouiller ou « snapshotter » l'état partagé entre threads | **M** |
| 4.1.5 (bis) | IA | Mock/cassettes du LLM pour tester le pipeline complet | **M** |
| 4.2.4 | Modularité | Spawn dynamique réel en cours de simulation | **L** |

---

<a id="p4-45"></a>

## 4.5 — Pièges déjà rencontrés et résolus — à ne pas réintroduire

Ce tableau est construit à partir des commentaires laissés **dans le code
lui-même** — chaque ligne correspond à un bug réellement rencontré, dont la
trace explicative est toujours présente à l'endroit du correctif. Il sert un
seul but : éviter qu'une future modification, faite sans lire ces
commentaires, ne réintroduise le même problème.

| Piège | Où | Symptôme observé | Correctif appliqué |
|---|---|---|---|
| **`False` traité comme un échec de méthode, `[]` comme un succès vide** — GTPyhop les distingue strictement (`seek_plan` : `subtasks != False and subtasks != None`) | `bdd/tasks_methods.py`, toutes les méthodes de mouvement | La 2ᵉ méthode de `suivre_agent` (poursuite) prenait le dessus un cycle sur deux, parce que la 1ʳᵉ méthode (retour base) « échouait » (`False`) simplement parce que le waypoint de base était déjà en cours d'envoi — oscillation visible du bateau | Retourner `[]` (succès, sans nouvelle action) au lieu de `False` quand le waypoint voulu est déjà en cours (garde d'idempotence sur `last_waypoint`) |
| **`aller_a_position_m` sans garde d'idempotence** | `bdd/tasks_methods.py::aller_a_position_m` | `rentrer_a_la_base` ne faisait jamais réellement arriver l'agent à la base — le waypoint identique était renvoyé à chaque cycle de replanification (l'agent surveille toujours sa propre position, donc replanifie à chaque micro-mouvement), réinitialisant la progression du suiveur de trajectoire LOTUSim à chaque fois — visible comme un bateau qui « tourne sur place » | Ajout de la même garde d'idempotence (`last_waypoint` / `in_zone`) que les autres méthodes de mouvement |
| **Méthodes dupliquées à chaque sauvegarde de la base de connaissances** | `bdd/tasks_methods.py::load_kb()` | `gtpyhop.declare_task_methods()` **accumule** par conception (prévu pour répartir des déclarations entre plusieurs fichiers) — mais `load_kb()` est rappelée à chaque sauvegarde KB et à chaque génération IA ; sans nettoyage préalable, chaque rechargement empilait une copie de plus de chaque méthode, multipliant silencieusement préconditions/sous-tâches et décalant l'ordre des méthodes à chaque édition | `gtpyhop.current_domain._task_method_dict.pop(task_name, None)` avant de ré-enregistrer les méthodes de chaque tâche |
| **Rebond au bord du rayon d'orbite (arrondi flottant)** | `bdd/tasks_methods.py::orbiter_m` | Un rayon d'orbite exactement égal au seuil de déclenchement de `distance_below` se trouve pile sur la frontière d'arrondi flottant — un cos/sin ponctuel pouvait pousser la distance calculée juste au-dessus, faisant croire l'agent « trop loin » et le faisant sauter directement sur la position exacte de la cible pendant un cycle, avant de reprendre l'orbite | `ORBIT_RADIUS_MARGIN = 0.9` — orbite strictement à l'intérieur (90 %) du rayon de déclenchement, jamais pile dessus |
| **Clause perdue silencieusement dans une condition composée** (ex. « commande = attaquer ET distance(...) ≤ 200 m ») | `bdd/ai_scenario_generator.py`, ancien système à plusieurs détecteurs séparés (remplacé par `_detect_multi_condition_branches`) | Chaque détecteur ne regardait qu'un seul type de condition ; une condition combinant deux clauses de types différents ne gardait que la clause reconnue par le premier détecteur qui matchait, abandonnant l'autre sans avertissement — et une 3ᵉ branche entière (« si commande = fuir ») a déjà été perdue de cette façon | Un détecteur unique (`_parse_branch_conditions`) qui découpe sur « ET »/« AND » et classe **chaque clause indépendamment** ; si une seule clause ne se reconnaît pas, refus explicite du scénario entier plutôt que construction partielle silencieuse |
| **Token halluciné en syntaxe de placeholder pour un nom d'agent littéral** | `bdd/ai_scenario_generator.py::_repair_suggested_tokens` | Le LLM enveloppe parfois un nom d'agent réel dans la syntaxe réservée aux tokens (ex. `__agent2__` pour désigner littéralement l'agent `agent2`), que rien ne résout puisque ce n'est un rôle/marqueur d'aucun agent | Réécriture automatique de tout token `__x__` non reconnu vers le nom d'agent réel correspondant (comparaison insensible à la casse), s'il correspond à un agent effectivement présent dans la génération |
| **Scénario halluciné sur un texte sans signal comportemental réel** (ex. « test\nagent 1\nagent 2 ») | `bdd/ai_scenario_generator.py::_has_actionable_signal` | Un simple compte d'agents ou des noms nus, sans aucune indication de comportement, étaient auparavant traités comme suffisants pour appeler le LLM — qui invente alors un scénario plausible mais sans rapport avec l'intention réelle, ancré sur la mission la plus représentée dans le prompt | Exiger un mot-clé de mission reconnu ou une mention d'intrus/menace **avant** même d'appeler le modèle ; sinon, poser directement une question de clarification |
| **Précondition de distance à soi-même, toujours vraie ou toujours fausse** | `bdd/ai_scenario_generator.py::_validate_suggested_method` | Une tâche suggérée par le LLM pouvait comparer un agent à lui-même (`target: "__self__"`) dans une précondition de distance — toujours 0, donc la méthode ne se déclenchait jamais comme prévu, silencieusement | Rejet explicite de toute précondition de distance ciblant `__self__`, avec message d'erreur nommé, avant écriture dans la base de connaissances |
| **Tâche personnalisée proposée mais jamais réellement assignée** (« orphaned suggestion ») | `bdd/ai_scenario_generator.py`, détection `orphaned_suggestion` | Le LLM pouvait construire une tâche complète via `suggested_methods`, puis assigner à l'agent concerné une mission de repli différente (ex. `suivre_agent` au lieu de la tâche personnalisée) — la tâche personnalisée s'écrivait quand même dans la base comme code mort, et le comportement réel obtenu ne correspondait plus à la description d'origine | Détection explicite du cas « tâche suggérée non utilisée par aucune mission d'agent » et retry/refus, plutôt qu'écriture silencieuse d'une tâche qui ne sert jamais |

---

<a id="p4-cloture"></a>

## Clôture du document de passation

Cette Partie 4 referme le document en quatre parties. Pour un repreneur qui
arriverait directement ici sans avoir lu le reste : le système fonctionne, il
est testé (au sens propre du terme pour les threads/HTN/ROS — voir [Partie 3](#p3) ;
et manuellement pour l'IA), et chaque limite listée ci-dessus est connue et
circonscrite, pas un mystère à redécouvrir. La priorité recommandée, à la
seule lumière de l'effort et de l'impact combinés, est le trio § 4.3.6
(recharger la KB après génération IA), § 4.1.1 (vérification de plan réelle)
et § 4.3.5 (vérifier le résultat de `c_aller_a`) — les trois tiennent chacun
en quelques lignes, s'appuient sur du code déjà existant dans le même
fichier, et corrigent chacun un comportement silencieusement incorrect plutôt
qu'une simple amélioration de confort.
