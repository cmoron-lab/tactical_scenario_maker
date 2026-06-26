# tasks.py — Déclaration des tâches et de leurs méthodes
#
# TASKS = { nom_tache: { params, methodes: [nom_methode, ...] } }
#
# L'ORDRE des méthodes est important :
# GTPyhop essaie la première, si elle retourne None il passe à la suivante.
#
# Pour ajouter une tâche : ajouter une entrée ici ET écrire la méthode dans methods.py.

TASKS = {
    "patrouiller": {
        "params": ["agent", "zone"],
        "methodes": [
            "methode_patrouille_standard"
        ]
    },

    "intercepter": {
        "params": ["agent", "cible"],
        "methodes": [
            "methode_deployer_drone",       # essayée en premier (si drone dispo)
            "methode_interception_directe"  # fallback
        ]
    },

    "engager": {
        "params": ["agent", "cible"],
        "methodes": [
            "methode_engagement_direct"
        ]
    },

    "escorter": {
        "params": ["agent", "convoi"],
        "methodes": [
            "methode_escorte_rapprochee"
        ]
    },

    "rechercher_zone": {
        "params": ["agent", "zone"],
        "methodes": [
            "methode_recherche_systematique"
        ]
    },
}
