import cv2
import numpy as np

print("Attempting to create a named window...")
try:
    cv2.namedWindow("OpenCV Test Window", cv2.WINDOW_AUTOSIZE)
    print("Named window created.")
    
    # Create a black image
    img = np.zeros((200, 200, 3), dtype=np.uint8)
    cv2.putText(img, "Test", (50,100), cv2.FONT_HERSHEY_SIMPLEX, 1, (255,255,255), 2)
    
    print("Attempting to show image with cv2.imshow()...")
    cv2.imshow("OpenCV Test Window", img)
    print("cv2.imshow() executed. Waiting for key press (5 seconds timeout)...")
    
    key = cv2.waitKey(5000) # Wait for 5000 ms (5 seconds)
    
    if key == -1:
        print("cv2.waitKey() timed out (no key press).")
    else:
        print(f"cv2.waitKey() returned: {key}")
        
except Exception as e:
    print(f"ERROR during OpenCV display test: {e}")
finally:
    print("Attempting cv2.destroyAllWindows()...")
    cv2.destroyAllWindows()
    print("OpenCV display test finished.")