import json
import math
import cv2
import numpy as np

with open('site-data/botanical_okhla/network.json') as f:
    net = json.load(f)

net['imagery'] = {
    'm_per_px': 0.95,
    'origin_px': [900.0, 560.0],
    'rotation_deg': 33.0,
    'scale_bar_m': 50,
    'view': [0, 56, 1920, 1024]
}
with open('site-data/botanical_okhla/network.json', 'w') as f:
    json.dump(net, f, indent=2)

img = cv2.imread('section_img/Botanical_interchange_apple.png')
canvas = img.copy()

ox, oy = 900.0, 560.0
rot = 33.0
m = 0.95
th = math.radians(rot)
c, s = math.cos(th), math.sin(th)

def to_img(x, y):
    ix = ox + (x * c - y * s) / m
    iy = oy + (x * s + y * c) / m
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

out_path = "C:/Users/rajku/.gemini/antigravity/brain/7fbe18dc-e823-4fc5-9f11-b73d94a0c585/osm_calibrated_final.jpg"
cv2.imwrite(out_path, canvas)
print(f"Saved {out_path}")
