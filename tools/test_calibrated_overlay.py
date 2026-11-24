import sys; sys.path.insert(0, 'tools')
import math
import cv2
import numpy as np

with open('tools/sites.py') as f:
    code = f.read()

# Replace imagery and LOAR
code = code.replace('"botanical_okhla": {"m_per_px": 0.8484, "origin_px": [1023.5, 562.2],  "rotation_deg": 42.3,',
                    '"botanical_okhla": {"m_per_px": 0.8484, "origin_px": [880.0, 545.0],   "rotation_deg": -5.0,')
code = code.replace('LOAR, SLIPR = 19.0, 46.0', 'LOAR, SLIPR = 38.0, 46.0')

g = {}
exec(code, g)
net = g['build_botanical_okhla']()

img = cv2.imread('section_img/Botanical_interchange_apple.png')
canvas = img.copy()

im = net.imagery
m_per_px = im['m_per_px']
ox, oy = im['origin_px']
th = math.radians(im['rotation_deg'])
cos_th = math.cos(th)
sin_th = math.sin(th)

def to_img(x, y):
    return int(round(ox + (x*cos_th - y*sin_th)/m_per_px)), int(round(oy + (x*sin_th + y*cos_th)/m_per_px))

for lk in net.links.values():
    is_mainline = 'mainline' in lk['name'].lower()
    color = (0, 220, 255) if is_mainline else (0, 140, 255)
    width = 3 if is_mainline else 2
    for g_prim in lk['geometry']:
        t = g_prim['type']
        if t == 'line':
            cv2.line(canvas, to_img(*g_prim['a']), to_img(*g_prim['b']), color, width)
        elif t == 'arc':
            c = g_prim['c']
            r = g_prim['r']
            a0 = math.radians(g_prim['a0'])
            a1 = math.radians(g_prim['a1'])
            pts = []
            for step in range(21):
                frac = step / 20.0
                ang = a0 + frac * (a1 - a0)
                px = c[0] + r * math.cos(ang)
                py = c[1] + r * math.sin(ang)
                pts.append(to_img(px, py))
            for i in range(len(pts) - 1):
                cv2.line(canvas, pts[i], pts[i+1], (0, 255, 100), width)

out_file = 'C:/Users/rajku/.gemini/antigravity/brain/7fbe18dc-e823-4fc5-9f11-b73d94a0c585/overlay_calibrated_botanical.jpg'
cv2.imwrite(out_file, canvas)
print(f"Saved {out_file}")
