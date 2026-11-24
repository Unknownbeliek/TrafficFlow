import json

with open('site-data/botanical_okhla/osm_raw.json') as f:
    d = json.load(f)

nodes = d['nodes']
ways = d['ways']

ramp_ways = [w for w in ways if 'mahamaya' in str(w['tags']).lower() or 'ramp' in str(w['tags']).lower()]
print(f"Total Mahamaya ramp ways: {len(ramp_ways)}")
for w in ramp_ways:
    pts = [nodes[nid] for nid in w['nodes'] if nid in nodes]
    print(f"Way {w['id']} ({w['tags'].get('name')}): {len(pts)} nodes, start={pts[0]}, end={pts[-1]}")
