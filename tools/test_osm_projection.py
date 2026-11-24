import json
import math
import cv2
import numpy as np

with open('site-data/botanical_okhla/osm_raw.json') as f:
    d = json.load(f)

nodes = d['nodes']
ways = d['ways']

# Find the crossing nodes:
# Noida-Greater Noida expressway:
exp_nodes = []
for w in ways:
    name = w['tags'].get('name', '')
    if 'Noida-Greater Noida Expressway' in name or 'Maharaja Agrasen Marg' in name or 'Mahamaya Flyover' in name:
        for nid in w['nodes']:
            if nid in nodes:
                exp_nodes.append(nodes[nid])

exp_nodes = np.array(exp_nodes)
lat_center = exp_nodes[:, 0].mean()
lon_center = exp_nodes[:, 1].mean()
print(f"Interchange center: lat={lat_center:.6f}, lon={lon_center:.6f}")

# Projection:
# Local meters (x=East, y=North)
m_per_deg_lat = 111320.0
m_per_deg_lon = 111320.0 * math.cos(math.radians(lat_center))

def project(lat, lon):
    x = (lon - lon_center) * m_per_deg_lon
    y = (lat - lat_center) * m_per_deg_lat
    return x, y

# Test converting all ways to meter polyline
all_polylines = []
for w in ways:
    pts = [project(*nodes[nid]) for nid in w['nodes'] if nid in nodes]
    if len(pts) >= 2:
        all_polylines.append((w, pts))

print(f"Projected {len(all_polylines)} road polylines successfully!")
