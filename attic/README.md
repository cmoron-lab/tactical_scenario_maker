# attic — code parqué, hors du paquet

`ai_scenario_generator.py` : générateur IA (Ollama + règles) du pré-PoC,
gelé lors du refactor de 2026-07 (décision de session : parqué, pas adapté).
Il parle l'ANCIEN format de scénario et mutait la KB en pleine requête —
sa réadaptation au schéma canonique (et la séparation doctrine/brouillon —
positionnement du LLM, docs/lsga-architecture-v3.md §3.3) est un incrément
dédié. Ne pas importer depuis tsm/.

`scenarios-v1/` — scénarios v1 parqués à l'harmonisation v2 (2026-07-13) :
démos des feuilles legacy (veiller/encercler/eviter/drone), sans équivalent
doctrinal v3. Le runtime v1 (main.py sans profil) sait toujours les jouer
depuis ce dossier à la main.
