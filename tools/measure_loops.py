import cv2
import numpy as np

img = cv2.imread('section_img/Botanical_interchange_apple.png')

# Let's inspect the bottom-left loop (SW quadrant)
# It's centered around x in [700, 780], y in [550, 650]
crop_sw = img[530:670, 680:800]
cv2.imwrite('C:/Users/rajku/.gemini/antigravity/brain/7fbe18dc-e823-4fc5-9f11-b73d94a0c585/loop_sw.jpg', crop_sw)

# Let's inspect the bottom-right loop (SE quadrant)
# centered around x in [920, 1020], y in [530, 670]
crop_se = img[530:670, 920:1040]
cv2.imwrite('C:/Users/rajku/.gemini/antigravity/brain/7fbe18dc-e823-4fc5-9f11-b73d94a0c585/loop_se.jpg', crop_se)

print("Saved SW and SE loop crops")
