import json

with open('site-data/kalindi_kunj/osm_raw.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

nodes = data.get('nodes', {})
for w in data.get('ways', []):
    tags = w.get('tags', {})
    name = tags.get('name', tags.get('name:en', ''))
    hw = tags.get('highway', '')
    if any(k in name.lower() for k in ['kalindi', 'barrage', 'amrapali', 'bandh', 'aurangzeb']) or hw in ('primary', 'secondary'):
        nds = [str(n) for n in w.get('nodes', [])]
        pts = [nodes[n] for n in nds if n in nodes]
        p0 = f"({pts[0][0]:.4f}, {pts[0][1]:.4f})" if pts else "none"
        p1 = f"({pts[-1][0]:.4f}, {pts[-1][1]:.4f})" if pts else "none"
        print(f"ID={w['id']} | Name={name} | hw={hw} | lanes={tags.get('lanes', '?')} | oneway={tags.get('oneway', '?')} | {p0} -> {p1}")
