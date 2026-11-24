import json

with open('site-data/kalindi_kunj/osm_raw.json') as f:
    d = json.load(f)

nodes = d['nodes']
ways = d['ways']

for wid in [670037899, 670037902, 1552904481, 1552904482, 379890428, 379890429, 379890430, 379890440, 690188270, 369852348]:
    w = next((x for x in ways if str(x['id']) == str(wid)), None)
    if w:
        pts = [nodes[nid] for nid in w['nodes'] if nid in nodes]
        print(f"{wid} ({w['tags'].get('name', '')}): start={pts[0]}, end={pts[-1]}, len={len(pts)}")
