import cv2
import time

# --- Configuration ---
RTSP_URL = "rtsp://admin:admin@192.168.1.206:1935"
# If your camera stream path is different, you might need to append it
# e.g., RTSP_URL = "rtsp://admin:admin@192.168.1.206:1935/cam/realmonitor?channel=1&subtype=0"
# The exact path depends on your camera manufacturer and configuration.
# The port 1935 is often used for RTSP over TCP or for RTMP, make sure it's indeed RTSP.
# Standard RTSP port is 554. If 1935 doesn't work, try 554 or check camera docs.

RECONNECT_DELAY_SECONDS = 5  # How long to wait before trying to reconnect

def connect_to_rtsp(rtsp_url):
    """Attempts to connect to the RTSP stream."""
    print(f"Attempting to connect to RTSP stream: {rtsp_url}")
    cap = cv2.VideoCapture(rtsp_url)
    if not cap.isOpened():
        print(f"Error: Could not open RTSP stream at {rtsp_url}. Retrying in {RECONNECT_DELAY_SECONDS} seconds...")
        return None
    print("Successfully connected to RTSP stream.")
    return cap

def main():
    cap = None
    while True: # Main loop to attempt reconnection
        if cap is None or not cap.isOpened():
            cap = connect_to_rtsp(RTSP_URL)
            if cap is None:
                time.sleep(RECONNECT_DELAY_SECONDS)
                continue # Try to reconnect

        ret, frame = cap.read()

        if not ret:
            print("Error: Could not read frame. Stream might have ended or there's a network issue.")
            cap.release()
            cap = None # Signal to reconnect
            print(f"Attempting to reconnect in {RECONNECT_DELAY_SECONDS} seconds...")
            time.sleep(RECONNECT_DELAY_SECONDS)
            continue

        # --- Frame Processing (for this step, we just show it or print info) ---
        # Option 1: Display the frame
        cv2.imshow('RTSP Stream Test', frame)
        
        # Option 2: Print frame shape (useful if running headless)
        # print(f"Read frame with shape: {frame.shape}")

        # --- Quit Condition ---
        # Press 'q' to quit the video window
        if cv2.waitKey(1) & 0xFF == ord('q'):
            print("Quitting...")
            break
        
        # Optional: Add a small delay if CPU usage is too high, though cap.read() often has inherent delay
        # time.sleep(0.01) 

    if cap is not None:
        cap.release()
    cv2.destroyAllWindows()
    print("Stream closed and resources released.")

if __name__ == "__main__":
    main()