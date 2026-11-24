import json
import math
import cv2
import numpy as np

img = cv2.imread('section_img/Botanical_interchange_apple.png')
h, w, _ = img.shape
hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
sat = hsv[:, :, 1]
val = hsv[:, :, 2]

# Asphalt road score: high value, low saturation
# Score each pixel: 1 if it looks like road/bridge asphalt, 0 otherwise
road_score = np.zeros((h, w), dtype=np.float32)
road_mask = (sat < 40) & (val > 65) & (val < 220)
road_score[road_mask] = 1.0

with open('site-data/botanical_okhla/network.json') as f:
    net = json.load(f)

# Sample points along all links in local coords (x, y)
sample_pts = []
for lk in net['links']:
    for g in lk['geometry']:
        t = g['type']
        if t == 'line':
            ax, ay = g['a']
            bx, by = g['b']
            for step in range(10):
                frac = step / 9.0
                sample_pts.append((ax + frac*(bx - ax), ay + frac*(by - ay)))
        elif t == 'arc':
            c = g['c']
            r = g['r']
            a0 = math.radians(g['a0'])
            a1 = math.radians(g['a1'])
            for step in range(10):
                frac = step / 9.0
                ang = a0 + frac * (a1 - a0)
                sample_pts.append((c[0] + r*math.cos(ang), c[1] + r*math.sin(ang)))

sample_pts = np.array(sample_pts, dtype=np.float32)
print(f"Total road sample points: {len(sample_pts)}")

m_per_px = 0.8484

def evaluate(ox, oy, rot):
    th = math.radians(rot)
    cos_th = math.cos(th)
    sin_th = math.sin(th)
    
    xs = sample_pts[:, 0]
    ys = sample_pts[:, 1]
    
    ixs = np.round(ox + (xs * cos_th - ys * sin_th) / m_per_px).astype(int)
    iys = np.round(oy + (xs * sin_th + ys * cos_th) / m_per_px).astype(int)
    
    valid = (ixs >= 0) & (ixs < w) & (iys >= 0) & (iys < h)
    if valid.sum() == 0:
        return 0.0
    return road_score[iys[valid], ixs[valid]].mean()

# Test original
print("Original score [1023.5, 562.2, 42.3]:", evaluate(1023.5, 562.2, 42.3))

best_score = -1
best_params = None

for rot in np.linspace(-12, 0, 25):
    for ox in np.linspace(840, 920, 17):
        for oy in np.linspace(500, 560, 13):
            sc = evaluate(ox, oy, rot)
            if sc > best_score:
                best_score = sc
                best_params = (ox, oy, rot)

print(f"Best params: ox={best_params[0]:.1f}, oy={best_params[1]:.1f}, rot={best_params[2]:.2f} deg with score={best_score:.4f}")
