import json
import math
import cv2
import numpy as np

def make_transform(imagery):
    m_per_px = imagery.get("m_per_px", 0.8484)
    ox, oy = imagery.get("origin_px", [865, 520])
    rotation_deg = imagery.get("rotation_deg", -6.5)
    th = math.radians(rotation_deg)
    cos_th = math.cos(th)
    sin_th = math.sin(th)

    def to_image(x, y):
        ix = ox + (x * cos_th - y * sin_th) / m_per_px
        iy = oy + (x * sin_th + y * cos_th) / m_per_px
        return int(round(ix)), int(round(iy))

    return to_image

img = cv2.imread('section_img/Botanical_interchange_apple.png')

test_configs = [
    {"name": "original", "origin_px": [1023.5, 562.2], "rotation_deg": 42.3, "m_per_px": 0.8484},
    {"name": "aligned_v1", "origin_px": [865.0, 525.0], "rotation_deg": -6.5, "m_per_px": 0.8484},
    {"name": "aligned_v2", "origin_px": [875.0, 520.0], "rotation_deg": -5.5, "m_per_px": 0.8484},
    {"name": "aligned_v3", "origin_px": [880.0, 525.0], "rotation_deg": -6.0, "m_per_px": 0.8484},
]

with open('site-data/botanical_okhla/network.json') as f:
    net = json.load(f)

for cfg in test_configs:
    canvas = img.copy()
    to_img = make_transform(cfg)
    
    for lk in net['links']:
        color = (0, 165, 255) if 'mainline' in lk['name'].lower() else (255, 200, 0)
        thickness = 3 if 'mainline' in lk['name'].lower() else 2
        for g in lk['geometry']:
            t = g['type']
            if t == 'line':
                p1 = to_img(g['a'][0], g['a'][1])
                p2 = to_img(g['b'][0], g['b'][1])
                cv2.line(canvas, p1, p2, color, thickness)
            elif t == 'arc':
                c = g['c']
                r = g['r']
                a0 = math.radians(g['a0'])
                a1 = math.radians(g['a1'])
                pts = []
                for step in range(21):
                    frac = step / 20.0
                    ang = a0 + frac * (a1 - a0)
                    px = c[0] + r * math.cos(ang)
                    py = c[1] + r * math.sin(ang)
                    pts.append(to_img(px, py))
                for i in range(len(pts) - 1):
                    cv2.line(canvas, pts[i], pts[i+1], color, thickness)
            elif t == 'bezier':
                p0 = g['p0']
                p1 = g['p1']
                p2 = g['p2']
                p3 = g['p3']
                pts = []
                for step in range(21):
                    u = step / 20.0
                    u2 = u * u
                    u3 = u2 * u
                    v = 1.0 - u
                    v2 = v * v
                    v3 = v2 * v
                    bx = v3*p0[0] + 3*v2*u*p1[0] + 3*v*u2*p2[0] + u3*p3[0]
                    by = v3*p0[1] + 3*v2*u*p1[1] + 3*v*u2*p2[1] + u3*p3[1]
                    pts.append(to_img(bx, by))
                for i in range(len(pts) - 1):
                    cv2.line(canvas, pts[i], pts[i+1], color, thickness)

    out_path = f"C:/Users/rajku/.gemini/antigravity/brain/7fbe18dc-e823-4fc5-9f11-b73d94a0c585/overlay_{cfg['name']}.jpg"
    cv2.imwrite(out_path, canvas)
    print(f"Saved {out_path}")
