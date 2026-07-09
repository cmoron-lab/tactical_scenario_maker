#!/usr/bin/env python3
"""
Génère une carte HTML interactive des trajectoires et waypoints des agents.
Usage : python3 visualize.py [logs/poses.csv] [logs/waypoints.csv]
"""
import csv
import json
import os
import sys
import webbrowser
from collections import defaultdict

COLORS = {
    'usv':   '#2196F3',  # bleu
    'intru': '#F44336',  # rouge
}
DEFAULT_COLOR = '#4CAF50'

def load_csv(path):
    """
    Reads a poses/waypoints log, tolerating a log left corrupted by an
    interrupted run: a process killed abruptly (rather than shut down
    cleanly) can leave a run of NUL bytes in the CSV — csv.DictReader raises
    on those outright — and/or a row truncated mid-write. Both are stripped/
    skipped (with a warning) instead of crashing the whole visualization,
    since the surrounding valid rows are still worth plotting.
    """
    if not os.path.exists(path):
        return []
    with open(path, encoding='utf-8', errors='replace') as f:
        raw = f.read()
    nul_count = raw.count('\x00')
    if nul_count:
        print(f"⚠ {path} : {nul_count} octet(s) NUL (écriture interrompue) — nettoyés avant lecture.")
        raw = raw.replace('\x00', '')

    rows = []
    skipped = 0
    for row in csv.DictReader(raw.splitlines()):
        try:
            float(row.get('lat', ''))
            float(row.get('lon', ''))
        except (TypeError, ValueError):
            skipped += 1
            continue
        rows.append(row)
    if skipped:
        print(f"⚠ {path} : {skipped} ligne(s) mal formée(s) ignorée(s).")
    return rows

def main():
    poses_path     = sys.argv[1] if len(sys.argv) > 1 else 'logs/poses.csv'
    waypoints_path = sys.argv[2] if len(sys.argv) > 2 else 'logs/waypoints.csv'

    poses     = load_csv(poses_path)
    waypoints = load_csv(waypoints_path)

    if not poses:
        print(f"Aucune donnée dans {poses_path}")
        return

    trajectories = defaultdict(list)
    for row in poses:
        trajectories[row['agent']].append({
            'lat': float(row['lat']),
            'lon': float(row['lon']),
            'ts':  row['timestamp'],
        })

    wp_by_agent = defaultdict(list)
    for row in waypoints:
        wp_by_agent[row['agent']].append({
            'lat': float(row['lat']),
            'lon': float(row['lon']),
            'ts':  row['timestamp'],
        })

    center_lat = float(poses[0]['lat'])
    center_lon = float(poses[0]['lon'])

    traj_js = json.dumps({a: [{'lat': p['lat'], 'lon': p['lon']} for p in pts]
                           for a, pts in trajectories.items()})
    wp_js   = json.dumps({a: pts for a, pts in wp_by_agent.items()})
    colors_js = json.dumps(COLORS)

    html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8"/>
  <title>Agent trajectories</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <style>
    body {{ margin: 0; }}
    #map {{ height: 100vh; }}
    #legend {{
      position: absolute; bottom: 30px; left: 10px; z-index: 1000;
      background: white; padding: 10px 14px; border-radius: 8px;
      box-shadow: 0 2px 8px rgba(0,0,0,.3); font: 13px sans-serif;
    }}
    #legend h4 {{ margin: 0 0 6px; }}
    .leg-row {{ display: flex; align-items: center; margin: 3px 0; gap: 8px; }}
    .leg-line {{ width: 24px; height: 3px; border-radius: 2px; }}
    .leg-dot  {{ width: 10px; height: 10px; border-radius: 50%; border: 2px solid #555; }}
  </style>
</head>
<body>
<div id="map"></div>
<div id="legend">
  <h4>Légende</h4>
  <div class="leg-row"><div class="leg-line" style="background:#2196F3"></div> USV trajectoire</div>
  <div class="leg-row"><div class="leg-line" style="background:#F44336"></div> Intru trajectoire</div>
  <div class="leg-row"><div class="leg-dot" style="background:white"></div> Waypoint</div>
  <div class="leg-row"><div class="leg-dot" style="background:#333"></div> Départ / Arrivée</div>
</div>
<script>
const map = L.map('map').setView([{center_lat}, {center_lon}], 17);
L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
  attribution: '© OpenStreetMap'
}}).addTo(map);

const trajectories = {traj_js};
const waypoints    = {wp_js};
const COLORS       = {colors_js};
const DEFAULT      = '#4CAF50';

for (const [agent, points] of Object.entries(trajectories)) {{
  const color  = COLORS[agent] || DEFAULT;
  const latlngs = points.map(p => [p.lat, p.lon]);

  L.polyline(latlngs, {{color, weight: 2, opacity: 0.7}})
   .bindTooltip(agent).addTo(map);

  L.circleMarker(latlngs[0], {{radius: 6, color: '#333', fillColor: color, fillOpacity: 1}})
   .bindTooltip(`${{agent}} — départ`).addTo(map);

  L.circleMarker(latlngs[latlngs.length-1], {{radius: 6, color: '#333', fillColor: color, fillOpacity: 1}})
   .bindTooltip(`${{agent}} — arrivée`).addTo(map);
}}

for (const [agent, wps] of Object.entries(waypoints)) {{
  const color = COLORS[agent] || DEFAULT;
  for (const wp of wps) {{
    L.circleMarker([wp.lat, wp.lon], {{
      radius: 4, color, fillColor: 'white', fillOpacity: 1, weight: 2
    }}).bindTooltip(`waypoint ${{agent}}<br>${{wp.ts.slice(11,19)}}`).addTo(map);
  }}
}}
</script>
</body>
</html>"""

    out = 'logs/map.html'
    with open(out, 'w') as f:
        f.write(html)
    print(f"Carte sauvegardée : {out}")
    webbrowser.open(f'file://{os.path.abspath(out)}')

if __name__ == '__main__':
    main()
