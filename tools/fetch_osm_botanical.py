import urllib.request
import xml.etree.ElementTree as ET
import json
import math

# Mahamaya Flyover / Botanical Interchange bounding box
# Let's inspect the area:
# Mahamaya flyover is at 28.560 N, 77.325 E
# Let's get bbox: min_lon, min_lat, max_lon, max_lat
bbox = (77.318, 28.552, 77.332, 28.566)
url = f"https://api.openstreetmap.org/api/0.6/map?bbox={bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}"
print(f"Fetching OSM data from: {url}")

req = urllib.request.Request(url, headers={"User-Agent": "TrackflowPBL/1.0"})
with urllib.request.urlopen(req, timeout=15) as res:
    xml_data = res.read()

root = ET.fromstring(xml_data)
print(f"Downloaded OSM XML, size: {len(xml_data)} bytes")

nodes = {}
for n in root.findall('node'):
    nid = n.get('id')
    lat = float(n.get('lat'))
    lon = float(n.get('lon'))
    nodes[nid] = (lat, lon)

ways = []
for w in root.findall('way'):
    tags = {t.get('k'): t.get('v') for t in w.findall('tag')}
    hw = tags.get('highway')
    if hw in ('motorway', 'trunk', 'primary', 'secondary', 'tertiary',
              'motorway_link', 'trunk_link', 'primary_link', 'secondary_link', 'tertiary_link'):
        nd_refs = [nd.get('ref') for nd in w.findall('nd')]
        ways.append({
            'id': w.get('id'),
            'tags': tags,
            'nodes': nd_refs
        })

print(f"Total nodes: {len(nodes)}, highway ways: {len(ways)}")
for w in ways[:15]:
    name = w['tags'].get('name', 'unnamed')
    hw = w['tags'].get('highway')
    lanes = w['tags'].get('lanes', '1')
    layer = w['tags'].get('layer', '0')
    print(f"  Way {w['id']}: {name} ({hw}, lanes={lanes}, layer={layer}) with {len(w['nodes'])} nodes")

# Save raw parsed data
with open('site-data/botanical_okhla/osm_raw.json', 'w') as f:
    json.dump({'nodes': nodes, 'ways': ways}, f, indent=2)
print("Saved site-data/botanical_okhla/osm_raw.json")
