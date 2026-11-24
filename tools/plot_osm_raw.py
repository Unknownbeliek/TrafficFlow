import json
import math
import cv2
import numpy as np

with open('site-data/botanical_okhla/osm_raw.json') as f:
    d = json.load(f)

nodes = d['nodes']
ways = d['ways']

# In OSM:
# Mahamaya Flyover center is around:
lat0 = 28.5562
lon0 = 77.3252

m_lat = 111320.0
m_lon = 111320.0 * math.cos(math.radians(lat0))

canvas = np.zeros((1080, 1920, 3), dtype=np.uint8)

# Center on screen: (960, 540)
# Scale: 1 meter = 1.8 pixels
sc = 1.8

def to_screen(lat, lon):
    x_m = (lon - lon0) * m_lon
    y_m = (lat - lat0) * m_lat
    # Standard map: East is +X, North is -Y
    sx = int(round(960 + x_m * sc))
    sy = int(round(540 - y_m * sc))
    return sx, sy

for w in ways:
    hw = w['tags'].get('highway', '')
    is_link = 'link' in hw
    is_flyover = w['tags'].get('bridge') == 'yes' or int(w['tags'].get('layer', 0)) > 0
    
    color = (255, 200, 0) if is_flyover else ((0, 255, 120) if is_link else (100, 150, 255))
    width = 3 if is_flyover else (2 if is_link else 4)
    
    pts = [to_screen(*nodes[nid]) for nid in w['nodes'] if nid in nodes]
    for i in range(len(pts) - 1):
        cv2.line(canvas, pts[i], pts[i+1], color, width)

cv2.imwrite('C:/Users/rajku/.gemini/antigravity/brain/7fbe18dc-e823-4fc5-9f11-b73d94a0c585/osm_mahamaya_raw_plot.jpg', canvas)
print("Saved osm_mahamaya_raw_plot.jpg")
