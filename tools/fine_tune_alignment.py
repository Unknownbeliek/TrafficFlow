import sys; sys.path.insert(0, 'tools')
import math
import cv2
import numpy as np

img = cv2.imread('section_img/Botanical_interchange_apple.png')
hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
road_mask = (hsv[:, :, 1] < 45) & (hsv[:, :, 2] > 65) & (hsv[:, :, 2] < 225)

# Measure along the two mainlines:
# Mainline A runs along local X from -600m to +600m
# Mainline B runs along local Y from -400m to +400m
xs = np.linspace(-550, 550, 100)
ys = np.linspace(-350, 350, 80)
m_per_px = 0.8484

best_score = -1
best_cfg = None

for rot in np.linspace(-8.0, -3.0, 26):
    th = math.radians(rot)
    cos_th = math.cos(th)
    sin_th = math.sin(th)
    
    for ox in np.linspace(865, 895, 16):
        for oy in np.linspace(530, 555, 13):
            # Sample points along Mainline A
            ix_A = np.round(ox + xs * cos_th / m_per_px).astype(int)
            iy_A = np.round(oy + xs * sin_th / m_per_px).astype(int)
            
            # Sample points along Mainline B
            ix_B = np.round(ox - ys * sin_th / m_per_px).astype(int)
            iy_B = np.round(oy + ys * cos_th / m_per_px).astype(int)
            
            val_A = (ix_A >= 0) & (ix_A < 1920) & (iy_A >= 0) & (iy_A < 1080)
            val_B = (ix_B >= 0) & (ix_B < 1920) & (iy_B >= 0) & (iy_B < 1080)
            
            score_A = road_mask[iy_A[val_A], ix_A[val_A]].mean() if val_A.sum() > 0 else 0
            score_B = road_mask[iy_B[val_B], ix_B[val_B]].mean() if val_B.sum() > 0 else 0
            
            total_score = score_A * 0.6 + score_B * 0.4
            if total_score > best_score:
                best_score = total_score
                best_cfg = (ox, oy, rot, score_A, score_B)

print(f"Optimal alignment: ox={best_cfg[0]:.1f}, oy={best_cfg[1]:.1f}, rot={best_cfg[2]:.2f} deg")
print(f"Mainline A road match: {best_cfg[3]*100:.1f}%, Mainline B road match: {best_cfg[4]*100:.1f}%")
