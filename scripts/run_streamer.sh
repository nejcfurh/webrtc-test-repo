#!/bin/bash

# WebRTC Streamer Launch Script
# This script handles environment setup and launches the improved streamer

set -e  # Exit on any error

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_PATH="$PROJECT_ROOT/venv"
STREAMER_PATH="$PROJECT_ROOT/src/webrtc_streamer.py"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}🚀 Starting WebRTC Streamer...${NC}"

# Check if virtual environment exists
if [ ! -d "$VENV_PATH" ]; then
    echo -e "${YELLOW}⚠️  Virtual environment not found at $VENV_PATH${NC}"
    echo -e "${YELLOW}Creating virtual environment...${NC}"
    python3 -m venv "$VENV_PATH"
fi

# Activate virtual environment
echo -e "${GREEN}📦 Activating virtual environment...${NC}"
source "$VENV_PATH/bin/activate"

# Check if requirements are installed
echo -e "${GREEN}🔍 Checking Python dependencies...${NC}"
if ! pip show aiortc >/dev/null 2>&1; then
    echo -e "${YELLOW}📦 Installing Python dependencies...${NC}"
    pip install -r "$PROJECT_ROOT/requirements.txt"
fi

# Check if video file exists
VIDEO_FILE="${VIDEO_FILE:-$PROJECT_ROOT/media/test-video.mp4}"
if [ ! -f "$VIDEO_FILE" ]; then
    echo -e "${RED}❌ Video file not found: $VIDEO_FILE${NC}"
    echo -e "${YELLOW}💡 Please ensure you have a video file at: $VIDEO_FILE${NC}"
    exit 1
fi

# Environment variables with defaults
export SIGNALING_URL="${SIGNALING_URL:-ws://localhost:8080}"
export VIDEO_FILE="$VIDEO_FILE"
export ROOM_ID="${ROOM_ID:-default}"
export MAX_RETRIES="${MAX_RETRIES:-3}"
export RETRY_DELAY="${RETRY_DELAY:-5}"
export CONNECTION_TIMEOUT="${CONNECTION_TIMEOUT:-30}"

echo -e "${GREEN}⚙️  Configuration:${NC}"
echo -e "  Signaling Server: $SIGNALING_URL"
echo -e "  Video File: $VIDEO_FILE"
echo -e "  Room ID: $ROOM_ID"
echo -e "  Max Retries: $MAX_RETRIES"
echo -e "  Connection Timeout: ${CONNECTION_TIMEOUT}s"
echo ""

# Launch the streamer
echo -e "${GREEN}🎬 Launching WebRTC streamer...${NC}"
python3 "$STREAMER_PATH"

echo -e "${GREEN}✅ WebRTC streamer finished.${NC}"