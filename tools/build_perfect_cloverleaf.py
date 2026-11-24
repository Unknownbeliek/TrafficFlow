import math
import cv2
import numpy as np

# Interchange center in satellite pixels:
# origin_px = [910.0, 522.0]
# rotation_deg = -6.0
# m_per_px = 0.8484

ox, oy = 910.0, 522.0
rot = -6.0
m_per_px = 0.8484
th = math.radians(rot)
c_th, s_th = math.cos(th), math.sin(th)

def to_img(x, y):
    ix = ox + (x * c_th - y * s_th) / m_per_px
    iy = oy + (x * s_th + y * c_th) / m_per_px
    return int(round(ix)), int(round(iy))

img = cv2.imread('section_img/Botanical_interchange_apple.png')
canvas = img.copy()

W = 3.5
gap = 2.5 * W # 8.75m median
half_road = gap / 2.0 + 2 * W # 4.375 + 7.0 = 11.375m
lane_out = gap / 2.0 + 1.5 * W # 9.625m (outer lane center)

# Mainline A (East-West):
for side in [-half_road, half_road]:
    cv2.line(canvas, to_img(-600, side), to_img(600, side), (255, 255, 255), 2)
# Mainline B (North-South):
for side in [-half_road, half_road]:
    cv2.line(canvas, to_img(side, -500), to_img(side, 500), (255, 255, 255), 2)

# The 4 Cloverleaf Quadrants and their 270-degree loops:
# Quadrant centers in local coordinates:
# SE loop: (+90.7, +103.8), R = 44.0m
# SW loop: (-119.6, +88.1), R = 44.0m
# NE loop: (+144.3, -97.9), R = 44.0m
# NW loop: (-117.5, -86.0), R = 44.0m

quads = {
    'SW': {'center': (-115.0, 90.0), 'r': 44.0, 'a0': 90.0, 'a1': 360.0},
    'SE': {'center': (95.0, 95.0), 'r': 44.0, 'a0': 180.0, 'a1': 450.0},
    'NE': {'center': (120.0, -95.0), 'r': 44.0, 'a0': 270.0, 'a1': 540.0},
    'NW': {'center': (-115.0, -85.0), 'r': 44.0, 'a0': 0.0, 'a1': 270.0},
}

for q_name, q in quads.items():
    cx, cy = q['center']
    r = q['r']
    a0 = q['a0']
    a1 = q['a1']
    
    # 270 degree arc
    pts = []
    for step in range(37):
        ang = math.radians(a0 + (a1 - a0) * step / 36.0)
        px = cx + r * math.cos(ang)
        py = cy + r * math.sin(ang)
        pts.append(to_img(px, py))
    for i in range(len(pts) - 1):
        cv2.line(canvas, pts[i], pts[i+1], (0, 255, 120), 4)

out_file = 'C:/Users/rajku/.gemini/antigravity/brain/7fbe18dc-e823-4fc5-9f11-b73d94a0c585/perfect_cloverleaf_preview.jpg'
cv2.imwrite(out_file, canvas)
print(f"Saved {out_file}")
