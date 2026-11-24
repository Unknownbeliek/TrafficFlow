import sys; sys.path.insert(0, 'tools')
import math
import cv2
import numpy as np
import build_botanical_clean

net = build_botanical_clean.build_botanical_clean()

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
    is_mainline = 'dnd' in lk['name'].lower() or 'circular' in lk['name'].lower()
    is_loop = 'loop' in lk['name'].lower()
    color = (255, 180, 0) if is_mainline else ((0, 255, 100) if is_loop else (0, 200, 255))
    width = 4 if is_mainline else 3
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
            for step in range(31):
                frac = step / 30.0
                ang = a0 + frac * (a1 - a0)
                px = c[0] + r * math.cos(ang)
                py = c[1] + r * math.sin(ang)
                pts.append(to_img(px, py))
            for i in range(len(pts) - 1):
                cv2.line(canvas, pts[i], pts[i+1], color, width)
        elif t == 'bezier':
            p0, p1, p2, p3 = g_prim['p0'], g_prim['p1'], g_prim['p2'], g_prim['p3']
            pts = []
            for step in range(21):
                u = step / 20.0
                u2 = u * u; u3 = u2 * u
                v = 1.0 - u; v2 = v * v; v3 = v2 * v
                bx = v3*p0[0] + 3*v2*u*p1[0] + 3*v*u2*p2[0] + u3*p3[0]
                by = v3*p0[1] + 3*v2*u*p1[1] + 3*v*u2*p2[1] + u3*p3[1]
                pts.append(to_img(bx, by))
            for i in range(len(pts) - 1):
                cv2.line(canvas, pts[i], pts[i+1], color, width)

out_file = 'C:/Users/rajku/.gemini/antigravity/brain/7fbe18dc-e823-4fc5-9f11-b73d94a0c585/verified_cloverleaf_full.jpg'
cv2.imwrite(out_file, canvas)
print(f"Saved {out_file}")
