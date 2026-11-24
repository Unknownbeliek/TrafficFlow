import sys; sys.path.insert(0, 'tools')
import math
import cv2
import numpy as np

img = cv2.imread('section_img/ITO_apple.png')
h, w, _ = img.shape
hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
sat = hsv[:, :, 1]
val = hsv[:, :, 2]

road_score = np.zeros((h, w), dtype=np.float32)
road_mask = (sat < 40) & (val > 65) & (val < 220)
road_score[road_mask] = 1.0

import sites
net = sites.build_ito()

# Sample points along all links in local coords (x, y)
sample_pts = []
for lk in net.links.values():
    for g in lk['geometry']:
        t = g['type']
        if t == 'line':
            ax, ay = g['a']
            bx, by = g['b']
            for step in range(8):
                frac = step / 7.0
                sample_pts.append((ax + frac*(bx - ax), ay + frac*(by - ay)))

sample_pts = np.array(sample_pts, dtype=np.float32)
print(f"Total road sample points: {len(sample_pts)}")

m_per_px = 0.61

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

print("Current uncalibrated ITO score [960, 536, 0.0]:", evaluate(960.0, 536.0, 0.0))

best_score = -1
best_params = None

for rot in np.linspace(-5, 15, 21):
    for ox in np.linspace(1010, 1070, 13):
        for oy in np.linspace(540, 600, 13):
            sc = evaluate(ox, oy, rot)
            if sc > best_score:
                best_score = sc
                best_params = (ox, oy, rot)

print(f"Best ITO params: ox={best_params[0]:.1f}, oy={best_params[1]:.1f}, rot={best_params[2]:.2f} deg with score={best_score:.4f}")
