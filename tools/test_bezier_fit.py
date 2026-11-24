import math
import cv2
import numpy as np

img = cv2.imread('section_img/Botanical_interchange_apple.png')
canvas = img.copy()

ox, oy = 880.0, 545.0
m_per_px = 0.8484

def to_px(x, y):
    return int(round(ox + x / m_per_px)), int(round(oy + y / m_per_px))

# Lane width ~ 3.5m. 2 lanes each direction = 7.0m. Median ~ 4.0m.
# Total half-road offset from centerline:
# Carriageway center is offset by ±(4.0/2 + 7.0/2) = ±5.5m.
# Or draw 2 lanes: inner lane at ±3.75m, outer lane at ±7.25m.

# Mainline A Bézier curves:
# Inbound west -> center (eastbound traffic)
# Center -> outbound east
# Inbound east -> center (westbound traffic)
# Center -> outbound west

# Let's test drawing the centerlines and carriageways on the canvas:
def draw_cubic_bezier(p0, p1, p2, p3, color, width=2):
    pts = []
    for step in range(31):
        u = step / 30.0
        u2 = u * u
        u3 = u2 * u
        v = 1.0 - u
        v2 = v * v
        v3 = v2 * v
        x = v3*p0[0] + 3*v2*u*p1[0] + 3*v*u2*p2[0] + u3*p3[0]
        y = v3*p0[1] + 3*v2*u*p1[1] + 3*v*u2*p2[1] + u3*p3[1]
        pts.append(to_px(x, y))
    for i in range(len(pts) - 1):
        cv2.line(canvas, pts[i], pts[i+1], color, width)

# Mainline A west half: (-704, -9) to (0, 0) via (-322, 17)
# Fit a cubic bezier:
p0_A_w = (-704.2, -9.3)
p1_A_w = (-350.0, 18.0)
p2_A_w = (-150.0, 10.0)
p3_A_w = (0.0, 0.0)

# Mainline A east half: (0, 0) to (823, -140) via (356, -42)
p0_A_e = (0.0, 0.0)
p1_A_e = (200.0, -15.0)
p2_A_e = (450.0, -55.0)
p3_A_e = (822.9, -140.0)

draw_cubic_bezier(p0_A_w, p1_A_w, p2_A_w, p3_A_w, (0, 255, 255), 3)
draw_cubic_bezier(p0_A_e, p1_A_e, p2_A_e, p3_A_e, (0, 255, 255), 3)

# Mainline B north half: (59.4, -394.5) to (0, 0)
p0_B_n = (59.4, -394.5)
p1_B_n = (45.0, -200.0)
p2_B_n = (15.0, -80.0)
p3_B_n = (0.0, 0.0)

# Mainline B south half: (0, 0) to (-84.8, 403.0)
p0_B_s = (0.0, 0.0)
p1_B_s = (-20.0, 120.0)
p2_B_s = (-50.0, 250.0)
p3_B_s = (-84.8, 403.0)

draw_cubic_bezier(p0_B_n, p1_B_n, p2_B_n, p3_B_n, (255, 200, 0), 3)
draw_cubic_bezier(p0_B_s, p1_B_s, p2_B_s, p3_B_s, (255, 200, 0), 3)

# Loops:
loops = [
    ((-118.8, 55.1), 42.4, (0, 255, 0)),
    ((84.8, 50.9), 42.4, (0, 255, 0)),
    ((67.9, -89.1), 38.2, (0, 255, 0)),
    ((-84.8, -80.6), 38.2, (0, 255, 0)),
]

for (cx, cy), r, col in loops:
    c_px = to_px(cx, cy)
    r_px = int(round(r / m_per_px))
    cv2.circle(canvas, c_px, r_px, col, 2)

out_file = 'C:/Users/rajku/.gemini/antigravity/brain/7fbe18dc-e823-4fc5-9f11-b73d94a0c585/overlay_perfect_test.jpg'
cv2.imwrite(out_file, canvas)
print(f"Saved {out_file}")
