import math
import cv2
import numpy as np

# Test generating proper 270-degree cloverleaf loops
# Mainline A: East-West (at grade, y=0 in local coords, with 2 lanes each way)
# Mainline B: North-South (flyover, x=0 in local coords, with 2 lanes each way)
# Lane width W = 3.5m, gap = 2.5 * W = 8.75m.
# Mainline A eastbound: y = - (8.75/2 + 2*3.5/2) = -7.875m (heading +x)
# Mainline A westbound: y = + (8.75/2 + 2*3.5/2) = +7.875m (heading -x)
# Mainline B northbound: x = - (8.75/2 + 2*3.5/2) = -7.875m (heading -y)
# Mainline B southbound: x = + (8.75/2 + 2*3.5/2) = +7.875m (heading +y)

# Let's check loop centers on the 4 quadrants:
# Loop radius R = 45.0m
# 1. SW Loop: from Eastbound (heading +x) to Northbound (heading -y):
#    Vehicle enters from Mainline A eastbound at x = - off_d, loops 270 degrees clockwise, merges into Mainline B northbound
# 2. SE Loop: from Northbound (heading -y) to Westbound (heading -x):
#    Vehicle enters from Mainline B northbound, loops 270 degrees clockwise, merges into Mainline A westbound
# 3. NE Loop: from Westbound (heading -x) to Southbound (heading +y):
#    Vehicle enters from Mainline A westbound, loops 270 degrees clockwise, merges into Mainline B southbound
# 4. NW Loop: from Southbound (heading +y) to Eastbound (heading +x):
#    Vehicle enters from Mainline B southbound, loops 270 degrees clockwise, merges into Mainline A eastbound

# In each quadrant, the loop center is at:
# SW: (-R - gap, R + gap) or similar
# Let's inspect where the green loop islands are in local coordinates:
# origin_px = [910.0, 522.0], rotation_deg = -6.0, m_per_px = 0.8484
th = math.radians(-6.0)
c_th, s_th = math.cos(th), math.sin(th)
ox, oy = 910.0, 522.0
m_per_px = 0.8484

def to_local(ix, iy):
    dx = (ix - ox) * m_per_px
    dy = (iy - oy) * m_per_px
    # inverse rotation: R(-th)
    x = dx * c_th + dy * s_th
    y = -dx * s_th + dy * c_th
    return x, y

def to_img(x, y):
    ix = ox + (x * c_th - y * s_th) / m_per_px
    iy = oy + (x * s_th + y * c_th) / m_per_px
    return int(round(ix)), int(round(iy))

# Loop island centers from satellite image:
# SE: (1029.1, 632.5)
# SW: (780.6, 640.0)
# NE: (1067.1, 389.5)
# NW: (761.7, 435.7)

c_se_loc = to_local(1029.1, 632.5)
c_sw_loc = to_local(780.6, 640.0)
c_ne_loc = to_local(1067.1, 389.5)
c_nw_loc = to_local(761.7, 435.7)

print(f"SE loop local center: ({c_se_loc[0]:.1f}, {c_se_loc[1]:.1f})")
print(f"SW loop local center: ({c_sw_loc[0]:.1f}, {c_sw_loc[1]:.1f})")
print(f"NE loop local center: ({c_ne_loc[0]:.1f}, {c_ne_loc[1]:.1f})")
print(f"NW loop local center: ({c_nw_loc[0]:.1f}, {c_nw_loc[1]:.1f})")
