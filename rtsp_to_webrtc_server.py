import asyncio
import cv2
import logging
import json
import time
import fractions
import os # <-- Import os
import numpy as np # <-- Import numpy for black frame
from aiortc import RTCIceCandidate, RTCPeerConnection, RTCSessionDescription
from aiortc.contrib.media import MediaStreamTrack, MediaPlayer, MediaRelay
from av import VideoFrame 

# --- FFmpeg options (set before first VideoCapture call) ---
# Attempt to use TCP for RTSP and increase timeout (10 seconds)
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|timeout;10000000"

# --- Configuration ---
RTSP_URL = "rtsp://admin:admin@192.168.1.206:1935" 
# As before, ensure this URL is correct and the stream is active.

# --- Global Variables for WebRTC ---
pcs = set() # Set to keep track of peer connections

class RTSPVideoTrack(MediaStreamTrack):
    """
    A video track that sources its frames from an RTSP stream via OpenCV.
    """
    kind = "video"

    def __init__(self, rtsp_url):
        super().__init__()
        self.cap = None
        self.rtsp_url = rtsp_url
        self._frame_counter = 0 
        self._start_time = None
        self._last_frame_time = 0
        self.target_fps = 15 # Target FPS for black frames, if needed
        self.placeholder_frame = None
        self.frame_width = 640 # Desired width for placeholder
        self.frame_height = 480 # Desired height for placeholder
        self._consecutive_read_failures = 0
        self._max_consecutive_read_failures = 10 # Try for a bit before sending black frames

    async def _ensure_capture_started(self):
        if self.cap and self.cap.isOpened():
            return True
        
        logging.info(f"RTSPVideoTrack: Attempting to connect to RTSP stream: {self.rtsp_url}")
        # Explicitly use FFmpeg backend
        self.cap = cv2.VideoCapture(self.rtsp_url, cv2.CAP_FFMPEG) 
        
        if self.cap.isOpened():
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1) # Keep buffer small
            # Try to get frame dimensions for placeholder
            # ret_w = self.cap.get(cv2.CAP_PROP_FRAME_WIDTH)
            # ret_h = self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
            # if ret_w > 0 and ret_h > 0:
            #     self.frame_width = int(ret_w)
            #     self.frame_height = int(ret_h)
            #     logging.info(f"RTSP stream opened with resolution: {self.frame_width}x{self.frame_height}")
            # else: # Fallback if dimensions can't be read immediately
            #     logging.warning(f"Could not get dimensions from RTSP, using default {self.frame_width}x{self.frame_height}")

            logging.info(f"RTSPVideoTrack: Successfully connected to RTSP stream. Using resolution {self.frame_width}x{self.frame_height} for placeholders.")
            self._consecutive_read_failures = 0 # Reset on successful connect
            if self._start_time is None: # Initialize start time on first successful connect
                self._start_time = time.time()
            return True
        else:
            logging.error(f"RTSPVideoTrack: Error: Could not open RTSP stream at {self.rtsp_url}")
            if self.cap: # Release if object exists but not opened
                self.cap.release()
            self.cap = None
            return False

    def _create_black_frame(self):
        if self.placeholder_frame is None:
            # Create a black BGR frame
            black_img_bgr = np.zeros((self.frame_height, self.frame_width, 3), dtype=np.uint8)
            # Convert to RGB for PyAV
            black_img_rgb = cv2.cvtColor(black_img_bgr, cv2.COLOR_BGR2RGB)
            self.placeholder_frame = VideoFrame.from_ndarray(black_img_rgb, format="rgb24")
        
        # Update PTS for the black frame
        current_time = time.time()
        if self._start_time is None: self._start_time = current_time # Should have been set
        
        elapsed_time = current_time - self._start_time
        self.placeholder_frame.pts = int(elapsed_time * 90000) 
        self.placeholder_frame.time_base = fractions.Fraction(1, 90000)
        return self.placeholder_frame

    async def recv(self):
        if not await self._ensure_capture_started():
            # If capture couldn't start even after an attempt, send black frame
            logging.warning("RTSPVideoTrack: Capture not started, sending black frame.")
            await asyncio.sleep(1.0 / self.target_fps) # Pace the black frames
            return self._create_black_frame()

        ret, frame = self.cap.read()

        if not ret or frame is None or frame.size == 0:
            self._consecutive_read_failures += 1
            logging.warning(f"RTSPVideoTrack: Could not read frame from RTSP (failure {self._consecutive_read_failures}).")
            
            if self.cap: # Attempt to release and nullify to force re-check/re-open on next recv
                self.cap.release()
                self.cap = None
            
            await asyncio.sleep(0.1) # Small delay before returning black frame

            if self._consecutive_read_failures > self._max_consecutive_read_failures:
                logging.error(f"RTSPVideoTrack: Max consecutive read failures reached. Sending black frame.")
            
            await asyncio.sleep(1.0 / self.target_fps) # Pace the black frames
            return self._create_black_frame()

        # Valid frame received
        self._consecutive_read_failures = 0 # Reset counter
        self._frame_counter += 1
        if self._frame_counter % 100 == 0:
            logging.debug(f"RTSPVideoTrack: Sending frame {self._frame_counter}")

        try:
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            video_frame = VideoFrame.from_ndarray(frame_rgb, format="rgb24")
            
            current_time = time.time()
            if self._start_time is None: self._start_time = current_time # Should have been set
            
            elapsed_time = current_time - self._start_time
            video_frame.pts = int(elapsed_time * 90000) 
            video_frame.time_base = fractions.Fraction(1, 90000)
            
            # Store the actual frame dimensions if we get a good frame
            # This is a bit late but better than never if initial read failed
            if frame.shape[0] != self.frame_height or frame.shape[1] != self.frame_width:
                self.frame_height, self.frame_width = frame.shape[0], frame.shape[1]
                self.placeholder_frame = None # Force recreation of placeholder with new dims
                logging.info(f"RTSPVideoTrack: Updated frame dimensions to {self.frame_width}x{self.frame_height}")


            return video_frame
        except Exception as e:
            logging.error(f"RTSPVideoTrack: Error processing valid frame: {e}", exc_info=True)
            # If processing fails, fall back to black frame for this instance
            await asyncio.sleep(1.0 / self.target_fps)
            return self._create_black_frame()

    async def stop(self):
        await super().stop()
        if self.cap:
            self.cap.release()
            self.cap = None
        logging.info("RTSPVideoTrack: Track stopped and RTSP capture released.")

async def run_sender():
    pc = RTCPeerConnection()
    pcs.add(pc)

    # Configure logging
    logging.basicConfig(level=logging.INFO) # Keep INFO for general, DEBUG for aiortc if needed
    # logging.getLogger("aiortc").setLevel(logging.DEBUG) # Uncomment for very verbose WebRTC logs
    # logging.getLogger("aioice").setLevel(logging.DEBUG) # Uncomment for very verbose ICE logs
    root_logger = logging.getLogger("root") # Our application/script specific logs
    root_logger.setLevel(logging.INFO) # Set our script's logs to INFO

    @pc.on("icecandidate")
    async def on_icecandidate(candidate):
        if candidate:
            # For Phase 0, we just print. Later, this sends to signaling server.
            print(f"SENDER ICE Candidate: {candidate}") # Keep this for debugging ICE

    # Create and add video track
    # The RTSPVideoTrack will now handle its own reconnections more robustly.
    video_track = RTSPVideoTrack(RTSP_URL)
    
    # No need to call video_track.start_capture() here, recv will handle it.
    pc.addTrack(video_track)

    try:
        root_logger.info("SENDER: Creating SDP Offer...")
        offer = await pc.createOffer()
        await pc.setLocalDescription(offer)
        root_logger.info("SENDER: SDP Offer created.")

        print("-" * 20)
        print("SENDER: SDP Offer (copy everything below this line, including curly braces):")
        print(json.dumps({"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}))
        print("-" * 20)

        answer_json_str = await asyncio.get_event_loop().run_in_executor(
            None, lambda: input("SENDER: Paste SDP Answer from Receiver here and press Enter:\n")
        )
        
        answer_data = json.loads(answer_json_str)
        answer = RTCSessionDescription(sdp=answer_data["sdp"], type=answer_data["type"])
        await pc.setRemoteDescription(answer)
        root_logger.info("SENDER: Remote description (answer) set.")

        root_logger.info("SENDER: Streaming video... Press Ctrl+C to stop.")
        while True:
            await asyncio.sleep(5) # Main loop doesn't need to do much now, track handles itself
            # We can add a check here to see if the pc connection is still alive if needed
            if pc.iceConnectionState in ["failed", "disconnected", "closed"]:
                root_logger.warning(f"SENDER: PeerConnection state is {pc.iceConnectionState}. Stopping.")
                break
            # Check if the track itself has decided it's permanently failed (optional, advanced)
            # For now, we rely on it sending black frames if RTSP is dead.

    except KeyboardInterrupt:
        root_logger.info("SENDER: KeyboardInterrupt received.")
    finally:
        root_logger.info("SENDER: Closing peer connection and track...")
        if video_track: # Ensure video_track exists
             await video_track.stop() # Gracefully stop the track
        if pc and pc.signalingState != "closed": # Check if pc exists and not already closed
            await pc.close()
        pcs.discard(pc)
        root_logger.info("SENDER: Cleanup complete. Exiting.")

if __name__ == "__main__":
    try:
        asyncio.run(run_sender())
    except KeyboardInterrupt:
        logging.getLogger("root").info("Sender stopped by user (main).")
    except Exception as e:
        logging.getLogger("root").critical(f"Sender CRASHED (main): {e}", exc_info=True)
