import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst, GLib
import threading
import logging
from enum import Enum
from typing import Optional, Callable, Dict, Any

# Initialize GStreamer
Gst.init(None)

class CameraType(Enum):
    """Enumeration for different camera types"""
    WEBCAM = "webcam"
    RTSP = "rtsp"
    FILE = "file"
    TEST = "test"
    CUSTOM = "custom"

class GStreamerCameraPipeline:
    """
    Flexible GStreamer pipeline class for processing various camera streams.
    
    Supports:
    - Webcams (V4L2)
    - RTSP streams
    - Video files
    - Test sources
    - Custom pipeline strings
    """
    
    def __init__(self, name: str = "camera_pipeline"):
        """
        Initialize the GStreamer pipeline.
        
        Args:
            name: Name for the pipeline
        """
        self.name = name
        self.pipeline = None
        self.bus = None
        self.loop = None
        self.loop_thread = None
        self.is_playing = False
        
        # Callbacks
        self.on_frame_callback = None
        self.on_error_callback = None
        self.on_eos_callback = None
        
        # Pipeline elements
        self.source = None
        self.sink = None
        
        # Logging
        self.logger = logging.getLogger(f"GStreamerPipeline.{name}")
        
    def build_pipeline(self, camera_type: CameraType, source_params: Dict[str, Any], 
                      sink_type: str = "autovideosink", processing_elements: str = ""):
        """
        Build a GStreamer pipeline based on camera type and parameters.
        
        Args:
            camera_type: Type of camera source
            source_params: Parameters specific to the camera type
            sink_type: Type of sink to use (default: autovideosink)
            processing_elements: Additional GStreamer elements for processing
        """
        try:
            # Create pipeline string based on camera type
            if camera_type == CameraType.WEBCAM:
                pipeline_str = self._build_webcam_pipeline(source_params, sink_type, processing_elements)
            elif camera_type == CameraType.RTSP:
                pipeline_str = self._build_rtsp_pipeline(source_params, sink_type, processing_elements)
            elif camera_type == CameraType.FILE:
                pipeline_str = self._build_file_pipeline(source_params, sink_type, processing_elements)
            elif camera_type == CameraType.TEST:
                pipeline_str = self._build_test_pipeline(source_params, sink_type, processing_elements)
            elif camera_type == CameraType.CUSTOM:
                pipeline_str = source_params.get("pipeline", "")
            else:
                raise ValueError(f"Unsupported camera type: {camera_type}")
            
            self.logger.info(f"Building pipeline: {pipeline_str}")
            
            # Create pipeline
            self.pipeline = Gst.parse_launch(pipeline_str)
            self.pipeline.set_name(self.name)
            
            # Set up bus for messages
            self.bus = self.pipeline.get_bus()
            self.bus.add_signal_watch()
            self.bus.connect("message", self._on_message)
            
            self.logger.info("Pipeline built successfully")
            
        except Exception as e:
            self.logger.error(f"Failed to build pipeline: {str(e)}")
            raise
    
    def _build_webcam_pipeline(self, params: Dict[str, Any], sink: str, processing: str) -> str:
        """Build pipeline string for webcam source"""
        device = params.get("device", "/dev/video0")
        width = params.get("width", 640)
        height = params.get("height", 480)
        framerate = params.get("framerate", 30)
        
        pipeline = f"v4l2src device={device} ! "
        pipeline += f"video/x-raw,width={width},height={height},framerate={framerate}/1 ! "
        pipeline += "videoconvert ! "
        
        if processing:
            pipeline += f"{processing} ! "
        
        pipeline += sink
        
        return pipeline
    
    def _build_rtsp_pipeline(self, params: Dict[str, Any], sink: str, processing: str) -> str:
        """Build pipeline string for RTSP source"""
        url = params.get("url", "")
        latency = params.get("latency", 0)
        protocols = params.get("protocols", "tcp")
        
        if not url:
            raise ValueError("RTSP URL is required")
        
        pipeline = f"rtspsrc location={url} latency={latency} protocols={protocols} ! "
        pipeline += "rtph264depay ! h264parse ! avdec_h264 ! "
        pipeline += "videoconvert ! "
        
        if processing:
            pipeline += f"{processing} ! "
        
        pipeline += sink
        
        return pipeline
    
    def _build_file_pipeline(self, params: Dict[str, Any], sink: str, processing: str) -> str:
        """Build pipeline string for file source"""
        filepath = params.get("filepath", "")
        
        if not filepath:
            raise ValueError("File path is required")
        
        pipeline = f"filesrc location={filepath} ! "
        pipeline += "decodebin ! videoconvert ! "
        
        if processing:
            pipeline += f"{processing} ! "
        
        pipeline += sink
        
        return pipeline
    
    def _build_test_pipeline(self, params: Dict[str, Any], sink: str, processing: str) -> str:
        """Build pipeline string for test source"""
        pattern = params.get("pattern", 0)
        width = params.get("width", 640)
        height = params.get("height", 480)
        framerate = params.get("framerate", 30)
        
        pipeline = f"videotestsrc pattern={pattern} ! "
        pipeline += f"video/x-raw,width={width},height={height},framerate={framerate}/1 ! "
        
        if processing:
            pipeline += f"{processing} ! "
        
        pipeline += sink
        
        return pipeline
    
    def add_appsink(self, callback: Callable[[Any], None], caps: str = "video/x-raw,format=RGB"):
        """
        Add an appsink to capture frames programmatically.
        
        Args:
            callback: Function to call with each frame
            caps: Caps string for the appsink
        """
        if not self.pipeline:
            raise RuntimeError("Pipeline must be built before adding appsink")
        
        # Create appsink element
        appsink = Gst.ElementFactory.make("appsink", "appsink")
        appsink.set_property("emit-signals", True)
        appsink.set_property("max-buffers", 1)
        appsink.set_property("drop", True)
        appsink.set_property("sync", False)
        
        # Set caps
        caps = Gst.caps_from_string(caps)
        appsink.set_property("caps", caps)
        
        # Connect callback
        appsink.connect("new-sample", self._on_new_sample, callback)
        
        # Add to pipeline
        self.pipeline.add(appsink)
        
        # Link elements
        # This is a simplified version - you might need to adjust based on your pipeline
        last_element = self.pipeline.get_by_name("videoconvert0")
        if last_element:
            last_element.link(appsink)
    
    def _on_new_sample(self, sink, callback):
        """Handle new sample from appsink"""
        sample = sink.emit("pull-sample")
        if sample and callback:
            callback(sample)
        return Gst.FlowReturn.OK
    
    def start(self):
        """Start the pipeline"""
        if not self.pipeline:
            raise RuntimeError("Pipeline not built. Call build_pipeline() first.")
        
        self.logger.info("Starting pipeline")
        
        # Start main loop in separate thread
        self.loop = GLib.MainLoop()
        self.loop_thread = threading.Thread(target=self._run_loop)
        self.loop_thread.daemon = True
        self.loop_thread.start()
        
        # Start playing
        ret = self.pipeline.set_state(Gst.State.PLAYING)
        if ret == Gst.StateChangeReturn.FAILURE:
            self.logger.error("Unable to set pipeline to PLAYING state")
            raise RuntimeError("Failed to start pipeline")
        
        self.is_playing = True
        self.logger.info("Pipeline started successfully")
    
    def stop(self):
        """Stop the pipeline"""
        if self.pipeline and self.is_playing:
            self.logger.info("Stopping pipeline")
            
            # Stop pipeline
            self.pipeline.set_state(Gst.State.NULL)
            self.is_playing = False
            
            # Stop main loop
            if self.loop:
                self.loop.quit()
            
            # Wait for thread to finish
            if self.loop_thread and self.loop_thread.is_alive():
                self.loop_thread.join(timeout=5)
            
            self.logger.info("Pipeline stopped")
    
    def pause(self):
        """Pause the pipeline"""
        if self.pipeline and self.is_playing:
            self.pipeline.set_state(Gst.State.PAUSED)
            self.is_playing = False
            self.logger.info("Pipeline paused")
    
    def resume(self):
        """Resume the pipeline"""
        if self.pipeline and not self.is_playing:
            self.pipeline.set_state(Gst.State.PLAYING)
            self.is_playing = True
            self.logger.info("Pipeline resumed")
    
    def _run_loop(self):
        """Run the GLib main loop"""
        try:
            self.loop.run()
        except Exception as e:
            self.logger.error(f"Error in main loop: {str(e)}")
    
    def _on_message(self, bus, message):
        """Handle bus messages"""
        msg_type = message.type
        
        if msg_type == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            self.logger.error(f"Error: {err}, Debug: {debug}")
            if self.on_error_callback:
                self.on_error_callback(err, debug)
        
        elif msg_type == Gst.MessageType.EOS:
            self.logger.info("End of stream")
            if self.on_eos_callback:
                self.on_eos_callback()
        
        elif msg_type == Gst.MessageType.WARNING:
            warn, debug = message.parse_warning()
            self.logger.warning(f"Warning: {warn}, Debug: {debug}")
        
        elif msg_type == Gst.MessageType.STATE_CHANGED:
            if message.src == self.pipeline:
                old_state, new_state, pending = message.parse_state_changed()
                self.logger.debug(f"State changed from {old_state.value_nick} to {new_state.value_nick}")
    
    def set_callbacks(self, on_frame=None, on_error=None, on_eos=None):
        """
        Set callback functions for various events.
        
        Args:
            on_frame: Callback for new frames (if using appsink)
            on_error: Callback for errors
            on_eos: Callback for end of stream
        """
        self.on_frame_callback = on_frame
        self.on_error_callback = on_error
        self.on_eos_callback = on_eos
    
    def get_pipeline_graph(self, filename: str = "pipeline"):
        """
        Generate a graph of the pipeline for debugging.
        
        Args:
            filename: Base filename for the graph (without extension)
        """
        if self.pipeline:
            Gst.debug_bin_to_dot_file(
                self.pipeline,
                Gst.DebugGraphDetails.ALL,
                filename
            )
            self.logger.info(f"Pipeline graph saved. Run: dot -Tpng {filename}.dot > {filename}.png")
    
    def __del__(self):
        """Cleanup when object is destroyed"""
        self.stop()


