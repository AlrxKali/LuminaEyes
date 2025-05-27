import cv2
import logging

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

# Try a simpler pipeline that matches the working gst-launch-1.0 command more closely
rtsp_url = "rtsp://admin:admin@192.168.1.206:1935"

# Simpler pipeline - remove some of the extra parameters
simple_rtsp_pipeline = (
    f"rtspsrc location={rtsp_url} protocols=tcp latency=200 do-rtsp-keep-alive=true ! "
    f"rtph264depay ! h264parse ! avdec_h264 ! "
    f"videoconvert ! video/x-raw,format=BGR ! appsink"
)

logging.info(f"Trying simplified RTSP pipeline: {simple_rtsp_pipeline}")
cap = cv2.VideoCapture(simple_rtsp_pipeline, cv2.CAP_GSTREAMER)

if not cap.isOpened():
    logging.error("Failed to open simplified RTSP pipeline")
else:
    logging.info("Successfully opened simplified RTSP pipeline!")
    while True:
        ret, frame = cap.read()
        if ret:
            logging.info(f"Successfully read frame! Shape: {frame.shape}")
            cv2.imshow("RTSP Stream", frame)
            # Wait for 1ms and check if 'q' is pressed to quit
            if cv2.waitKey(1) & 0xFF == ord('q'):
                logging.info("'q' pressed, exiting.")
                break
        else:
            logging.error("Failed to read frame, stream might have ended or there's an error.")
            break  # Exit loop if no frame is read

    cap.release()
    cv2.destroyAllWindows()