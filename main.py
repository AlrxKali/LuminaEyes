import cv2
import time
import threading
import numpy as np
import logging
from typing import Optional, Dict, Any, Set
import asyncio
import websockets
import json
import base64

from Pipeline import GStreamerCameraPipeline, CameraType
from gi.repository import Gst

Gst.init(None)

# --- Global State ---
latest_frame: Optional[np.ndarray] = None
frame_lock = threading.Lock() # GStreamer runs in its own thread
gst_pipeline_instance: Optional[GStreamerCameraPipeline] = None
active_ai_pipelines = []
clients: Set[websockets.WebSocketServerProtocol] = set()
streaming_active = False
ai_processing_task: Optional[asyncio.Task] = None
main_event_loop: Optional[asyncio.AbstractEventLoop] = None

# Default user preferences, can be updated via WebSocket
user_preferences: Dict[str, Any] = {
    "run_face_mesh": False,
    "run_hand_tracking": False,
    "run_object_detection": False,
    "source_type": "webcam",  # "webcam", "rtsp", "file", "test"
    "webcam_device": "/dev/video0",
    "rtsp_url": "rtsp://admin:admin@192.168.1.206:1935",
    "video_file_path": "myvideo.mp4",
    # Add any other relevant preferences here
}

# Configure basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Import your detector classes
from ai_pipelines.face_mesh import FaceMeshDetector
# from ai_pipelines.hand_tracking import HandTracker # Placeholder
# from ai_pipelines.object_detection import ObjectDetector # Placeholder

# --- WebSocket Handling ---
async def register_client(websocket: websockets.WebSocketServerProtocol):
    clients.add(websocket)
    logger.info(f"Client connected: {websocket.remote_address}")
    await notify_status(websocket) # Send current status to new client

async def unregister_client(websocket: websockets.WebSocketServerProtocol):
    clients.remove(websocket)
    logger.info(f"Client disconnected: {websocket.remote_address}")

async def notify_status(websocket: websockets.WebSocketServerProtocol, message_override: Optional[str] = None):
    global streaming_active, user_preferences
    if message_override:
        status_message = message_override
    elif not streaming_active:
        status_message = "Stream stopped. Waiting for configuration."
    elif not any(user_preferences.get(key) for key in ["run_face_mesh", "run_hand_tracking", "run_object_detection"]):
        status_message = "Streaming video, but no AI models selected."
    else:
        active_models = [model_name for model_name, active in user_preferences.items() 
                         if "run_" in model_name and active]
        status_message = f"Streaming with models: {', '.join(active_models)}"
    
    try:
        await websocket.send(json.dumps({"type": "status", "message": status_message, "config": user_preferences, "streaming_active": streaming_active}))
    except websockets.ConnectionClosed:
        pass # Client disconnected

async def notify_status_to_all_clients(message_override: Optional[str] = None):
    if clients: # Check if there are any clients
        # Create a list of tasks to send status to all clients
        tasks = [notify_status(client, message_override) for client in clients]
        await asyncio.gather(*tasks, return_exceptions=True) # Handle potential errors during send


# --- GStreamer and AI Processing ---
def gst_sample_to_opencv_bgr(sample: Gst.Sample) -> Optional[np.ndarray]:
    buf = sample.get_buffer()
    caps = sample.get_caps()
    if not caps or not buf:
        logger.error("GStreamer sample has no caps or buffer.")
        return None

    structure = caps.get_structure(0)
    format_str = structure.get_value("format")
    height = structure.get_value("height")
    width = structure.get_value("width")

    if format_str != "BGR":
        logger.warning(f"Expected BGR format, got {format_str}.")
    
    success, map_info = buf.map(Gst.MapFlags.READ)
    if not success:
        logger.error("Failed to map GStreamer buffer")
        buf.unmap(map_info) # Ensure unmap is called even on failure if map_info is valid
        return None

    frame_copy = np.ndarray((height, width, 3), dtype=np.uint8, buffer=map_info.data).copy()
    buf.unmap(map_info)
    return frame_copy

def on_new_frame_from_pipeline(appsink):
    global latest_frame, frame_lock
    sample = appsink.emit("pull-sample")
    if sample:
        frame = gst_sample_to_opencv_bgr(sample)
        if frame is not None:
            with frame_lock:
                latest_frame = frame.copy() # Ensure we have a distinct copy
    return Gst.FlowReturn.OK

def on_pipeline_error(bus, message): # Modified to match Gst.Bus.connect("message::error", ...)
    global main_event_loop
    err, debug_info = message.parse_error()
    logger.error(f"GStreamer Pipeline Error: {err}. Debug Info: {debug_info}")
    if main_event_loop:
        asyncio.run_coroutine_threadsafe(
            notify_status_to_all_clients(f"GStreamer Pipeline Error: {err}"), 
            main_event_loop
        )

def on_pipeline_eos(bus, message): # Modified to match Gst.Bus.connect("message::eos", ...)
    global main_event_loop
    logger.info("GStreamer Pipeline: End Of Stream.")
    if main_event_loop:
        asyncio.run_coroutine_threadsafe(
            notify_status_to_all_clients("GStreamer Pipeline: End Of Stream."),
            main_event_loop
        )
    # We might want to trigger a stop_video_streaming_loop here if EOS means the source is finished
    # For now, it depends on the source type. File sources will EOS, RTSP/webcam might not.


async def process_and_broadcast_frames():
    global latest_frame, frame_lock, streaming_active, user_preferences, active_ai_pipelines
    pTime = 0
    logger.info("AI Processing & Broadcast task started.")

    try:
        while streaming_active:
            current_frame_for_processing = None
            with frame_lock:
                if latest_frame is not None:
                    current_frame_for_processing = latest_frame.copy()
            
            if current_frame_for_processing is not None:
                # logger.debug(f"Processing frame. AI pipelines active: {len(active_ai_pipelines)}") # Uncomment for very verbose logging
                processed_frame = current_frame_for_processing
                all_ai_data = {}

                if active_ai_pipelines:
                    for pipeline_idx, ai_pipeline in enumerate(active_ai_pipelines):
                        try:
                            logger.info(f"Attempting to apply AI pipeline: {ai_pipeline.__class__.__name__}")
                            if hasattr(ai_pipeline, 'process_frame'):
                                processed_frame, data = ai_pipeline.process_frame(processed_frame)
                            elif hasattr(ai_pipeline, 'findFaceMesh'): # Legacy/alternative
                                processed_frame, data = ai_pipeline.findFaceMesh(processed_frame)
                            else:
                                data = {} # No specific data processing method found
                            all_ai_data[f"{ai_pipeline.__class__.__name__}_{pipeline_idx}"] = data
                            logger.info(f"Successfully applied AI pipeline: {ai_pipeline.__class__.__name__}")
                        except Exception as e_ai:
                            logger.error(f"Error during AI processing with {ai_pipeline.__class__.__name__}: {e_ai}", exc_info=True)
                            # Send error info within ai_data for this pipeline
                            all_ai_data[f"{ai_pipeline.__class__.__name__}_{pipeline_idx}"] = {"error": str(e_ai)}
                            # Decide if you want to continue sending the frame or skip
                            # For now, we continue with the frame possibly unprocessed by this failing AI pipeline
                else:
                    # logger.debug("No AI pipelines active, sending raw frame.") # Uncomment for very verbose logging
                    pass # No AI processing needed

                # Encode frame to JPEG
                encode_success, buffer = cv2.imencode('.jpg', processed_frame)
                if not encode_success:
                    logger.error("Failed to encode frame to JPEG.")
                    await asyncio.sleep(0.01) # Avoid busy loop if encoding fails
                    continue
                
                jpg_as_text = base64.b64encode(buffer).decode('utf-8')

                # Send frame and AI data to all clients
                if clients:
                    message = json.dumps({"type": "video_frame", "frame": jpg_as_text, "ai_data": all_ai_data, "timestamp": time.time()})
                    tasks = [client.send(message) for client in clients]
                    results = await asyncio.gather(*tasks, return_exceptions=True)
                    for i, res in enumerate(results):
                        if isinstance(res, Exception):
                            # Safely get client address for logging
                            client_list = list(clients)
                            client_addr = client_list[i].remote_address if i < len(client_list) else "unknown_client"
                            logger.warning(f"Failed to send frame to client {client_addr}: {res}")
                
                cTime = time.time()
                fps = 1 / (cTime - pTime) if (cTime - pTime) > 0 else 0
                pTime = cTime
                # logger.info(f"FPS: {int(fps)}") # Logging FPS can be verbose

                await asyncio.sleep(0.01) # Adjust for desired frame rate / responsiveness
            else:
                # logger.debug("No new frame from GStreamer, sleeping briefly.") # Uncomment for very verbose logging
                await asyncio.sleep(0.005) # Wait briefly if no new frame
    except asyncio.CancelledError:
        logger.info("AI Processing & Broadcast task explicitly cancelled.")
        raise # Re-raise CancelledError is important for proper task cleanup
    except Exception as e_loop:
        logger.error(f"Fatal exception in process_and_broadcast_frames loop: {e_loop}", exc_info=True)
        # This task will terminate. Consider notifying clients or attempting a graceful shutdown of the stream.
        await notify_status_to_all_clients(f"Critical Error: AI processing loop failed: {e_loop}")
        # global streaming_active # Can't assign to global here directly for stopping
        # Consider calling stop_video_streaming_loop, but need to be careful about re-entrancy
    finally:
        logger.info("AI Processing & Broadcast task finished.")

async def start_video_streaming_loop(prefs: Dict[str, Any]):
    global gst_pipeline_instance, streaming_active, active_ai_pipelines, ai_processing_task, user_preferences

    if streaming_active:
        logger.info("Streaming is already active. Stopping first.")
        await stop_video_streaming_loop() # Ensure clean state

    user_preferences.update(prefs) # Update global prefs with new settings
    logger.info(f"Starting video stream with preferences: {user_preferences}")
    active_ai_pipelines.clear()

    # Initialize selected AI pipelines
    if user_preferences.get("run_face_mesh"):
        logger.info("Initializing Face Mesh Detector...")
        active_ai_pipelines.append(FaceMeshDetector(maxFaces=2)) # Example params
    # Add other AI pipelines based on user_preferences
    # if user_preferences.get("run_hand_tracking"):
    #     active_ai_pipelines.append(HandTracker())
    # if user_preferences.get("run_object_detection"):
    #     active_ai_pipelines.append(ObjectDetector())

    if not active_ai_pipelines:
        logger.warning("No AI pipelines selected. Video will be streamed without AI processing.")

    gst_pipeline_instance = GStreamerCameraPipeline(name="websocket_video_feed")
    
    # GStreamer pipeline error and EOS are now connected with modified handlers
    gst_pipeline_instance.set_callbacks(on_error=None, on_eos=None) # Callbacks set directly on bus messages now

    source_type_pref = user_preferences.get("source_type", "webcam").lower()
    source_params = {}
    gst_cam_type = CameraType.WEBCAM

    if source_type_pref == "webcam":
        gst_cam_type = CameraType.WEBCAM
        source_params = {"device": user_preferences.get("webcam_device", "/dev/video0")}
    elif source_type_pref == "rtsp":
        gst_cam_type = CameraType.RTSP
        source_params = {
            "url": user_preferences.get("rtsp_url"), "latency": 200, "protocols": "tcp", "do-rtsp-keep-alive": True
        }
    elif source_type_pref == "file":
        gst_cam_type = CameraType.FILE
        source_params = {"filepath": user_preferences.get("video_file_path", "myvideo.mp4")}
    # Add other source types as needed

    appsink_name = "pythonsink"
    appsink_pipeline_config = (
        f"appsink name={appsink_name} emit-signals=true "
        f"max-buffers=1 drop=true sync=false caps=video/x-raw,format=BGR"
    )

    try:
        gst_pipeline_instance.build_pipeline(
            camera_type=gst_cam_type,
            source_params=source_params,
            sink_type=appsink_pipeline_config,
            processing_elements=""
        )
        
        appsink_el = gst_pipeline_instance.pipeline.get_by_name(appsink_name)
        if not appsink_el:
            logger.error(f"Failed to get appsink element '{appsink_name}'.")
            await notify_status_to_all_clients(f"Error: Failed to get appsink from GStreamer pipeline.")
            return
        appsink_el.connect("new-sample", on_new_frame_from_pipeline)

        # Connect bus messages for error and EOS
        bus = gst_pipeline_instance.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message::error", on_pipeline_error)
        bus.connect("message::eos", on_pipeline_eos)


        gst_pipeline_instance.start() # This starts the GStreamer GLib main loop in a separate thread
        streaming_active = True
        logger.info("GStreamer pipeline started for WebSocket streaming.")
        
        # Start the asyncio task for processing frames and broadcasting via WebSocket
        ai_processing_task = asyncio.create_task(process_and_broadcast_frames())
        await notify_status_to_all_clients()

    except Exception as e:
        logger.error(f"Failed to initialize or start GStreamer pipeline: {e}")
        streaming_active = False
        await notify_status_to_all_clients(f"Error starting GStreamer: {e}")


async def stop_video_streaming_loop():
    global gst_pipeline_instance, streaming_active, ai_processing_task, active_ai_pipelines, latest_frame

    logger.info("Attempting to stop video stream...")
    if not streaming_active and not gst_pipeline_instance and not ai_processing_task:
        logger.info("Stream already stopped or not initialized.")
        await notify_status_to_all_clients("Stream is not active.")
        return

    streaming_active = False # Signal the processing loop to stop

    if ai_processing_task:
        logger.info("Cancelling AI processing task...")
        ai_processing_task.cancel()
        try:
            await ai_processing_task
        except asyncio.CancelledError:
            logger.info("AI processing task cancelled successfully.")
        except Exception as e:
            logger.error(f"Exception while cancelling AI task: {e}")
        ai_processing_task = None

    if gst_pipeline_instance and gst_pipeline_instance.is_playing:
        logger.info("Stopping GStreamer pipeline...")
        gst_pipeline_instance.stop() # This should also stop its internal loop_thread
        logger.info("GStreamer pipeline stop command issued.")
    
    gst_pipeline_instance = None
    
    logger.info("Closing active AI pipelines...")
    for ai_pipe in active_ai_pipelines:
        if hasattr(ai_pipe, 'close'):
            try:
                logger.info(f"Calling close() on {ai_pipe.__class__.__name__}")
                ai_pipe.close()
            except Exception as e_close:
                logger.error(f"Error closing AI pipeline {ai_pipe.__class__.__name__}: {e_close}")
    active_ai_pipelines.clear()

    with frame_lock: # Clear the last frame
        latest_frame = None
    
    logger.info("Video stream stopped.")
    await notify_status_to_all_clients("Stream stopped.")


async def serve_websocket_commands(websocket: websockets.WebSocketServerProtocol, path: str):
    global user_preferences
    await register_client(websocket)
    try:
        async for message_str in websocket:
            try:
                message = json.loads(message_str)
                command = message.get("command")
                config = message.get("config", {})

                logger.info(f"Received command: {command} with config: {config if config else 'No config'}")

                if command == "start_stream":
                    # Update user_preferences with received config
                    # Sanitize/validate config as needed
                    user_preferences.update(config)
                    await start_video_streaming_loop(user_preferences)
                elif command == "stop_stream":
                    await stop_video_streaming_loop()
                elif command == "update_config": # For changing models without full stop/start
                    user_preferences.update(config)
                    logger.info(f"User preferences updated to: {user_preferences}")
                    # If streaming, potentially restart with new config or update on the fly
                    if streaming_active:
                        logger.info("Config updated while streaming. Restarting stream with new config.")
                        await start_video_streaming_loop(user_preferences) # Simple restart for now
                    else:
                       await notify_status_to_all_clients("Configuration updated. Stream is stopped.")
                elif command == "get_status":
                    await notify_status(websocket)
                else:
                    logger.warning(f"Unknown command received: {command}")
                    await websocket.send(json.dumps({"type": "error", "message": f"Unknown command: {command}"}))

            except json.JSONDecodeError:
                logger.error("Invalid JSON received from client.")
                await websocket.send(json.dumps({"type": "error", "message": "Invalid JSON format"}))
            except Exception as e:
                logger.error(f"Error processing command: {e}")
                await websocket.send(json.dumps({"type": "error", "message": f"Error processing command: {str(e)}"}))
    except websockets.exceptions.ConnectionClosedOK:
        logger.info(f"Client {websocket.remote_address} disconnected normally.")
    except websockets.exceptions.ConnectionClosedError as e:
        logger.error(f"Client {websocket.remote_address} connection closed with error: {e}")
    finally:
        await unregister_client(websocket)

async def main_async():
    global main_event_loop
    # Ensure Gst is initialized (already done globally, but good practice if moved)
    # Gst.init(None) 
    
    main_event_loop = asyncio.get_running_loop()

    host = "0.0.0.0" # Listen on all available interfaces
    port = 8765       # Standard WebSocket port, change if needed
    
    logger.info(f"Starting WebSocket server on ws://{host}:{port}")
    
    server = await websockets.serve(serve_websocket_commands, host, port)
    
    try:
        await server.wait_closed() # Keep the server running
    except KeyboardInterrupt:
        logger.info("Server shutting down on KeyboardInterrupt...")
    finally:
        # Graceful shutdown of streaming if active
        if streaming_active:
            logger.info("Shutting down active stream...")
            await stop_video_streaming_loop()
        
        server.close()
        await server.wait_closed() # Ensure server fully closed
        logger.info("WebSocket server shut down.")

if __name__ == "__main__":
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        logger.info("Application terminated by user.")
    except Exception as e:
        logger.critical(f"Unhandled exception in main: {e}", exc_info=True)