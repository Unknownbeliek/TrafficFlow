import urllib.request
import json

# Mahamaya Flyover / Botanical Okhla interchange:
# Lat ~ 28.560, Lon ~ 77.325
query = """
[out:json][timeout:25];
(
  way["highway"~"motorway|trunk|primary|secondary|motorway_link|trunk_link|primary_link"]
    (28.552,77.315,28.568,77.335);
);
out body;
>;
out skel qt;
"""

url = "https://overpass-api.de/api/interpreter"
req = urllib.request.Request(url, data=query.encode("utf-8"), headers={"User-Agent": "TrackflowPBL/1.0"})
try:
    with urllib.request.urlopen(req, timeout=15) as res:
        data = json.loads(res.read())
        elements = data.get("elements", [])
        ways = [e for e in elements if e.get("type") == "way"]
        print(f"Overpass API Success! Fetched {len(ways)} real road ways, total elements: {len(elements)}")
        for w in ways[:10]:
            print("  Road:", w.get("tags", {}).get("name", "unnamed"), "| highway:", w.get("tags", {}).get("highway"), "| oneway:", w.get("tags", {}).get("oneway"))
except Exception as e:
    print("Error accessing Overpass:", e)
