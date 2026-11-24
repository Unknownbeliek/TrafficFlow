import json
import math
import cv2
import numpy as np

with open('site-data/botanical_okhla/network.json') as f:
    net = json.load(f)

img = cv2.imread('section_img/Botanical_interchange_apple.png')

# In the satellite image:
# Horizontal road (Dadri Road / Agrasen Marg) runs across at -6 deg
# In OSM:
# Dadri Road / Agrasen Marg runs roughly West-East (angle ~ 0 to 10 deg)
# Let's test candidate rotation angles and origins
test_configs = [
    {"name": "rot_0", "ox": 960, "oy": 540, "rot": 0.0, "m": 1.0},
    {"name": "rot_n6", "ox": 960, "oy": 540, "rot": -6.0, "m": 0.85},
    {"name": "rot_35", "ox": 960, "oy": 540, "rot": 35.0, "m": 0.85},
    {"name": "rot_n45", "ox": 960, "oy": 540, "rot": -45.0, "m": 0.85},
]

for cfg in test_configs:
    canvas = img.copy()
    ox, oy, rot, m = cfg["ox"], cfg["oy"], cfg["rot"], cfg["m"]
    th = math.radians(rot)
    c, s = math.cos(th), math.sin(th)
    
    def to_img(x, y):
        # East is +x, North is +y (in image: South is +y, so -y)
        ix = ox + (x * c + y * s) / m
        iy = oy + (-x * s + y * c) / m
        return int(round(ix)), int(round(iy))

    for l in net['links']:
        is_flyover = l.get('layer', 0) > 0
        is_ramp = l.get('kind') == 'ramp'
        color = (255, 200, 0) if is_flyover else ((0, 255, 120) if is_ramp else (0, 160, 255))
        width = 3 if is_flyover else (2 if is_ramp else 4)
        for g in l['geometry']:
            p1 = to_img(*g['a'])
            p2 = to_img(*g['b'])
            cv2.line(canvas, p1, p2, color, width)

    out_path = f"C:/Users/rajku/.gemini/antigravity/brain/7fbe18dc-e823-4fc5-9f11-b73d94a0c585/osm_overlay_{cfg['name']}.jpg"
    cv2.imwrite(out_path, canvas)
    print(f"Saved {out_path}")
