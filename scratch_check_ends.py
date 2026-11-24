import json
with open('site-data/kalindi_kunj/network.json') as f:
    d = json.load(f)

for l in d['links']:
    if l['kind'] in ['approach', 'connector', 'exit']:
        g = l['geometry']
        p0 = g[0]['a']
        p1 = g[-1]['b']
        print(l['id'], l['kind'], l['lanes'], "start:", p0, "end:", p1)
