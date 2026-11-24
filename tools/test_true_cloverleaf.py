import math
import cv2
import numpy as np

# Coordinates:
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

# Lane width 3.5m, gap = 8.75m. 2 lanes each way.
# Outer lane offset:
W = 3.5
gap = 2.5 * W # 8.75
lane_in = gap / 2.0 + W / 2.0 # inner lane center = 6.125
lane_out = gap / 2.0 + 1.5 * W # outer lane center = 9.625

# Draw Mainline A (East-West):
for side in [-lane_out, -lane_in, lane_in, lane_out]:
    p1 = to_img(-600, side)
    p2 = to_img(600, side)
    cv2.line(canvas, p1, p2, (255, 180, 0), 2)

# Draw Mainline B (North-South):
for side in [-lane_out, -lane_in, lane_in, lane_out]:
    p1 = to_img(side, -500)
    p2 = to_img(side, 500)
    cv2.line(canvas, p1, p2, (255, 200, 50), 2)

# 4 Cloverleaf Loops:
# Loop centers match the 4 green patches:
# NW Loop: center = (-70, -60), R = 45m
# NE Loop: center = (80, -65), R = 45m
# SE Loop: center = (70, 65), R = 45m
# SW Loop: center = (-70, 60), R = 45m

loops = [
    # (name, center, R, a0_deg, a1_deg)
    ("SW Loop (Eb -> Nb)", (-68.0, 58.0), 44.0, 90.0, 360.0), # 270 deg
    ("SE Loop (Nb -> Wb)", (68.0, 60.0), 44.0, 180.0, 450.0), # 270 deg
    ("NE Loop (Wb -> Sb)", (75.0, -62.0), 44.0, 270.0, 540.0), # 270 deg
    ("NW Loop (Sb -> Eb)", (-68.0, -60.0), 44.0, 0.0, 270.0), # 270 deg
]

for name, (cx, cy), R, a0, a1 in loops:
    pts = []
    for step in range(37):
        ang = math.radians(a0 + (a1 - a0) * step / 36.0)
        px = cx + R * math.cos(ang)
        py = cy + R * math.sin(ang)
        pts.append(to_img(px, py))
    for i in range(len(pts) - 1):
        cv2.line(canvas, pts[i], pts[i+1], (0, 255, 100), 3)

out_file = 'C:/Users/rajku/.gemini/antigravity/brain/7fbe18dc-e823-4fc5-9f11-b73d94a0c585/true_cloverleaf_test.jpg'
cv2.imwrite(out_file, canvas)
print(f"Saved {out_file}")
