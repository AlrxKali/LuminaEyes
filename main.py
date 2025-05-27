import cv2
import time
import threading # Added for thread lock
import numpy as np # Added for frame manipulation
import logging   # Added for logging
from typing import Optional

# Import GStreamer related classes from your Pipeline.py
from Pipeline import GStreamerCameraPipeline, CameraType # Assuming Pipeline.py is in the same directory orPYTHONPATH
from gi.repository import Gst # Added for GStreamer specific types like Gst.FlowReturn


Gst.init(None)

latest_frame = None
frame_lock = threading.Lock()
gst_pipeline_instance = None 

# Configure basic logging for the main application
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Import your detector classes
from ai_pipelines.face_mesh import FaceMeshDetector

# Placeholder for loading configurations (e.g., from a file, GUI, or command-line args)
def get_user_preferences():
    # Example: Enable face mesh by default, others disabled
    # In a real app, this would read from a config file or CLI args
    return {
        "run_face_mesh": True,
        "run_hand_tracking": False,
        "run_object_detection": False,
        "source_type": "webcam", # "webcam", "rtsp", "file", "test"
        "webcam_device": "/dev/video0",
        "rtsp_url": 0 # "rtsp://admin:admin@192.168.1.206:1935"
    }

def gst_sample_to_opencv_bgr(sample: Gst.Sample) -> Optional[np.ndarray]:
    """Converts a Gst.Sample to an OpenCV (BGR) NumPy array."""
    buf = sample.get_buffer()
    caps = sample.get_caps()
    if not caps or not buf:
        logger.error("GStreamer sample has no caps or buffer.")
        return None

    structure = caps.get_structure(0)
    format_str = structure.get_value("format")
    height = structure.get_value("height")
    width = structure.get_value("width")

    # GStreamer appsink in the pipeline is set to BGR, so direct mapping.
    # If it were RGB, conversion would be needed: frame = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
    if format_str != "BGR":
        logger.warning(f"Expected BGR format from GStreamer, but got {format_str}. Colors might be incorrect.")
        # Potentially add a conversion here if you often get other formats
        # e.g., if format_str == "RGB":
        #    # map buffer, create np.ndarray, then cv2.cvtColor(..., cv2.COLOR_RGB2BGR)

    success, map_info = buf.map(Gst.MapFlags.READ)
    if not success:
        logger.error("Failed to map GStreamer buffer")
        return None

    # Create a NumPy array from the buffer data
    # This creates a view. A copy is essential if the frame is used after buf.unmap()
    # or if the AI models modify the frame in place.
    image = np.ndarray(
        (height, width, 3),  # Assuming 3 channels for BGR (or RGB)
        dtype=np.uint8,
        buffer=map_info.data
    )
    
    frame_copy = image.copy() # Make a copy to own the data
    buf.unmap(map_info)
    return frame_copy

def on_new_frame_from_pipeline(appsink):
    """Callback function for GStreamer appsink's 'new-sample' signal"""
    global latest_frame, frame_lock
    sample = appsink.emit("pull-sample")
    if sample:
        frame = gst_sample_to_opencv_bgr(sample)
        if frame is not None:
            with frame_lock:
                latest_frame = frame
    return Gst.FlowReturn.OK # Important for GStreamer to know processing was okay

def on_pipeline_error(error, debug_info):
    logger.error(f"GStreamer Pipeline Error: {error}. Debug Info: {debug_info}")

def on_pipeline_eos():
    logger.info("GStreamer Pipeline: End Of Stream.")
    # You might want to signal the main loop to exit here
    # For now, it will just log. The main loop continues until 'q' is pressed.

def main():
    global latest_frame, frame_lock, gst_pipeline_instance
    user_prefs = get_user_preferences()
    active_ai_pipelines = []

    cv2.namedWindow("Combined Output", cv2.WINDOW_AUTOSIZE)
    cv2.waitKey(1)

    # Initialize selected AI pipelines
    if user_prefs.get("run_face_mesh"):
        logger.info("Initializing Face Mesh Detector...")
        active_ai_pipelines.append(FaceMeshDetector(maxFaces=2))
    
    # if user_prefs.get("run_hand_tracking"):
    #     logger.info("Initializing Hand Tracker...")
    #     active_ai_pipelines.append(HandTracker())
        
    # if user_prefs.get("run_object_detection"):
    #     logger.info("Initializing Object Detector...")
    #     active_ai_pipelines.append(ObjectDetector())

    if not active_ai_pipelines:
        logger.warning("No AI pipelines selected. Video will be shown without AI processing.")
        # We can still run the GStreamer pipeline to just display video

    # --- GStreamer Pipeline Setup ---
    gst_pipeline_instance = GStreamerCameraPipeline(name="main_video_feed")
    gst_pipeline_instance.set_callbacks(on_error=on_pipeline_error, on_eos=on_pipeline_eos)

    source_type_pref = user_prefs.get("source_type", "webcam").lower()
    source_params = {}
    gst_cam_type = CameraType.WEBCAM # Default

    if source_type_pref == "webcam":
        gst_cam_type = CameraType.WEBCAM
        source_params = {"device": user_prefs.get("webcam_device", "/dev/video0")}
        logger.info(f"Configuring GStreamer for Webcam: {source_params['device']}")
    elif source_type_pref == "rtsp":
        gst_cam_type = CameraType.RTSP
        source_params = {
            "url": user_prefs.get("rtsp_url"),
            "latency": 200, # Example, make configurable if needed
            "protocols": "tcp" # Example
        }
        logger.info(f"Configuring GStreamer for RTSP: {source_params['url']}")
    elif source_type_pref == "file":
        gst_cam_type = CameraType.FILE
        source_params = {"filepath": user_prefs.get("video_file_path", "myvideo.mp4")} # Add "video_file_path" to prefs
        logger.info(f"Configuring GStreamer for File: {source_params['filepath']}")
    # Add other source types (TEST, CUSTOM) as needed

    # We will define an appsink directly in the pipeline string passed to build_pipeline.
    # This appsink will provide frames to our `on_new_frame_from_pipeline` callback.
    # The format BGR is generally what OpenCV expects.
    appsink_name = "pythonsink"
    appsink_pipeline_config = (
        f"appsink name={appsink_name} emit-signals=true "
        f"max-buffers=1 drop=true sync=false caps=video/x-raw,format=BGR"
    )

    try:
        gst_pipeline_instance.build_pipeline(
            camera_type=gst_cam_type,
            source_params=source_params,
            sink_type=appsink_pipeline_config, # Key change: sink_type IS our appsink string
            processing_elements="" # e.g., "videoscale ! video/x-raw,width=320,height=240"
        )

        # Get the appsink element by name and connect the callback
        appsink_el = gst_pipeline_instance.pipeline.get_by_name(appsink_name)
        if not appsink_el:
            logger.error(f"Failed to get appsink element '{appsink_name}' from pipeline. Check pipeline construction.")
            return
        appsink_el.connect("new-sample", on_new_frame_from_pipeline)
        
        gst_pipeline_instance.start()
        logger.info("GStreamer pipeline started.")

    except Exception as e:
        logger.error(f"Failed to initialize or start GStreamer pipeline: {e}")
        return
    # --- End GStreamer Pipeline Setup ---

    pTime = 0

    try:
        while True:
            current_frame_for_processing = None
            with frame_lock:
                if latest_frame is not None:
                    # Make a copy for AI processing to avoid race conditions if GStreamer updates latest_frame
                    current_frame_for_processing = latest_frame.copy()
            
            if current_frame_for_processing is not None:
                processed_frame = current_frame_for_processing # This will be modified by AI pipelines
                all_data = {} # To store data from all pipelines for this frame

                if active_ai_pipelines: # Only process if AI pipelines are active
                    for pipeline_idx, ai_pipeline in enumerate(active_ai_pipelines):
                        if hasattr(ai_pipeline, 'process_frame'):
                            processed_frame, data = ai_pipeline.process_frame(processed_frame)
                            all_data[f"ai_pipeline_{pipeline_idx}_{ai_pipeline.__class__.__name__}"] = data
                        elif hasattr(ai_pipeline, 'findFaceMesh'): # Legacy support for findFaceMesh
                            processed_frame, data = ai_pipeline.findFaceMesh(processed_frame)
                            all_data[f"ai_pipeline_{pipeline_idx}_{ai_pipeline.__class__.__name__}"] = data
                
                # Calculate and display FPS
                cTime = time.time()
                fps = 1 / (cTime - pTime) if (cTime - pTime) > 0 else 0
                pTime = cTime
                cv2.putText(processed_frame, f'FPS: {int(fps)} ({processed_frame.shape[1]}x{processed_frame.shape[0]})', 
                            (20, 70), cv2.FONT_HERSHEY_PLAIN, 2, (0, 255, 0), 2)

                cv2.imshow("Combined Output", processed_frame)
            else:
                # Optional: Add a small sleep if no frame yet, to prevent busy-waiting in main thread
                # However, GStreamer callback should provide frames. If it's too slow, this might indicate
                # an issue with the GStreamer pipeline or system performance.
                time.sleep(0.001) # 1 ms sleep

            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                logger.info("'q' pressed, exiting...")
                break
            # Add other key handling if needed

    finally:
        logger.info("Shutting down...")
        if gst_pipeline_instance and gst_pipeline_instance.is_playing:
            logger.info("Stopping GStreamer pipeline...")
            gst_pipeline_instance.stop()
        cv2.destroyAllWindows()
        logger.info("Application terminated.")

if __name__ == "__main__":
    main()