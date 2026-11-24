import cv2
import numpy as np

img = cv2.imread('section_img/Botanical_interchange_apple.png')

# Let's find the interchange center accurately.
# Look at the bridge overpass: where does the overpass bridge span cross the underpass?
# Let's crop around x in [800, 1000], y in [450, 600] and find the bridge structure
crop = img[400:650, 750:1050]
cv2.imwrite('C:/Users/rajku/.gemini/antigravity/brain/7fbe18dc-e823-4fc5-9f11-b73d94a0c585/interchange_center.jpg', crop)
print("Saved interchange_center.jpg")
