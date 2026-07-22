#!/bin/bash
# AI Bulk Remix Studio Launcher (Linux/macOS)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is not installed. Please install Python 3.9 or later."
    exit 1
fi

# Check FFmpeg
if ! command -v ffmpeg &> /dev/null; then
    echo "⚠️  FFmpeg not found in PATH. Video processing will not work."
    echo "   Install: sudo apt install ffmpeg  (Ubuntu/Debian)"
    echo "            brew install ffmpeg      (macOS)"
fi

# Create venv if not exists
if [ ! -d ".venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv .venv
fi

# Activate venv
source .venv/bin/activate

# Install/update dependencies
if [ ! -f ".venv/installed" ] || [ "requirements.txt" -nt ".venv/installed" ]; then
    echo "📦 Installing dependencies..."
    pip install -r requirements.txt -q
    touch .venv/installed
fi

# Launch app
echo "🚀 Starting AI Bulk Remix Studio..."
python3 main.py "$@"
