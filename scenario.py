# scenario.py — Instance concrète du scénario
# Ce fichier est généré et réécrit par l'interface graphique (app.py).
# Modifiable directement aussi : ce sont juste des variables Python.

NOM = "interception_sous_marin"

AGENTS = [
    {"nom": "fremm1", "modele": "fremm", "x": 0,    "y": 0,   "vitesse": 8.0, "dispo": 1},
    {"nom": "lrauv1", "modele": "lrauv", "x": 2000, "y": 250, "vitesse": 3.0, "dispo": 1},
]

ZONES = {
    "zone_alpha": {"waypoints": [[0, 0], [500, 0], [500, 500], [0, 500]]}
}

# Buts initiaux par agent — exécutés séquentiellement dans l'ordre de la liste
BUTS_PAR_AGENT = {
    "fremm1": [["patrouiller", "fremm1", "zone_alpha"]],
    "lrauv1": [["naviguer_vers_point", "lrauv1", -500, 250]],
}

# Événements évalués à chaque tick par le moniteur Python
# quand : liste de conditions — toutes doivent être vraies
#   ["distance", source, operateur, seuil, variable_cible]
#   ["champ",    agent,  operateur, valeur]
# alors : {agent: qui_reçoit_le_nouveau_but, but: [tache, arg1, ...]}
# rearmable : False = one-shot, True = se redéclenche tant que la condition est vraie
EVENEMENTS = [
    {
        "nom": "intrusion_detectee",
        "quand": [
            ["distance", "fremm1", "inferieur", 600, "cible"],
            ["modele",   "cible",  "egal",      "lrauv"]
        ],
        "alors": {"agent": "fremm1", "but": ["intercepter", "fremm1", "cible"]},
        "rearmable": False
    }
]
