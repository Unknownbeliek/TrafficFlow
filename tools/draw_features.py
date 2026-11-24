import cv2
import numpy as np

img = cv2.imread('section_img/Botanical_interchange_apple.png')
h, w, _ = img.shape

# Let's inspect the loop ramps and exact asphalt boundaries by saving a visualization
# with the real centers marked
vis = img.copy()

# Draw detected centers
cv2.circle(vis, (880, 545), 8, (0, 0, 255), -1) # interchange center
cv2.circle(vis, (740, 610), 6, (0, 255, 0), -1) # SW loop
cv2.circle(vis, (740, 610), 50, (0, 255, 0), 2)
cv2.circle(vis, (980, 605), 6, (0, 255, 0), -1) # SE loop
cv2.circle(vis, (980, 605), 50, (0, 255, 0), 2)
cv2.circle(vis, (960, 440), 6, (0, 255, 0), -1) # NE loop
cv2.circle(vis, (960, 440), 45, (0, 255, 0), 2)
cv2.circle(vis, (780, 450), 6, (0, 255, 0), -1) # NW loop
cv2.circle(vis, (780, 450), 45, (0, 255, 0), 2)

# Mainline A curve
pts_A = np.array([[100, 536], [500, 570], [880, 545], [1300, 495], [1800, 388]], np.int32)
cv2.polylines(vis, [pts_A], False, (255, 100, 0), 3)

# Mainline B curve
pts_B = np.array([[950, 80], [940, 300], [880, 545], [840, 800], [780, 1000]], np.int32)
cv2.polylines(vis, [pts_B], False, (255, 200, 0), 3)

out_path = 'C:/Users/rajku/.gemini/antigravity/brain/7fbe18dc-e823-4fc5-9f11-b73d94a0c585/interchange_features.jpg'
cv2.imwrite(out_path, vis)
print(f"Saved {out_path}")
