import math
import cv2
import numpy as np

# Image dimensions: 1920 x 1080
# Coordinate system:
# Let origin_px = [880.0, 545.0] (the grade-separated crossing)
# m_per_px = 0.8484
# rotation_deg = 0.0 (so local x is image +X/East, local y is image +Y/South!)
# This makes local meters directly map to image pixels without any distortion:
# ix = 880.0 + x / 0.8484
# iy = 545.0 + y / 0.8484

ox, oy = 880.0, 545.0
m_per_px = 0.8484

def to_px(x, y):
    return int(round(ox + x / m_per_px)), int(round(oy + y / m_per_px))

def from_px(ix, iy):
    return (ix - ox) * m_per_px, (iy - oy) * m_per_px

# Let's inspect the actual asphalt roads in the image:
# Mainline A (East-West expressway):
# Carriageway width is 2 lanes each way (each lane ~3.5m = 7m per side, median ~6m)
# West approach:
# Centerline at ix=50, iy=534 -> local x, y:
x_west, y_west = from_px(50, 534)
# Mid-west at ix=500, iy=565 -> local x, y:
x_midw, y_midw = from_px(500, 565)
# Interchange crossing at ix=880, iy=545 -> local (0, 0)
# Mid-east at ix=1300, iy=495 -> local x, y:
x_mide, y_mide = from_px(1300, 495)
# East approach at ix=1850, iy=380 -> local x, y:
x_east, y_east = from_px(1850, 380)

print(f"Mainline A West: ({x_west:.1f}, {y_west:.1f})")
print(f"Mainline A MidW: ({x_midw:.1f}, {y_midw:.1f})")
print(f"Mainline A Center: (0.0, 0.0)")
print(f"Mainline A MidE: ({x_mide:.1f}, {y_mide:.1f})")
print(f"Mainline A East: ({x_east:.1f}, {y_east:.1f})")

# Mainline B (North-South road):
# North approach at ix=950, iy=80:
x_north, y_north = from_px(950, 80)
# Crossing at (0, 0)
# South approach at ix=780, iy=1020:
x_south, y_south = from_px(780, 1020)

print(f"Mainline B North: ({x_north:.1f}, {y_north:.1f})")
print(f"Mainline B Center: (0.0, 0.0)")
print(f"Mainline B South: ({x_south:.1f}, {y_south:.1f})")

# Loops:
# SW loop center at ix=740, iy=610:
c_sw = from_px(740, 610)
# SE loop center at ix=980, iy=605:
c_se = from_px(980, 605)
# NE loop center at ix=960, iy=440:
c_ne = from_px(960, 440)
# NW loop center at ix=780, iy=450:
c_nw = from_px(780, 450)

print(f"SW loop: center={c_sw}, radius={50 * m_per_px:.1f}m")
print(f"SE loop: center={c_se}, radius={50 * m_per_px:.1f}m")
print(f"NE loop: center={c_ne}, radius={45 * m_per_px:.1f}m")
print(f"NW loop: center={c_nw}, radius={45 * m_per_px:.1f}m")
