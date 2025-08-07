import asyncio
import json
import logging
import os
import time
from typing import Optional
import cv2
import websockets
from aiortc import (
    RTCPeerConnection, 
    RTCSessionDescription, 
    VideoStreamTrack, 
    RTCConfiguration, 
    RTCIceServer
)
from av import VideoFrame
import signal
import sys

# Configure logging
logging.basicConfig(
    level=logging.INFO,  # Back to normal logging
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class Config:
    """Configuration management"""
    def __init__(self):
        self.SIGNALING_URL = os.getenv('SIGNALING_URL', 'ws://localhost:8080')
        self.USE_WEBCAM = os.getenv('USE_WEBCAM', 'true').lower() == 'true'
        self.WEBCAM_INDEX = int(os.getenv('WEBCAM_INDEX', '0'))  # Default to first webcam
        self.VIDEO_FILE = os.getenv('VIDEO_FILE', 'media/test-video.mp4')  # Fallback for file mode
        self.STUN_SERVERS = [
            'stun:stun.l.google.com:19302',
            'stun:stun1.l.google.com:19302',
            'stun:stun2.l.google.com:19302',
        ]
        self.MAX_RETRIES = int(os.getenv('MAX_RETRIES', '3'))
        self.RETRY_DELAY = int(os.getenv('RETRY_DELAY', '5'))
        self.CONNECTION_TIMEOUT = int(os.getenv('CONNECTION_TIMEOUT', '30'))

class OptimizedVideoTrack(VideoStreamTrack):
    """Enhanced video track with better performance and error handling"""
    
    def __init__(self, source, is_webcam=False):
        super().__init__()
        self.source = source  # Can be file path or webcam index
        self.is_webcam = is_webcam
        self.cap = None
        self.frame_rate = 30
        self.frame_time = 1.0 / self.frame_rate
        self.last_frame_time = 0
        self.frame_count = 0
        self.total_frames = 0
        self._initialize_capture()

    def _initialize_capture(self):
        """Initialize video capture with error handling"""
        try:
            if self.is_webcam:
                # Initialize webcam
                self.cap = cv2.VideoCapture(self.source)
                if not self.cap.isOpened():
                    raise IOError(f"Cannot open webcam at index: {self.source}")
                
                # Set webcam properties for better performance
                self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                self.cap.set(cv2.CAP_PROP_FPS, 30)
                
                # Get actual properties after setting
                self.frame_rate = self.cap.get(cv2.CAP_PROP_FPS) or 30
                self.total_frames = 0  # Webcam has no total frames
                
                logger.info(f"Webcam initialized: index {self.source} ({self.frame_rate} fps)")
            else:
                # Initialize video file
                self.cap = cv2.VideoCapture(self.source)
                if not self.cap.isOpened():
                    raise IOError(f"Cannot open video file: {self.source}")
                
                # Get video properties
                self.frame_rate = self.cap.get(cv2.CAP_PROP_FPS) or 30
                self.total_frames = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
                
                logger.info(f"Video file initialized: {self.source} ({self.frame_rate} fps, {self.total_frames} frames)")
            
            self.frame_time = 1.0 / self.frame_rate
            
            # Set buffer size to reduce latency
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            
        except Exception as e:
            logger.error(f"Failed to initialize video capture: {e}")
            raise

    async def recv(self):
        """Receive next video frame with timing control"""
        try:
            current_time = time.time()
            
            # Control frame rate
            if current_time - self.last_frame_time < self.frame_time:
                await asyncio.sleep(self.frame_time - (current_time - self.last_frame_time))
            
            pts, time_base = await self.next_timestamp()
            
            ret, frame = self.cap.read()
            if not ret:
                if self.is_webcam:
                    # For webcam, try to reinitialize if frame read fails
                    logger.warning("Failed to read webcam frame, reinitializing...")
                    self._initialize_capture()
                    ret, frame = self.cap.read()
                    
                    if not ret:
                        raise RuntimeError("Failed to read webcam frame after reinitialization")
                else:
                    # Loop video file
                    logger.info("Video ended, restarting...")
                    self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    self.frame_count = 0
                    ret, frame = self.cap.read()
                    
                    if not ret:
                        # Reinitialize if still failing
                        logger.warning("Reinitializing video capture...")
                        self._initialize_capture()
                        ret, frame = self.cap.read()
                        
                        if not ret:
                            raise RuntimeError("Failed to read video frame after reinitialization")
            
            # Convert color space
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            
            # Create video frame
            vf = VideoFrame.from_ndarray(frame, format="rgb24")
            vf.pts = pts
            vf.time_base = time_base
            
            self.last_frame_time = current_time
            self.frame_count += 1
            
            return vf
            
        except Exception as e:
            logger.error(f"Error in video frame processing: {e}")
            raise

    def cleanup(self):
        """Clean up video capture resources"""
        if self.cap:
            self.cap.release()
            self.cap = None
            if self.is_webcam:
                logger.info("🔴 Webcam released and turned off")
            else:
                logger.info("Video capture released")

class WebRTCStreamer:
    """Simple WebRTC streamer - no rooms, just connects and streams"""
    
    def __init__(self, config: Config):
        self.config = config
        self.pc: Optional[RTCPeerConnection] = None
        self.ws: Optional[websockets.WebSocketServerProtocol] = None
        self.video_track: Optional[OptimizedVideoTrack] = None
        self.connected = False
        self.running = False
        self.retry_count = 0
        
        # Setup signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        logger.info(f"Received signal {signum}, shutting down...")
        self.running = False
        # Immediate cleanup of video track to turn off camera
        if self.video_track:
            self.video_track.cleanup()

    async def start(self):
        """Start the WebRTC streamer with retry logic"""
        self.running = True
        
        while self.running and self.retry_count < self.config.MAX_RETRIES:
            try:
                await self._connect_and_stream()
                # If we get here, connection was successful
                self.retry_count = 0
                
            except KeyboardInterrupt:
                logger.info("Keyboard interrupt received")
                self.running = False
                break
                
            except Exception as e:
                logger.error(f"Streaming failed: {e}")
                self.retry_count += 1
                
                if self.retry_count < self.config.MAX_RETRIES and self.running:
                    logger.info(f"Retrying in {self.config.RETRY_DELAY} seconds... (attempt {self.retry_count}/{self.config.MAX_RETRIES})")
                    await asyncio.sleep(self.config.RETRY_DELAY)
                else:
                    logger.error("Maximum retries reached, stopping...")
                    break
                    
            finally:
                # Always cleanup to ensure camera is released
                await self._cleanup()

    async def _connect_and_stream(self):
        """Main connection and streaming logic"""
        logger.info("Starting WebRTC streamer...")
        
        # Initialize video track
        if self.config.USE_WEBCAM:
            logger.info(f"Using webcam at index {self.config.WEBCAM_INDEX}")
            self.video_track = OptimizedVideoTrack(self.config.WEBCAM_INDEX, is_webcam=True)
        else:
            logger.info(f"Using video file: {self.config.VIDEO_FILE}")
            self.video_track = OptimizedVideoTrack(self.config.VIDEO_FILE, is_webcam=False)
        
        # Create peer connection
        self._create_peer_connection()
        
        # Connect to signaling server
        await self._connect_signaling()
        
        # Handle signaling messages
        await self._handle_signaling_messages()

    def _create_peer_connection(self):
        """Create and configure RTCPeerConnection"""
        config = RTCConfiguration(
            iceServers=[RTCIceServer(urls=url) for url in self.config.STUN_SERVERS]
        )
        
        self.pc = RTCPeerConnection(configuration=config)
        self.pc.addTrack(self.video_track)
        
        # Set up event handlers
        self.pc.on("connectionstatechange", self._on_connection_state_change)
        self.pc.on("icecandidate", self._on_ice_candidate)
        self.pc.on("icegatheringstatechange", self._on_ice_gathering_state_change)
        self.pc.on("iceconnectionstatechange", self._on_ice_connection_state_change)
        
        logger.info(f"Peer connection created with video track: {self.video_track}")
        logger.info(f"Video track kind: {self.video_track.kind}")
        
    async def _on_ice_connection_state_change(self):
        """Handle ICE connection state changes"""
        state = self.pc.iceConnectionState
        logger.info(f"🧊 ICE connection state: {state}")
        
        if state == "connected":
            logger.info("✅ ICE connection established - P2P connection active")
        elif state == "failed":
            logger.error("❌ ICE connection failed - may need TURN server")
            # Clean up on ICE failure
            if self.video_track:
                self.video_track.cleanup()
        elif state == "disconnected" or state == "closed":
            logger.warning(f"⚠️ ICE connection {state}")
            # Clean up on disconnect
            if self.video_track:
                self.video_track.cleanup()
        elif state == "checking":
            logger.info("🔍 ICE checking candidates...")
        elif state == "completed":
            logger.info("🎯 ICE connection completed")

    async def _connect_signaling(self):
        """Connect to signaling server"""
        logger.info(f"Connecting to signaling server: {self.config.SIGNALING_URL}")
        
        try:
            self.ws = await asyncio.wait_for(
                websockets.connect(self.config.SIGNALING_URL),
                timeout=10
            )
            logger.info("Connected to signaling server")
            
            # Send role identification
            await self.ws.send(json.dumps({"type": "role", "role": "sender"}))
            logger.info("📡 Identified as sender to signaling server")
            
        except asyncio.TimeoutError:
            raise ConnectionError("Timeout connecting to signaling server")
        except Exception as e:
            raise ConnectionError(f"Failed to connect to signaling server: {e}")

    async def _handle_signaling_messages(self):
        """Handle incoming signaling messages"""
        try:
            async for message in self.ws:
                data = json.loads(message)
                message_type = data.get("type")
                
                logger.info(f"Received message: {message_type}")
                
                if message_type == "sender-connected":
                    logger.info("Sender status broadcast to viewers")
                    
                elif message_type == "sender-disconnected":
                    logger.warning("Received sender disconnected (shouldn't happen for sender)")
                    
                elif message_type == "offer":
                    await self._handle_offer(data)
                    
                elif message_type == "ice-candidate":
                    await self._handle_ice_candidate(data)
                    
        except websockets.exceptions.ConnectionClosed:
            logger.warning("WebSocket connection closed")
            await self._cleanup()
            raise ConnectionError("WebSocket connection lost")
        except Exception as e:
            logger.error(f"Error handling signaling messages: {e}")
            await self._cleanup()
            raise

    async def _handle_offer(self, data):
        """Handle incoming offer from viewer"""
        try:
            offer_data = data["offer"]
            logger.info("Processing offer from viewer")
            
            # Set remote description
            offer = RTCSessionDescription(
                sdp=offer_data["sdp"], 
                type=offer_data["type"]
            )
            await self.pc.setRemoteDescription(offer)
            
            # Create and send answer
            answer = await self.pc.createAnswer()
            await self.pc.setLocalDescription(answer)
            
            answer_message = {
                "type": "answer",
                "answer": {
                    "sdp": answer.sdp,
                    "type": answer.type
                }
            }
            
            await self.ws.send(json.dumps(answer_message))
            logger.info("Sent answer to viewer")
            
        except Exception as e:
            logger.error(f"Error handling offer: {e}")
            raise

    def parse_ice_candidate_string(self, candidate_string):
        """Parse ICE candidate string to extract components"""
        try:
            # Example: "candidate:3208550620 1 udp 2113937152 192.168.1.100 58291 typ host generation 0 ufrag 4WUP network-cost 999"
            parts = candidate_string.split()
            if len(parts) < 8:
                raise ValueError("Invalid candidate string format")
            
            foundation = parts[0].split(':')[1]  # Remove "candidate:" prefix
            component = int(parts[1])
            protocol = parts[2].lower()
            priority = int(parts[3])
            ip = parts[4]
            port = int(parts[5])
            # parts[6] is "typ"
            candidate_type = parts[7]
            
            return {
                'foundation': foundation,
                'component': component,
                'protocol': protocol,
                'priority': priority,
                'ip': ip,
                'port': port,
                'type': candidate_type
            }
        except Exception as e:
            logger.error(f"Failed to parse candidate string: {e}")
            return None

    async def _handle_ice_candidate(self, data):
        """Handle incoming ICE candidate"""
        try:
            candidate_data = data.get("candidate", {})
            candidate_string = candidate_data.get("candidate") if isinstance(candidate_data, dict) else None
            
            if candidate_string:
                # Parse the candidate string
                parsed = self.parse_ice_candidate_string(candidate_string)
                if not parsed:
                    logger.error(f"Failed to parse candidate: {candidate_string}")
                    return
                
                # Create RTCIceCandidate object with parsed values
                from aiortc import RTCIceCandidate
                
                ice_candidate = RTCIceCandidate(
                    foundation=parsed['foundation'],
                    component=parsed['component'],
                    protocol=parsed['protocol'],
                    priority=parsed['priority'],
                    ip=parsed['ip'],
                    port=parsed['port'],
                    type=parsed['type']
                )
                
                # Set additional properties
                ice_candidate.sdpMid = candidate_data.get("sdpMid")
                ice_candidate.sdpMLineIndex = candidate_data.get("sdpMLineIndex", 0)
                
                logger.debug(f"Adding ICE candidate: {parsed['ip']}:{parsed['port']} ({parsed['type']})")
                await self.pc.addIceCandidate(ice_candidate)
                logger.debug("✅ ICE candidate added successfully")
                
            elif candidate_data is None or (isinstance(candidate_data, dict) and candidate_data.get("candidate") is None):
                # End of candidates signal
                await self.pc.addIceCandidate(None)
                logger.debug("✅ Added null ICE candidate (gathering complete)")
                
        except Exception as e:
            logger.error(f"❌ Error handling ICE candidate: {e}")
            logger.debug(f"Full data structure: {data}")
            # Continue without failing the connection
            pass

    async def _on_connection_state_change(self):
        """Handle connection state changes"""
        state = self.pc.connectionState
        ice_state = self.pc.iceConnectionState
        logger.info(f"Connection state changed to: {state} (ICE: {ice_state})")
        
        if state == "connected":
            logger.info("🎉 WebRTC connection established! Video should be streaming now.")
        elif state == "failed":
            logger.error("❌ WebRTC connection failed")
            if self.video_track:
                self.video_track.cleanup()
            raise ConnectionError("WebRTC connection failed")
        elif state == "disconnected" or state == "closed":
            logger.warning(f"⚠️ WebRTC connection {state}")
            if self.video_track:
                self.video_track.cleanup()

    async def _on_ice_candidate(self, candidate):
        """Handle local ICE candidates"""
        if candidate and self.ws:
            try:
                candidate_message = {
                    "type": "ice-candidate",
                    "candidate": {
                        "candidate": candidate.candidate,
                        "sdpMid": candidate.sdpMid,
                        "sdpMLineIndex": candidate.sdpMLineIndex
                    }
                }
                
                await self.ws.send(json.dumps(candidate_message))
                logger.debug(f"Sent ICE candidate: {candidate.candidate[:50]}...")
                
            except Exception as e:
                logger.error(f"Error sending ICE candidate: {e}")

    async def _on_ice_gathering_state_change(self):
        """Handle ICE gathering state changes"""
        state = self.pc.iceGatheringState
        logger.info(f"ICE gathering state: {state}")

    async def _cleanup(self):
        """Clean up resources"""
        logger.info("Cleaning up resources...")
        
        # Clean up video track first to release camera
        if self.video_track:
            try:
                self.video_track.cleanup()
            except Exception as e:
                logger.error(f"Error cleaning up video track: {e}")
            finally:
                self.video_track = None
        
        # Close peer connection
        if self.pc:
            try:
                await self.pc.close()
            except Exception as e:
                logger.error(f"Error closing peer connection: {e}")
            finally:
                self.pc = None
        
        # Close websocket
        if self.ws:
            try:
                await self.ws.close()
            except Exception as e:
                logger.error(f"Error closing websocket: {e}")
            finally:
                self.ws = None
        
        self.connected = False
        logger.info("✅ Cleanup completed")

async def main():
    """Main entry point"""
    config = Config()
    streamer = WebRTCStreamer(config)
    
    try:
        await streamer.start()
    except KeyboardInterrupt:
        logger.info("Shutdown requested by user")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        sys.exit(1)
    finally:
        # Final cleanup to ensure camera is off
        await streamer._cleanup()
        logger.info("WebRTC streamer stopped")

if __name__ == "__main__":
    asyncio.run(main())