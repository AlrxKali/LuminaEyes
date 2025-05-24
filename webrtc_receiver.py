import asyncio
import logging
import json
import multiprocessing as mp
import queue
from aiortc import RTCIceCandidate, RTCPeerConnection, RTCSessionDescription
from av import VideoFrame
import cv2
import numpy as np

# --- Global Variables for WebRTC ---
pcs = set()

# --- Configuration for logging ---
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("pc")
app_logger = logging.getLogger(__name__)
app_logger.setLevel(logging.DEBUG)

# --- Configuration ---
TRY_DISPLAY_WITH_OPENCV = True
MAX_FRAMES_TO_SAVE = 20

def display_process(frame_queue, stop_event):
    """Separate process for OpenCV display"""
    import cv2
    window_name = "Received WebRTC Stream"
    cv2.namedWindow(window_name, cv2.WINDOW_AUTOSIZE)
    print("Display process: Window created")
    
    frames_displayed = 0
    
    while not stop_event.is_set():
        try:
            # Try to get frame with timeout
            frame_data = frame_queue.get(timeout=0.1)
            
            if frame_data is None:  # Sentinel value
                break
                
            # Reconstruct numpy array from bytes
            frame = np.frombuffer(frame_data['data'], dtype=np.uint8).reshape(frame_data['shape'])
            
            cv2.imshow(window_name, frame)
            frames_displayed += 1
            
            if frames_displayed == 1:
                print("Display process: First frame displayed!")
            elif frames_displayed % 50 == 0:
                print(f"Display process: Displayed {frames_displayed} frames")
            
            key = cv2.waitKey(1) & 0xFF
            
            if key == ord('q'):
                print("Display process: 'q' pressed, stopping")
                stop_event.set()
                break
                
        except queue.Empty:
            # No frame available, still process window events
            if cv2.waitKey(1) & 0xFF == ord('q'):
                stop_event.set()
                break
        except Exception as e:
            print(f"Display process: Error: {e}")
            break
            
    print(f"Display process: Exiting after displaying {frames_displayed} frames")
    cv2.destroyAllWindows()

async def run_receiver():
    pc = RTCPeerConnection()
    pcs.add(pc)

    frame_counter = 0
    track_received_flag = False
    display_queue = None
    display_proc = None
    stop_event = None
    
    # Start display process if enabled
    if TRY_DISPLAY_WITH_OPENCV:
        # Use multiprocessing queue and event
        display_queue = mp.Queue(maxsize=5)
        stop_event = mp.Event()
        display_proc = mp.Process(target=display_process, args=(display_queue, stop_event))
        display_proc.start()
        app_logger.info("RECEIVER: Display process started")

    @pc.on("iceconnectionstatechange")
    async def on_iceconnectionstatechange():
        app_logger.info(f"RECEIVER: ICE connection state is {pc.iceConnectionState}")
        if pc.iceConnectionState == "failed":
            await pc.close()
            pcs.discard(pc)

    @pc.on("track")
    async def on_track(track):
        nonlocal frame_counter, track_received_flag
        track_received_flag = True
        app_logger.info(f"RECEIVER: Track {track.kind} received! ID: {track.id}")

        if track.kind == "video":
            app_logger.info("RECEIVER: Video track processing started.")
            saved_frame_count = 0
            
            while True:
                try:
                    app_logger.debug("RECEIVER: Attempting to receive frame from track...")
                    frame = await track.recv()
                    app_logger.debug(f"RECEIVER: Successfully received a frame object: type={type(frame)}")

                    if frame:
                        frame_counter += 1
                        if frame_counter % 10 == 0:
                            app_logger.info(f"RECEIVER: Received video frame {frame_counter}, PTS={frame.pts}, Time={frame.time}, Format={frame.format.name if frame.format else 'N/A'}")
                        
                        try:
                            app_logger.debug("RECEIVER: Converting frame to ndarray (bgr24)...")
                            img_bgr = frame.to_ndarray(format="bgr24")
                            app_logger.debug(f"RECEIVER: Frame converted to ndarray, shape={img_bgr.shape}.")
                            
                            # Add basic frame quality check
                            frame_mean = img_bgr.mean()
                            frame_std = img_bgr.std()
                            app_logger.debug(f"RECEIVER: Frame quality - mean: {frame_mean:.2f}, std: {frame_std:.2f}")
                            
                            # Display or save the frame
                            if TRY_DISPLAY_WITH_OPENCV and display_queue and not stop_event.is_set():
                                # Send frame to display process
                                try:
                                    # Clear old frames if queue is getting full
                                    while display_queue.qsize() >= 4:
                                        try:
                                            display_queue.get_nowait()
                                        except queue.Empty:
                                            break
                                    
                                    # Send frame data as dict with bytes
                                    frame_data = {
                                        'data': img_bgr.tobytes(),
                                        'shape': img_bgr.shape
                                    }
                                    display_queue.put_nowait(frame_data)
                                    
                                    # Log periodically
                                    if frame_counter % 50 == 0:
                                        app_logger.info(f"RECEIVER: Sent frame {frame_counter} to display process")
                                    
                                except queue.Full:
                                    app_logger.debug("RECEIVER: Display queue full, dropping frame")
                                
                                # Check if display process stopped
                                if stop_event.is_set():
                                    app_logger.info("RECEIVER: Display process stopped, ending video processing")
                                    break
                            else:
                                # Save frames to disk
                                if saved_frame_count < MAX_FRAMES_TO_SAVE:
                                    filename = f"received_frame_{saved_frame_count:03d}.png"
                                    try:
                                        cv2.imwrite(filename, img_bgr)
                                        app_logger.info(f"RECEIVER: Saved frame {saved_frame_count} as {filename}")
                                        saved_frame_count += 1
                                    except Exception as e:
                                        app_logger.error(f"RECEIVER: Error saving frame {filename}: {e}", exc_info=True)
                                elif saved_frame_count == MAX_FRAMES_TO_SAVE:
                                    app_logger.info(f"RECEIVER: Reached max frames to save ({MAX_FRAMES_TO_SAVE}). No longer saving.")
                                    saved_frame_count += 1
                            
                        except Exception as e:
                            app_logger.error(f"RECEIVER: Error converting frame to ndarray: {e}", exc_info=True)
                            continue

                    else:
                        app_logger.warning("RECEIVER: Received a None frame object from track.recv().")

                except Exception as e:
                    app_logger.error(f"RECEIVER: Error receiving frame from track: {e}", exc_info=True)
                    break
                    
            app_logger.info("RECEIVER: Video track processing loop ended.")
        
        @track.on("ended")
        async def on_ended():
            app_logger.info(f"RECEIVER: Track {track.kind} (ID: {track.id}) ended.")

    try:
        # 1. Wait for offer (manual input)
        app_logger.info("RECEIVER: Waiting for SDP Offer from Sender...")
        offer_json_str = await asyncio.get_event_loop().run_in_executor(
            None, lambda: input("RECEIVER: Paste SDP Offer from Sender here and press Enter:\n")
        )
        offer_data = json.loads(offer_json_str)
        offer = RTCSessionDescription(sdp=offer_data["sdp"], type=offer_data["type"])
        
        app_logger.info("RECEIVER: Setting remote description (offer)...")
        await pc.setRemoteDescription(offer)
        app_logger.info("RECEIVER: Remote description (offer) set successfully.")

        # 2. Create answer
        app_logger.info("RECEIVER: Creating SDP Answer...")
        answer = await pc.createAnswer()
        app_logger.info("RECEIVER: SDP Answer created. Setting local description (answer)...")
        await pc.setLocalDescription(answer)
        app_logger.info("RECEIVER: Local description (answer) set successfully.")

        print("-" * 20)
        print("RECEIVER: SDP Answer (copy everything below this line, including curly braces):")
        print(json.dumps({"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}))
        print("-" * 20)
        
        app_logger.info("RECEIVER: SDP exchange complete. Waiting for connection and tracks... Press Ctrl+C to stop.")
        
        # Keep running to receive video
        while True:
            await asyncio.sleep(5)
            app_logger.debug(f"RECEIVER: Main loop check. pc.iceConnectionState: {pc.iceConnectionState}, pc.connectionState: {pc.signalingState}")
            if not track_received_flag and pc.iceConnectionState in ["connected", "completed"]:
                app_logger.warning("RECEIVER: ICE connected/completed, but 'on_track' event was NOT fired yet.")
            if pc.iceConnectionState in ["failed", "closed", "disconnected"]:
                app_logger.warning(f"RECEIVER: ICE connection state is {pc.iceConnectionState}. Exiting main loop.")
                break
            # Check if display process stopped
            if stop_event and stop_event.is_set():
                app_logger.info("RECEIVER: Display process stopped. Exiting main loop.")
                break

    except KeyboardInterrupt:
        app_logger.info("RECEIVER: KeyboardInterrupt received.")
    except Exception as e:
        app_logger.error(f"RECEIVER: An error occurred in run_receiver: {e}", exc_info=True)
    finally:
        app_logger.info("RECEIVER: Closing peer connection and cleaning up...")
        
        # Stop display process if running
        if display_proc:
            if stop_event:
                stop_event.set()
            if display_queue:
                display_queue.put(None)  # Sentinel value
            display_proc.join(timeout=2.0)  # Wait for process to finish
            if display_proc.is_alive():
                display_proc.terminate()
            
        if pc and pc.signalingState != "closed":
            await pc.close()
        pcs.discard(pc)
        
        app_logger.info("RECEIVER: Cleanup complete. Exiting.")

if __name__ == "__main__":
    # Set multiprocessing start method
    mp.set_start_method('spawn', force=True)
    
    try:
        asyncio.run(run_receiver())
    except KeyboardInterrupt:
        app_logger.info("Receiver stopped by user (main).")
    except Exception as e:
        app_logger.critical(f"Receiver CRASHED (main): {e}", exc_info=True)