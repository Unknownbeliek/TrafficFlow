import urllib.request
import json

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

mirrors = [
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
    "https://z.overpass-api.de/api/interpreter",
]

for url in mirrors:
    print(f"Trying mirror: {url}")
    req = urllib.request.Request(url, data=query.encode("utf-8"), headers={"User-Agent": "TrackflowPBL/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as res:
            data = json.loads(res.read())
            elements = data.get("elements", [])
            ways = [e for e in elements if e.get("type") == "way"]
            print(f"  SUCCESS on {url}! Fetched {len(ways)} real road ways, total elements: {len(elements)}")
            break
    except Exception as e:
        print(f"  Failed: {e}")
