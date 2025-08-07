# WebRTC Webcam Streaming Setup

## Overview
The WebRTC streamer has been modified to use your webcam instead of a preselected video file.

## Configuration

### Using Webcam (Default)
By default, the streamer will now use your webcam. The following environment variables control the behavior:

- `USE_WEBCAM=true` - Enable webcam mode (default: true)
- `WEBCAM_INDEX=0` - Webcam device index (default: 0 for primary camera)
- `VIDEO_FILE=path/to/video.mp4` - Fallback video file if webcam mode is disabled

### macOS Camera Permissions
On macOS, you need to grant camera permissions to your terminal application:

1. Go to **System Settings** → **Privacy & Security** → **Camera**
2. Enable camera access for your terminal application (Terminal, iTerm2, etc.)
3. You may need to restart your terminal after granting permission

### Testing Webcam Access
Run the test script to verify webcam access:
```bash
python3 test_webcam.py
```

To test a different camera index:
```bash
python3 test_webcam.py 1  # Test second camera
```

## Running the Streamer

### Start the Signaling Server
```bash
cd signaling
npm install  # If not already done
node server.js
```

### Start the Webcam Streamer
```bash
# Using default webcam
python3 src/webrtc_streamer.py

# Using specific webcam index
WEBCAM_INDEX=1 python3 src/webrtc_streamer.py

# Fallback to video file mode
USE_WEBCAM=false python3 src/webrtc_streamer.py
```

### Open the Viewer
Open `viewer.html` in a web browser and click "Connect" to start viewing the webcam stream.

## Troubleshooting

### Camera Not Found
- Check camera permissions in System Settings
- Try different camera indices (0, 1, 2, etc.)
- Ensure no other application is using the camera
- On macOS, restart your terminal after granting permissions

### Performance Issues
The webcam is configured to use:
- Resolution: 640x480 (can be adjusted in the code)
- FPS: 30 (can be adjusted based on your camera capabilities)

To modify these settings, edit the `_initialize_capture` method in `src/webrtc_streamer.py`:
```python
self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)  # Change width
self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)  # Change height
self.cap.set(cv2.CAP_PROP_FPS, 60)  # Change FPS
```

## Changes Made

The following modifications were made to enable webcam streaming:

1. **Config Class**: Added `USE_WEBCAM` and `WEBCAM_INDEX` configuration options
2. **OptimizedVideoTrack Class**: Modified to accept either webcam index or video file path
3. **Frame Capture Logic**: Adjusted to handle live webcam feed without looping
4. **Initialization**: Added webcam-specific initialization with resolution and FPS settings

The system automatically falls back to video file mode if webcam access fails or if `USE_WEBCAM=false` is set.