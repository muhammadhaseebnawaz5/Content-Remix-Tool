# AI Bulk Remix Studio v1.0.0

A desktop application for content creators to bulk-process videos with automatic randomization — ensuring every output video has a unique fingerprint to avoid duplicate content penalties on YouTube, TikTok, Instagram, etc.

## Features

- **Bulk Processing**: Process hundreds/thousands of videos in parallel
- **AI Remix / Duplicate Prevention**: Automatically randomizes effects per video
- **Rich Effects**: Mirror, zoom, crop, rotation, speed, color grading, noise, motion blur, camera shake, and more
- **GPU Acceleration**: Supports NVIDIA NVENC, Intel QSV, AMD AMF
- **Real-time Monitoring**: Progress tracking, logs, ETA
- **Project Files**: Save/load workflows as `.aibrs` files
- **Plugin System**: Extensible architecture for future effects

## Project Structure

```
ai-bulk-remix-studio/
├── main.py                  # Entry point
├── config/
│   ├── defaults.json        # Default settings
│   └── presets/             # Saved presets
├── src/
│   ├── core/                # EventBus, ProjectManager, ConfigManager, etc.
│   ├── ffmpeg/              # FFmpeg engine (probe, filter graph, command builder)
│   ├── processing/          # Batch & single video processing
│   ├── ui/                  # PySide6 GUI
│   ├── io/                  # File scanning
│   ├── utils/               # System info, randomizer, file utils, logger
│   ├── ai/                  # Reserved for AI models
│   ├── audio/               # Reserved
│   ├── effects/             # Reserved
│   ├── export/              # Reserved
│   └── overlay/             # Reserved
├── plugins/                 # Plugin system
├── assets/                  # Images, icons
├── build/                   # Compiled binaries
└── tests/                   # Unit tests
```

## Requirements

- Python 3.9+
- FFmpeg installed and available in PATH
- (Optional) NVIDIA/Intel/AMD GPU for hardware encoding

## Installation

```bash
pip install -r requirements.txt
```

Make sure `ffmpeg` and `ffprobe` are installed:
```bash
# Ubuntu/Debian
sudo apt install ffmpeg

# macOS
brew install ffmpeg

# Windows
# Download from https://ffmpeg.org/download.html and add to PATH
```

## Usage

```bash
python main.py
```

1. **Sources Tab**: Select input/output directories and scan for videos
2. **Effects Tab**: Choose which effects to apply (randomization enabled by default)
3. **Export Tab**: Set resolution, bitrate, encoder, and naming
4. **Processing Tab**: Adjust workers, detect GPU, and start
5. **Monitor Tab**: Watch real-time progress and logs

## License

MIT License — Use at your own risk. Ensure compliance with platform policies.
