import json

with open('site-data/botanical_okhla/osm_raw.json') as f:
    d = json.load(f)

ways = d['ways']
for w in ways:
    tags = w['tags']
    if 'bridge' in tags or 'canal' in tags or 'drain' in str(tags).lower() or 'mahamaya' in str(tags).lower():
        print(w['id'], tags.get('name'), tags.get('highway'), tags.get('bridge'), tags.get('layer'))
