#!/usr/bin/env python3
"""
app.py — LOTUSim Poste de Commandement
Lancer : python app.py  →  http://localhost:8765
"""

import sys, os, math, time, threading, importlib, inspect, pprint, copy, ast
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'HTN'))

from flask import Flask, jsonify, request, render_template_string
from flask_cors import CORS

import HTN.gtpyhop as gtpyhop
import HTN.actions as actions_mod
import HTN.methods as methods_mod
import HTN.tasks   as tasks_mod
import scenario    as scenario_mod

app  = Flask(__name__)
CORS(app)

# ══════════════════════════════════════════════════════════════════════
#  CHARGEMENT DU DOMAINE GTPYHOP
# ══════════════════════════════════════════════════════════════════════

def charger_domaine():
    """Recharge les 3 fichiers HTN et reconstruit le domaine GTPyhop."""
    importlib.reload(actions_mod)
    importlib.reload(methods_mod)
    importlib.reload(tasks_mod)

    gtpyhop.current_domain = gtpyhop.Domain("lotusim")

    # Actions : toutes les fonctions publiques de actions.py
    fns_actions = [fn for name, fn in inspect.getmembers(actions_mod, inspect.isfunction)
                   if not name.startswith("_")]
    if fns_actions:
        gtpyhop.declare_actions(*fns_actions)

    # Tâches + méthodes depuis tasks.py TASKS
    for nom_tache, defn in tasks_mod.TASKS.items():
        fns_methodes = []
        for nom_m in defn.get("methodes", []):
            fn = getattr(methods_mod, nom_m, None)
            if fn and callable(fn):
                fns_methodes.append(fn)
        if fns_methodes:
            gtpyhop.declare_task_methods(nom_tache, *fns_methodes)

    gtpyhop.verbose = 0


charger_domaine()  # au démarrage


# ══════════════════════════════════════════════════════════════════════
#  CONSTRUCTION DE L'ÉTAT GTPYHOP
# ══════════════════════════════════════════════════════════════════════

def construire_etat(agents, zones):
    state = gtpyhop.State("courant")
    state.trace = []
    state.zones  = zones
    state.x = {}; state.y = {}; state.modele = {}
    state.dispo = {}; state.phase = {}; state.waypoints_courants = {}

    for nom, ag in agents.items():
        state.x[nom]     = ag["x"]
        state.y[nom]     = ag["y"]
        state.modele[nom]  = ag["modele"]
        state.dispo[nom]   = ag.get("dispo", 1)
        state.phase[nom]   = ag.get("phase", "init")
        state.waypoints_courants[nom] = {"points": [], "loop": False}

    return state


# ══════════════════════════════════════════════════════════════════════
#  FAKE SIMULATEUR CINÉMATIQUE
# ══════════════════════════════════════════════════════════════════════

TOLERANCE_WP = 5.0   # mètres — distance pour considérer un waypoint atteint

def tick_sim(agents, dt=1.0):
    for ag in agents.values():
        wps = ag.get("waypoints", [])
        if not wps or ag.get("fini", False):
            continue

        cx, cy = wps[0]
        dx, dy = cx - ag["x"], cy - ag["y"]
        dist   = math.hypot(dx, dy)

        if dist < TOLERANCE_WP:
            wps.pop(0)
            if not wps:
                if ag.get("loop", False):
                    ag["waypoints"] = list(ag.get("waypoints_origin", []))
                else:
                    ag["fini"] = True
        else:
            pas = min(ag["vitesse"] * dt, dist)
            ag["x"] += (dx / dist) * pas
            ag["y"] += (dy / dist) * pas


def envoyer_waypoints(agents, agent, waypoints, loop=False):
    if agent not in agents:
        return
    wps = [tuple(w) for w in waypoints]
    agents[agent].update({"waypoints": list(wps), "waypoints_origin": list(wps),
                           "loop": loop, "fini": False})


# ══════════════════════════════════════════════════════════════════════
#  MONITEUR D'ÉVÉNEMENTS
# ══════════════════════════════════════════════════════════════════════

OPERATEURS = {
    "egal":               lambda a, b: a == b,
    "different":          lambda a, b: a != b,
    "superieur":          lambda a, b: float(a) >  float(b),
    "superieur_ou_egal":  lambda a, b: float(a) >= float(b),
    "inferieur":          lambda a, b: float(a) <  float(b),
    "inferieur_ou_egal":  lambda a, b: float(a) <= float(b),
    "dans":               lambda a, b: a in b,
}


def evaluer_evenements(evenements, agents, deja_declenche):
    declenches = []

    for evt in evenements:
        nom = evt["nom"]
        if nom in deja_declenche and not evt.get("rearmable", False):
            continue

        contexte, ok = {}, True
        for cond in evt["quand"]:
            if cond[0] == "distance":
                _, source, op, seuil, var_cible = cond
                if source not in agents:
                    ok = False; break

                candidats = ([contexte[var_cible]] if var_cible in contexte
                             else [n for n in agents if n != source])
                trouve = False
                for nc in candidats:
                    if nc not in agents:
                        continue
                    d = math.hypot(agents[source]["x"] - agents[nc]["x"],
                                   agents[source]["y"] - agents[nc]["y"])
                    if OPERATEURS[op](d, seuil):
                        contexte[var_cible] = nc
                        trouve = True; break
                if not trouve:
                    ok = False; break
            else:
                champ, qui_param, op, valeur = cond
                agent_nom = contexte.get(qui_param, qui_param)
                if agent_nom not in agents:
                    ok = False; break
                val = agents[agent_nom].get(champ)
                if val is None or not OPERATEURS[op](val, valeur):
                    ok = False; break

        if ok:
            if not evt.get("rearmable", False):
                deja_declenche.add(nom)
            declenches.append((evt, contexte))

    return declenches


# ══════════════════════════════════════════════════════════════════════
#  EXÉCUTEUR — traduit une action du plan en commande fake sim
# ══════════════════════════════════════════════════════════════════════

ACTIONS_INSTANTANEES = {"stopper", "spawn_agent"}
ACTIONS_LOOP         = {"patrouiller_zone", "suivre_agent"}


def appliquer_action(action, agents, zones):
    """Applique une action sur le fake sim. Retourne True si instantané."""
    nom  = action[0]
    args = action[1:]

    if nom == "patrouiller_zone":
        agent, zone = args[0], args[1]
        wps = zones.get(zone, {}).get("waypoints", [])
        envoyer_waypoints(agents, agent, wps, loop=True)
        agents[agent]["phase"] = "patrouille"

    elif nom in ("aller_vers_agent", "naviguer_vers_agent"):
        agent, cible = args[0], args[1]
        if cible in agents:
            envoyer_waypoints(agents, agent, [(agents[cible]["x"], agents[cible]["y"])])
            agents[agent]["phase"] = "interception"

    elif nom == "naviguer_vers_point":
        agent = args[0]; x, y = float(args[1]), float(args[2])
        envoyer_waypoints(agents, agent, [(x, y)])
        agents[agent]["phase"] = "transit"

    elif nom == "stopper":
        agent = args[0]
        agents[agent].update({"waypoints": [], "fini": True, "phase": "arret"})

    elif nom == "spawn_agent":
        nom_drone, modele = args[0], args[1]
        x, y = float(args[2]), float(args[3])
        if nom_drone not in agents:
            agents[nom_drone] = {
                "nom": nom_drone, "modele": modele, "x": x, "y": y, "vitesse": 15.0,
                "dispo": 1, "waypoints": [], "waypoints_origin": [], "loop": False,
                "fini": False, "phase": "spawne"
            }

    elif nom == "suivre_agent":
        agent, cible = args[0], args[1]
        if cible in agents:
            envoyer_waypoints(agents, agent, [(agents[cible]["x"], agents[cible]["y"])])
            agents[agent]["phase"] = "suivi"

    return nom in ACTIONS_INSTANTANEES


def action_terminee(action, agents):
    """Renvoie True si l'action en cours est considérée comme terminée."""
    nom   = action[0]
    agent = action[1] if len(action) > 1 else None

    if nom in ACTIONS_INSTANTANEES:
        return True
    if nom in ACTIONS_LOOP:
        return False  # jamais terminé seul (interrompu par événement)
    if agent and agent in agents:
        return agents[agent].get("fini", False)
    return False


# ══════════════════════════════════════════════════════════════════════
#  ÉTAT D'EXÉCUTION (partagé thread principal ↔ thread boucle)
# ══════════════════════════════════════════════════════════════════════

etat_exec = {
    "running":    False,
    "t":          0,
    "agents":     {},
    "plans":      {},   # {agent: [actions_restantes]}
    "files_buts": {},   # {agent: [buts_restants]}
    "log":        [],
    "log_cursor": 0,
    "evts":       [],
    "evts_cursor": 0,
}
exec_lock  = threading.Lock()
stop_event = threading.Event()


# ══════════════════════════════════════════════════════════════════════
#  BOUCLE D'EXÉCUTION (thread séparé)
# ══════════════════════════════════════════════════════════════════════

def boucle(buts_par_agent):
    global etat_exec

    stop_event.clear()
    importlib.reload(scenario_mod)
    charger_domaine()

    # Init agents
    agents = {}
    for ag_def in scenario_mod.AGENTS:
        nom = ag_def["nom"]
        agents[nom] = {**ag_def,
                       "waypoints": [], "waypoints_origin": [], "loop": False, "fini": False,
                       "phase": "init"}

    zones          = scenario_mod.ZONES
    evenements     = scenario_mod.EVENEMENTS
    deja_declenche = set()
    log            = []
    evts_log       = []

    # Files de buts (copie profonde pour ne pas modifier le scénario)
    files_buts = {ag: list(buts) for ag, buts in buts_par_agent.items()}
    plans      = {ag: [] for ag in agents}

    def planifier_prochain_but(agent):
        file = files_buts.get(agent, [])
        if not file:
            return
        but = file[0]
        state = construire_etat(agents, zones)
        plan  = gtpyhop.find_plan(state, [tuple(but)])
        if plan:
            plans[agent] = list(plan)
            log.append(f"[t={t}s] Plan {agent} : {' → '.join(a[0] for a in plan)}")
            appliquer_action(plans[agent][0], agents, zones)
        else:
            log.append(f"[t={t}s] ⚠ Pas de plan pour {but}")
            file.pop(0)

    # Planification initiale
    t = 0
    for agent in agents:
        planifier_prochain_but(agent)

    # ── Boucle principale ──────────────────────────────────────────────
    while not stop_event.is_set():
        time.sleep(1.0)
        t += 1
        tick_sim(agents)

        # Avancement des plans
        for agent in list(agents.keys()):
            plan = plans.get(agent, [])
            if not plan:
                # Plus d'actions → but suivant
                file = files_buts.get(agent, [])
                if file:
                    file.pop(0)
                planifier_prochain_but(agent)
                continue

            action_courante = plan[0]
            if action_terminee(action_courante, agents):
                plan.pop(0)
                if plan:
                    log.append(f"[t={t}s] → {agent} : {plan[0][0]}")
                    appliquer_action(plan[0], agents, zones)
                else:
                    # Plan fini → but suivant
                    file = files_buts.get(agent, [])
                    if file:
                        file.pop(0)
                    planifier_prochain_but(agent)

        # Moniteur d'événements
        declenches = evaluer_evenements(evenements, agents, deja_declenche)
        for evt, contexte in declenches:
            msg = f"[t={t}s] ★ ÉVÉNEMENT : {evt['nom']}"
            log.append(msg)
            evts_log.append({"nom": evt["nom"], "t": t})

            # Résoudre le but
            alors    = evt["alors"]
            but_brut = alors["but"]
            but      = [contexte.get(tok, tok) for tok in but_brut]
            agent_cible = alors.get("agent", but[1] if len(but) > 1 else None)

            if agent_cible:
                state = construire_etat(agents, zones)
                plan  = gtpyhop.find_plan(state, [tuple(but)])
                if plan:
                    plans[agent_cible] = list(plan)
                    agents[agent_cible]["fini"] = False
                    appliquer_action(plans[agent_cible][0], agents, zones)
                    log.append(f"[t={t}s] → Nouveau plan {agent_cible} : "
                               f"{' → '.join(a[0] for a in plan)}")

        # Mise à jour état partagé
        with exec_lock:
            etat_exec["t"]          = t
            etat_exec["running"]    = True
            etat_exec["agents"]     = {
                nom: {"x": round(ag["x"], 1), "y": round(ag["y"], 1),
                      "modele": ag["modele"], "phase": ag.get("phase", "?"),
                      "fini": ag.get("fini", False)}
                for nom, ag in agents.items()
            }
            etat_exec["plans"]      = {
                ag: {"action_courante": plans[ag][0][0] if plans.get(ag) else "–",
                     "buts_restants":   len(files_buts.get(ag, []))}
                for ag in agents
            }
            etat_exec["log"]        = log
            etat_exec["evts"]       = evts_log

    with exec_lock:
        etat_exec["running"] = False


# ══════════════════════════════════════════════════════════════════════
#  FLASK — ROUTES API
# ══════════════════════════════════════════════════════════════════════

FICHIERS_HTN = {
    "actions": os.path.join("HTN", "actions.py"),
    "methods": os.path.join("HTN", "methods.py"),
    "tasks":   os.path.join("HTN", "tasks.py"),
}

BASE = os.path.dirname(__file__)


@app.get("/api/fichier/<nom>")
def get_fichier(nom):
    if nom not in FICHIERS_HTN:
        return jsonify({"erreur": "Fichier inconnu"}), 404
    chemin = os.path.join(BASE, FICHIERS_HTN[nom])
    with open(chemin, encoding="utf-8") as f:
        return jsonify({"nom": nom, "contenu": f.read()})


@app.post("/api/fichier/<nom>")
def save_fichier(nom):
    if nom not in FICHIERS_HTN:
        return jsonify({"ok": False, "erreur": "Fichier inconnu"}), 404
    contenu = request.json.get("contenu", "")
    try:
        compile(contenu, FICHIERS_HTN[nom], "exec")
    except SyntaxError as e:
        return jsonify({"ok": False, "erreur": f"Erreur de syntaxe : {e}"})

    chemin = os.path.join(BASE, FICHIERS_HTN[nom])
    tmp    = chemin + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(contenu)
    os.replace(tmp, chemin)

    try:
        charger_domaine()
    except Exception as e:
        return jsonify({"ok": False, "erreur": f"Erreur au rechargement : {e}"})

    return jsonify({"ok": True})


@app.get("/api/scenario")
def get_scenario():
    importlib.reload(scenario_mod)
    return jsonify({
        "nom":           scenario_mod.NOM,
        "agents":        scenario_mod.AGENTS,
        "zones":         scenario_mod.ZONES,
        "buts_par_agent": scenario_mod.BUTS_PAR_AGENT,
        "evenements":    scenario_mod.EVENEMENTS,
    })


@app.post("/api/scenario")
def save_scenario():
    d = request.json
    # Validation minimale
    if "agents" not in d:
        return jsonify({"ok": False, "erreur": "Clé 'agents' manquante"})

    contenu = f"""# scenario.py — généré par LOTUSim App
# Modifiable directement.

NOM = {repr(d.get('nom', 'sans_nom'))}

AGENTS = {pprint.pformat(d['agents'])}

ZONES = {pprint.pformat(d.get('zones', {}))}

BUTS_PAR_AGENT = {pprint.pformat(d.get('buts_par_agent', {}))}

EVENEMENTS = {pprint.pformat(d.get('evenements', []))}
"""
    try:
        compile(contenu, "scenario.py", "exec")
    except SyntaxError as e:
        return jsonify({"ok": False, "erreur": str(e)})

    chemin = os.path.join(BASE, "scenario.py")
    with open(chemin, "w", encoding="utf-8") as f:
        f.write(contenu)
    importlib.reload(scenario_mod)
    return jsonify({"ok": True})


@app.post("/api/preview")
def preview():
    data = request.json or {}
    buts_par_agent = data.get("buts_par_agent", {})
    importlib.reload(scenario_mod)
    try:
        charger_domaine()
    except Exception as e:
        return jsonify({"ok": False, "erreur": str(e)})

    agents_init = {ag["nom"]: ag for ag in scenario_mod.AGENTS}
    zones       = scenario_mod.ZONES
    state       = construire_etat(agents_init, zones)
    plans       = {}

    for agent, file_buts in buts_par_agent.items():
        if not file_buts:
            continue
        plan = gtpyhop.find_plan(state, [tuple(file_buts[0])])
        if plan:
            plans[agent] = [{"action": a[0], "args": list(a[1:])} for a in plan]
        else:
            plans[agent] = []

    return jsonify({"ok": True, "plans": plans})


@app.post("/api/execute")
def execute():
    if etat_exec["running"]:
        return jsonify({"ok": False, "erreur": "Déjà en cours"})
    buts = request.json.get("buts_par_agent", {})
    with exec_lock:
        etat_exec["log"]        = []
        etat_exec["log_cursor"] = 0
        etat_exec["evts"]       = []
        etat_exec["evts_cursor"]= 0
        etat_exec["t"]          = 0

    t = threading.Thread(target=boucle, args=(buts,), daemon=True)
    t.start()
    return jsonify({"ok": True})


@app.get("/api/status")
def status():
    with exec_lock:
        log_cursor  = etat_exec["log_cursor"]
        evts_cursor = etat_exec["evts_cursor"]
        nouveaux_logs = etat_exec["log"][log_cursor:]
        nouveaux_evts = etat_exec["evts"][evts_cursor:]
        etat_exec["log_cursor"]  = len(etat_exec["log"])
        etat_exec["evts_cursor"] = len(etat_exec["evts"])

        return jsonify({
            "running":          etat_exec["running"],
            "t":                etat_exec["t"],
            "agents":           etat_exec["agents"],
            "plans_courants":   etat_exec["plans"],
            "nouveaux_logs":    nouveaux_logs,
            "nouveaux_evenements": nouveaux_evts,
        })


@app.post("/api/stop")
def stop():
    stop_event.set()
    return jsonify({"ok": True})


# ══════════════════════════════════════════════════════════════════════
#  HTML — INTERFACE GRAPHIQUE
# ══════════════════════════════════════════════════════════════════════

HTML = r"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<title>LOTUSim — Poste de Commandement</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#080d18;color:#b8ccd8;font-family:'Courier New',monospace;font-size:13px;overflow:hidden;height:100vh}
/* Header */
.hdr{background:#0a1020;border-bottom:1px solid #1a3050;padding:10px 18px;display:flex;align-items:center;gap:14px;height:42px}
.hdr h1{color:#3d8fd6;font-size:14px;letter-spacing:3px}
.badge{padding:2px 9px;font-size:10px;letter-spacing:1px;border-radius:2px}
.b-amber{background:#2a1e06;color:#f59e0b;border:1px solid #78400a}
.b-green{background:#061a10;color:#34d399;border:1px solid #065f36}
.b-red{background:#1a0606;color:#f87171;border:1px solid #7a1a1a}
/* Layout */
.main{display:grid;grid-template-columns:440px 1fr;height:calc(100vh - 42px)}
.panel{border-right:1px solid #1a3050;display:flex;flex-direction:column;overflow:hidden}
/* Tabs */
.tabs{display:flex;background:#070c16;border-bottom:1px solid #1a3050;flex-shrink:0}
.tab{padding:8px 14px;cursor:pointer;border:none;background:none;color:#5a7a90;font-size:11px;font-family:inherit;letter-spacing:1px;border-bottom:2px solid transparent}
.tab:hover{color:#8aaabb}
.tab.act{color:#3d8fd6;border-bottom-color:#3d8fd6}
/* Panels */
.pscroll{overflow-y:auto;flex:1;padding:0}
.sec{padding:14px;border-bottom:1px solid #101828}
.stitle{color:#3d8fd6;font-size:10px;letter-spacing:2px;margin-bottom:10px;text-transform:uppercase}
/* Code editor */
.ced{width:100%;height:380px;background:#040810;color:#4ade80;border:1px solid #1a3050;padding:12px;font-family:'Courier New',monospace;font-size:12px;resize:vertical;outline:none}
.ced:focus{border-color:#3d8fd6}
/* Buttons */
.btn{padding:5px 13px;border:1px solid #1a3050;background:#0a1020;color:#3d8fd6;cursor:pointer;font-family:inherit;font-size:11px;letter-spacing:1px}
.btn:hover{background:#1a3050}
.btn.g{border-color:#065f36;color:#34d399}.btn.g:hover{background:#061a10}
.btn.r{border-color:#7a1a1a;color:#f87171}.btn.r:hover{background:#1a0606}
.btn.a{border-color:#78400a;color:#f59e0b}.btn.a:hover{background:#2a1e06}
/* Tables */
table{width:100%;border-collapse:collapse}
th{background:#070c16;color:#3d8fd6;padding:5px 10px;text-align:left;font-size:10px;letter-spacing:1px;border-bottom:1px solid #1a3050}
td{padding:5px 10px;border-bottom:1px solid #0a1020;font-size:12px}
tr:hover td{background:#0a1020}
/* Inputs */
input[type=text],input[type=number],select{background:#040810;color:#b8ccd8;border:1px solid #1a3050;padding:3px 7px;font-family:inherit;font-size:12px;outline:none}
input:focus,select:focus{border-color:#3d8fd6}
/* Messages */
.msg{padding:5px 10px;font-size:11px;margin-top:6px;display:none}
.msg.ok{background:#061a10;color:#34d399}.msg.err{background:#1a0606;color:#f87171}
/* Plan items */
.pi{padding:4px 10px;margin:2px 0;background:#0a1020;border-left:2px solid #1a3050;font-size:12px}
.pi.cur{border-left-color:#34d399;color:#34d399}
/* Log */
.le{padding:3px 0;border-bottom:1px solid #0a1020;font-size:11px}
.le.evt{color:#f59e0b}.le.act{color:#4ade80}.le.info{color:#5a7a90}
/* Right panel sections */
.rpanel{overflow-y:auto;height:100%}
/* Distances */
.dist-item{display:inline-block;margin:3px 8px 3px 0;font-size:11px;padding:2px 8px;background:#0a1020;border:1px solid #1a3050}
/* Status bar */
.sbar{position:fixed;bottom:0;left:0;right:0;background:#070c16;border-top:1px solid #1a3050;padding:3px 18px;font-size:10px;color:#3a5a70;display:flex;gap:20px;z-index:10}
</style>
</head>
<body>

<div class="hdr">
  <h1>⚓ LOTUSIM — POSTE DE COMMANDEMENT</h1>
  <span id="si" class="badge b-amber">INACTIF</span>
  <span id="snom" style="color:#3a5a70;font-size:11px;margin-left:8px;"></span>
  <span style="flex:1"></span>
  <span style="font-size:10px;color:#3a5a70;">FAKE SIM MODE</span>
</div>

<div class="main">
  <!-- ══ PANNEAU GAUCHE ══════════════════════════════════════════════ -->
  <div class="panel">
    <div class="tabs">
      <button class="tab act" onclick="tab('htn',this)">◈ HTN</button>
      <button class="tab" onclick="tab('scenario',this)">◈ SCÉNARIO</button>
      <button class="tab" onclick="tab('exec',this)">◈ EXÉCUTION</button>
    </div>

    <!-- HTN -->
    <div id="t-htn" class="pscroll">
      <div class="tabs">
        <button class="tab act" onclick="sf('actions',this)">Actions</button>
        <button class="tab" onclick="sf('methods',this)">Méthodes</button>
        <button class="tab" onclick="sf('tasks',this)">Tâches</button>
      </div>
      <div class="sec">
        <div class="stitle" id="flabel">HTN/actions.py</div>
        <textarea id="ced" class="ced" spellcheck="false"></textarea>
        <div style="display:flex;gap:8px;margin-top:8px;align-items:center">
          <button class="btn g" onclick="savef()">💾 Sauvegarder</button>
          <button class="btn" onclick="loadf()">↺ Recharger</button>
          <div id="fmsg" class="msg"></div>
        </div>
      </div>
    </div>

    <!-- SCÉNARIO -->
    <div id="t-scenario" class="pscroll" style="display:none">
      <div class="sec">
        <div class="stitle">Nom du scénario</div>
        <input type="text" id="snom-in" style="width:100%">
      </div>

      <div class="sec">
        <div class="stitle">Agents</div>
        <table>
          <thead><tr><th>Nom</th><th>Modèle</th><th>X</th><th>Y</th><th>V</th><th>dispo</th><th></th></tr></thead>
          <tbody id="at"></tbody>
        </table>
        <button class="btn" style="margin-top:8px" onclick="addAgent()">+ Agent</button>
      </div>

      <div class="sec">
        <div class="stitle">Zones (waypoints JSON)</div>
        <div id="zones-div"></div>
        <button class="btn" style="margin-top:8px" onclick="addZone()">+ Zone</button>
      </div>

      <div class="sec">
        <div class="stitle">Buts initiaux par agent (JSON list)</div>
        <div id="buts-div"></div>
      </div>

      <div class="sec">
        <div class="stitle">Événements (JSON)</div>
        <textarea id="evts-ed" class="ced" style="height:180px;color:#f59e0b;" spellcheck="false"></textarea>
      </div>

      <div class="sec" style="display:flex;gap:8px;align-items:center">
        <button class="btn g" onclick="saveScenario()">💾 Sauvegarder le scénario</button>
        <div id="smsg" class="msg"></div>
      </div>
    </div>

    <!-- EXÉCUTION -->
    <div id="t-exec" class="pscroll" style="display:none">
      <div class="sec">
        <div class="stitle">Buts chargés</div>
        <div id="buts-exec"></div>
      </div>
      <div class="sec" style="display:flex;gap:8px;flex-wrap:wrap">
        <button class="btn a" onclick="preview()">▶ GÉNÉRER LE PLAN</button>
        <button class="btn g" id="btn-go" onclick="lancer()">⚡ LANCER</button>
        <button class="btn r" id="btn-stop" onclick="arreter()" style="display:none">■ ARRÊTER</button>
      </div>
      <div class="sec">
        <div class="stitle">Plan généré</div>
        <div id="plan-div"></div>
      </div>
    </div>
  </div>

  <!-- ══ PANNEAU DROIT ════════════════════════════════════════════════ -->
  <div class="rpanel">
    <div class="sec">
      <div class="stitle">Positions des agents</div>
      <table>
        <thead><tr><th>Agent</th><th>Modèle</th><th>X (m)</th><th>Y (m)</th><th>Phase</th><th>Action courante</th></tr></thead>
        <tbody id="pos-tbody"></tbody>
      </table>
    </div>

    <div class="sec">
      <div class="stitle">Distances</div>
      <div id="dists">–</div>
    </div>

    <div class="sec">
      <div class="stitle">Événements déclenchés</div>
      <div id="evts-log" style="max-height:120px;overflow-y:auto"></div>
    </div>

    <div class="sec">
      <div class="stitle" style="display:flex;justify-content:space-between">
        <span>Journal d'exécution</span>
        <button class="btn" style="padding:1px 7px;font-size:10px" onclick="document.getElementById('elog').innerHTML=''">Vider</button>
      </div>
      <div id="elog" style="max-height:320px;overflow-y:auto"></div>
    </div>
  </div>
</div>

<div class="sbar">
  <span>t = <b id="tc">0</b>s</span>
  <span id="rs" style="color:#3a5a70">● ARRÊTÉ</span>
  <span>LOTUSim v1.0</span>
</div>

<script>
let curFile='actions', running=false, interval=null;
let _sd={};  // scenario data

// ── Tabs ─────────────────────────────────────────────────────────────
function tab(id,el){
  ['htn','scenario','exec'].forEach(t=>document.getElementById('t-'+t).style.display='none');
  document.getElementById('t-'+id).style.display='block';
  document.querySelectorAll('.main .panel>.tabs>.tab').forEach(t=>t.classList.remove('act'));
  el.classList.add('act');
  if(id==='scenario') loadScenario();
  if(id==='exec') loadExecButs();
}

// ── File editor ───────────────────────────────────────────────────────
const FLABELS={'actions':'HTN/actions.py','methods':'HTN/methods.py','tasks':'HTN/tasks.py'};
function sf(nom,el){
  curFile=nom;
  document.getElementById('flabel').textContent=FLABELS[nom];
  document.querySelectorAll('#t-htn .tabs .tab').forEach(t=>t.classList.remove('act'));
  el.classList.add('act');
  loadf();
}
async function loadf(){
  const r=await fetch('/api/fichier/'+curFile);
  const d=await r.json();
  document.getElementById('ced').value=d.contenu;
}
async function savef(){
  const r=await fetch('/api/fichier/'+curFile,{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({contenu:document.getElementById('ced').value})});
  const d=await r.json();
  showMsg('fmsg',d.ok?'Sauvegardé ✓':d.erreur,d.ok);
}

// ── Scenario editor ───────────────────────────────────────────────────
async function loadScenario(){
  const r=await fetch('/api/scenario'); _sd=await r.json();
  document.getElementById('snom-in').value=_sd.nom||'';
  renderAgents(); renderZones(); renderButs();
  document.getElementById('evts-ed').value=JSON.stringify(_sd.evenements||[],null,2);
}
function renderAgents(){
  document.getElementById('at').innerHTML=(_sd.agents||[]).map((ag,i)=>`
    <tr>
      <td><input type="text" value="${ag.nom}" onchange="_sd.agents[${i}].nom=this.value" style="width:75px"></td>
      <td><input type="text" value="${ag.modele}" onchange="_sd.agents[${i}].modele=this.value" style="width:65px"></td>
      <td><input type="number" value="${ag.x}" onchange="_sd.agents[${i}].x=+this.value" style="width:58px"></td>
      <td><input type="number" value="${ag.y}" onchange="_sd.agents[${i}].y=+this.value" style="width:58px"></td>
      <td><input type="number" value="${ag.vitesse}" onchange="_sd.agents[${i}].vitesse=+this.value" style="width:46px"></td>
      <td><input type="number" value="${ag.dispo}" onchange="_sd.agents[${i}].dispo=+this.value" style="width:40px"></td>
      <td><button class="btn r" style="padding:2px 5px" onclick="_sd.agents.splice(${i},1);renderAgents()">✕</button></td>
    </tr>`).join('');
}
function addAgent(){
  _sd.agents=_sd.agents||[];
  _sd.agents.push({nom:'agent'+_sd.agents.length,modele:'fremm',x:0,y:0,vitesse:5.0,dispo:1});
  renderAgents();
}
function renderZones(){
  document.getElementById('zones-div').innerHTML=Object.entries(_sd.zones||{}).map(([nom,z])=>`
    <div style="margin-bottom:8px">
      <span style="color:#3d8fd6">${nom}</span>
      <input type="text" value='${JSON.stringify(z.waypoints)}'
             onchange="try{_sd.zones['${nom}'].waypoints=JSON.parse(this.value)}catch(e){}"
             style="width:100%;margin-top:4px;font-size:11px">
    </div>`).join('');
}
function addZone(){
  const nom=prompt('Nom de la zone :');
  if(!nom) return;
  _sd.zones=_sd.zones||{};
  _sd.zones[nom]={waypoints:[[0,0],[100,0],[100,100],[0,100]]};
  renderZones();
}
function renderButs(){
  document.getElementById('buts-div').innerHTML=(_sd.agents||[]).map(ag=>`
    <div style="margin-bottom:8px">
      <div style="color:#3d8fd6;margin-bottom:4px;font-size:11px">${ag.nom}</div>
      <input type="text" id="buts-${ag.nom}" style="width:100%;font-size:11px"
             value='${JSON.stringify((_sd.buts_par_agent||{})[ag.nom]||[])}'>
    </div>`).join('');
}
async function saveScenario(){
  _sd.nom=document.getElementById('snom-in').value;
  try{_sd.evenements=JSON.parse(document.getElementById('evts-ed').value);}catch(e){alert('JSON événements invalide');return;}
  _sd.buts_par_agent={};
  (_sd.agents||[]).forEach(ag=>{
    const el=document.getElementById('buts-'+ag.nom);
    if(el) try{_sd.buts_par_agent[ag.nom]=JSON.parse(el.value);}catch(e){}
  });
  const r=await fetch('/api/scenario',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(_sd)});
  const d=await r.json();
  showMsg('smsg',d.ok?'Scénario sauvegardé ✓':d.erreur,d.ok);
  if(d.ok) document.getElementById('snom').textContent=_sd.nom;
}

// ── Execution tab ─────────────────────────────────────────────────────
async function loadExecButs(){
  const r=await fetch('/api/scenario'); const d=await r.json();
  document.getElementById('buts-exec').innerHTML=
    Object.entries(d.buts_par_agent||{}).map(([ag,buts])=>
      `<div style="margin-bottom:6px"><span style="color:#3d8fd6">${ag} :</span>
       <span style="font-size:11px"> ${buts.map(b=>`${b[0]}(${b.slice(1).join(',')})`).join(' → ')}</span></div>`
    ).join('')||'<div style="color:#3a5a70">Aucun but défini</div>';
}
async function preview(){
  const r=await fetch('/api/scenario'); const sd=await r.json();
  const r2=await fetch('/api/preview',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({buts_par_agent:sd.buts_par_agent})});
  const d=await r2.json();
  const div=document.getElementById('plan-div');
  if(!d.ok){div.innerHTML=`<div class="le err">${d.erreur}</div>`;return;}
  div.innerHTML=Object.entries(d.plans).map(([ag,plan])=>`
    <div style="margin-bottom:12px">
      <div style="color:#3d8fd6;font-size:11px;margin-bottom:4px">▸ ${ag}</div>
      ${plan.length?plan.map((a,i)=>`<div class="pi">${i+1}. ${a.action}(${a.args.join(', ')})</div>`).join('')
        :'<div style="color:#f87171;font-size:11px">Aucun plan trouvé</div>'}
    </div>`).join('');
}
async function lancer(){
  const r=await fetch('/api/scenario'); const sd=await r.json();
  await fetch('/api/execute',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({buts_par_agent:sd.buts_par_agent})});
  setRunning(true);
  interval=setInterval(refreshStatus,1000);
}
async function arreter(){
  await fetch('/api/stop',{method:'POST'});
  setRunning(false);
  clearInterval(interval);
}
function setRunning(r){
  running=r;
  document.getElementById('btn-go').style.display=r?'none':'inline';
  document.getElementById('btn-stop').style.display=r?'inline':'none';
  document.getElementById('si').textContent=r?'ACTIF':'INACTIF';
  document.getElementById('si').className='badge '+(r?'b-green':'b-amber');
  document.getElementById('rs').textContent=r?'● ACTIF':'● ARRÊTÉ';
  document.getElementById('rs').style.color=r?'#34d399':'#3a5a70';
}

// ── Status refresh ────────────────────────────────────────────────────
async function refreshStatus(){
  const r=await fetch('/api/status'); const d=await r.json();
  if(!d.running && running){setRunning(false);clearInterval(interval);return;}

  document.getElementById('tc').textContent=d.t;

  // Positions table
  const ags=d.agents||{};
  document.getElementById('pos-tbody').innerHTML=
    Object.entries(ags).map(([nom,ag])=>{
      const plan=(d.plans_courants||{})[nom]||{};
      const phaseClass=ag.phase==='patrouille'?'b-amber':ag.phase==='interception'||ag.phase==='transit'?'b-red':'b-green';
      return `<tr>
        <td><b>${nom}</b></td>
        <td style="color:#5a7a90">${ag.modele}</td>
        <td>${ag.x.toFixed(1)}</td>
        <td>${ag.y.toFixed(1)}</td>
        <td><span class="badge ${phaseClass}">${ag.phase}</span></td>
        <td style="font-size:11px;color:#4ade80">${plan.action_courante||'–'}</td>
      </tr>`;
    }).join('');

  // Distances
  const noms=Object.keys(ags), dists=[];
  for(let i=0;i<noms.length;i++) for(let j=i+1;j<noms.length;j++){
    const a=ags[noms[i]],b=ags[noms[j]];
    const dist=Math.round(Math.sqrt((a.x-b.x)**2+(a.y-b.y)**2));
    const col=dist<600?'#f87171':dist<1500?'#f59e0b':'#4ade80';
    dists.push(`<span class="dist-item">${noms[i]} ↔ ${noms[j]} : <span style="color:${col}">${dist}m</span></span>`);
  }
  document.getElementById('dists').innerHTML=dists.join('')||'–';

  // Events
  const el=document.getElementById('evts-log');
  (d.nouveaux_evenements||[]).forEach(e=>{
    el.innerHTML+=`<div class="le evt">★ [t=${e.t}s] ${e.nom}</div>`;
  });

  // Log
  const elog=document.getElementById('elog');
  (d.nouveaux_logs||[]).forEach(l=>{
    const cls=l.includes('★')?'evt':l.includes('Plan')||l.includes('→')?'act':'info';
    elog.innerHTML+=`<div class="le ${cls}">${l}</div>`;
  });
  elog.scrollTop=elog.scrollHeight;
}

// ── Utils ─────────────────────────────────────────────────────────────
function showMsg(id,msg,ok){
  const el=document.getElementById(id);
  el.textContent=msg; el.className='msg '+(ok?'ok':'err'); el.style.display='block';
  setTimeout(()=>el.style.display='none',3000);
}

// ── Init ──────────────────────────────────────────────────────────────
window.onload=()=>{
  loadf();
  fetch('/api/scenario').then(r=>r.json()).then(d=>{
    document.getElementById('snom').textContent=d.nom||'';
  });
};
</script>
</body>
</html>"""


@app.get("/")
def index():
    return render_template_string(HTML)


# ══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("\n╔══════════════════════════════════════╗")
    print("║  LOTUSim — Poste de Commandement     ║")
    print("║  http://localhost:8765               ║")
    print("╚══════════════════════════════════════╝\n")
    app.run(host="127.0.0.1", port=8765, debug=False)
