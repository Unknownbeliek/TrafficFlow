import cv2
import numpy as np

img = cv2.imread('section_img/Botanical_interchange_apple.png')

# Let's inspect specific columns to find Mainline A centerline
def find_center_y(x, y_guess, window=60):
    col = img[y_guess - window : y_guess + window, x]
    # compute edge gradients
    gray = cv2.cvtColor(col.reshape(-1, 1, 3), cv2.COLOR_BGR2GRAY)
    grad = np.abs(np.diff(gray, axis=0))
    # print top gradient locations
    return y_guess

# Let's inspect crops along Mainline A:
# x=100 (West end)
# x=500
# x=880 (Interchange center)
# x=1300
# x=1800 (East end)

# Let's save small patches around these points to artifact directory with coordinate ticks
test_xs = [100, 500, 880, 1300, 1800]
y_centers = [540, 540, 520, 480, 360]

for x, yc in zip(test_xs, y_centers):
    patch = img[max(0, yc-80):min(1080, yc+80), max(0, x-80):min(1920, x+80)].copy()
    cv2.circle(patch, (80, 80), 3, (0, 0, 255), -1)
    cv2.putText(patch, f"({x},{yc})", (5, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
    cv2.imwrite(f"C:/Users/rajku/.gemini/antigravity/brain/7fbe18dc-e823-4fc5-9f11-b73d94a0c585/patch_A_x{x}.jpg", patch)

# Let's do the same for Mainline B:
test_ys = [80, 300, 520, 800, 1000]
x_centers = [970, 930, 880, 830, 770]

for y, xc in zip(test_ys, x_centers):
    patch = img[max(0, y-80):min(1080, y+80), max(0, xc-80):min(1920, xc+80)].copy()
    cv2.circle(patch, (80, 80), 3, (0, 0, 255), -1)
    cv2.putText(patch, f"({xc},{y})", (5, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
    cv2.imwrite(f"C:/Users/rajku/.gemini/antigravity/brain/7fbe18dc-e823-4fc5-9f11-b73d94a0c585/patch_B_y{y}.jpg", patch)

print("Saved patches for Mainline A and Mainline B")
