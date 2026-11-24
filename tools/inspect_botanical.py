import json

path = "site-data/botanical_okhla/network.json"
with open(path) as f:
    d = json.load(f)

print("Nodes count:", len(d.get("nodes", [])))
print("Links count:", len(d.get("links", [])))
print("Imagery:", d.get("imagery"))

for l in d["links"]:
    geoms = l["geometry"]
    desc = []
    for g in geoms:
        t = g.get("type")
        if t == "line":
            desc.append(f"line({g.get('from')}->{g.get('to')})")
        elif t == "arc":
            desc.append(f"arc(c={g.get('center')}, r={g.get('radius')}, {g.get('a0_deg')}->{g.get('a1_deg')})")
        elif t == "bezier":
            desc.append(f"bezier(p0={g.get('p0')}, p3={g.get('p3')})")
    print(f"{l['id']:12} | {l['name'][:30]:30} | lanes={l['lanes']} | layer={l.get('elevation_layer',0)} | {', '.join(desc)}")
