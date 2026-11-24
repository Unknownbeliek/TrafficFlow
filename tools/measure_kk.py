import cv2
import numpy as np

img = cv2.imread('section_img/KalindiKunj_apple.png')
h, w, _ = img.shape

# Let's inspect rows and columns to find the exact asphalt corridors:
# 1. Main bridge deck (top): around y = 250
# 2. Metro viaduct: around y = 280
# 3. Lower bridge / barrage: around y = 420
# 4. Canal: dark green water between y = 350 and y = 500 on the right half (x > 1100)
# 5. North canal road (towards Botanical): north bank of canal, y around 290 - 320 for x in [1150, 1919]
# 6. Faridabad road: south of junction (x around 1100 - 1200, y from 400 down to 800, then curves right to x=1800, y=850)

# Let's draw horizontal and vertical guidelines and save a grid image to verify exact coordinates!
grid = img.copy()
for x in range(0, w, 100):
    cv2.line(grid, (x, 0), (x, h), (100, 100, 100), 1)
    if x % 200 == 0:
        cv2.putText(grid, str(x), (x + 5, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

for y in range(0, h, 100):
    cv2.line(grid, (0, y), (w, y), (100, 100, 100), 1)
    if y % 200 == 0:
        cv2.putText(grid, str(y), (20, y - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

cv2.imwrite('C:/Users/rajku/.gemini/antigravity/brain/7fbe18dc-e823-4fc5-9f11-b73d94a0c585/kk_coordinate_grid.jpg', grid)
print('Saved kk_coordinate_grid.jpg')
