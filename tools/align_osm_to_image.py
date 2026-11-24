import json
import math
import cv2
import numpy as np

with open('site-data/botanical_okhla/osm_raw.json') as f:
    d = json.load(f)

nodes = d['nodes']
ways = d['ways']

# Project all ways to meters
lat_c, lon_c = 28.5585, 77.3245
m_lat = 111320.0
m_lon = 111320.0 * math.cos(math.radians(lat_c))

polylines = []
for w in ways:
    pts = []
    for nid in w['nodes']:
        if nid in nodes:
            lat, lon = nodes[nid]
            x = (lon - lon_c) * m_lon
            y = (lat - lat_c) * m_lat
            pts.append((x, y))
    if len(pts) >= 2:
        polylines.append((w, pts))

# Sample points from polylines
sample_pts = []
for w, pts in polylines:
    for i in range(len(pts) - 1):
        x1, y1 = pts[i]
        x2, y2 = pts[i+1]
        for step in range(5):
            frac = step / 4.0
            sample_pts.append((x1 + frac*(x2 - x1), y1 + frac*(y2 - y1)))

sample_pts = np.array(sample_pts, dtype=np.float32)
print(f"Total OSM road sample points: {len(sample_pts)}")

# Load image
img = cv2.imread('section_img/Botanical_interchange_apple.png')
h, w, _ = img.shape
hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
road_mask = (hsv[:, :, 1] < 45) & (hsv[:, :, 2] > 65) & (hsv[:, :, 2] < 225)

# In Apple Maps / standard screenshots, North is UP:
# So local y (North) maps to -iy (upwards on screen), local x (East) maps to +ix (rightwards on screen)
# Let's search rotation angle theta around 0 (or slight tilt)
best_score = -1
best_cfg = None

for rot in np.linspace(-30, 30, 25):
    th = math.radians(rot)
    c_th, s_th = math.cos(th), math.sin(th)
    for m in [0.75, 0.85, 0.95, 1.05]:
        for ox in np.linspace(850, 1050, 9):
            for oy in np.linspace(450, 600, 7):
                xs = sample_pts[:, 0]
                ys = sample_pts[:, 1]
                # In standard image coords: ix = ox + (x*cos - y*sin)/m, iy = oy - (x*sin + y*cos)/m
                ixs = np.round(ox + (xs * c_th - ys * s_th) / m).astype(int)
                iys = np.round(oy - (xs * s_th + ys * c_th) / m).astype(int)
                
                val = (ixs >= 0) & (ixs < w) & (iys >= 0) & (iys < h)
                if val.sum() < len(sample_pts) * 0.4:
                    continue
                score = road_mask[iys[val], ixs[val]].mean()
                if score > best_score:
                    best_score = score
                    best_cfg = (ox, oy, rot, m)

print(f"Best OSM alignment: ox={best_cfg[0]:.1f}, oy={best_cfg[1]:.1f}, rot={best_cfg[2]:.1f} deg, m={best_cfg[3]:.2f}, score={best_score:.4f}")
