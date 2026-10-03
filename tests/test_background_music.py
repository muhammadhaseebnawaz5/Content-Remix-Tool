import shutil
import subprocess
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.audio.music_library import MusicLibrary, scan_music_folder
from src.ffmpeg.command_builder import CommandBuilder
from src.ffmpeg.probe import Probe
from src.processing import batch_processor as batch_processor_module
from src.processing.batch_processor import BatchProcessor


def _media_info(duration=10.0, has_audio=True):
    return SimpleNamespace(
        duration=duration,
        video_streams=[SimpleNamespace(width=1920, height=1080)],
        audio_streams=[SimpleNamespace()] if has_audio else [],
    )


def _build_command(music_config, media_info=None, effects=None):
    config = {
        "audio": {"background_music": music_config},
        "effects": effects or {},
        "export": {"encoder": "libx264", "resolution": "original"},
    }
    return CommandBuilder().build(
        "input.mp4",
        "output.mp4",
        config,
        media_info=media_info or _media_info(),
        gpu_encoders=[],
    )


def test_music_disabled_leaves_existing_audio_path_unchanged(tmp_path: Path):
    music_path = tmp_path / "track.mp3"
    music_path.touch()

    command = _build_command(
        {"enabled": False, "file": str(music_path)}
    )

    assert command.count("-i") == 1
    assert "-filter_complex" not in command
    assert "-map" not in command
    assert command[command.index("-c:a") + 1] == "copy"


def test_enabled_music_is_mapped_and_trimmed_to_video(tmp_path: Path):
    music_path = tmp_path / "track.mp3"
    music_path.touch()

    command = _build_command(
        {
            "enabled": True,
            "file": str(music_path),
            "music_duration": 30.0,
            "volume": 0.6,
            "mode": "replace",
        },
        media_info=_media_info(has_audio=False),
    )

    assert command.count("-i") == 2
    assert command[command.index("-filter_complex") + 1].startswith("[1:a]")
    assert command[command.index("-map") + 1] == "0:v:0"
    assert command[command.index("-map") + 3] == "[m]"
    assert command[command.index("-t") + 1] == "10.000"
    assert command[command.index("-c:a") + 1] == "aac"


def test_music_mix_preserves_audio_effects_and_respects_speed(tmp_path: Path):
    music_path = tmp_path / "track.mp3"
    music_path.touch()

    command = _build_command(
        {
            "enabled": True,
            "file": str(music_path),
            "music_duration": 30.0,
            "mode": "mix",
        },
        effects={"speed": {"enabled": True, "speed": 2.0}},
    )

    filter_complex = command[command.index("-filter_complex") + 1]
    assert "[0:a]volume=0.500,atempo=2.0000,aresample=44100" in filter_complex
    assert "[1:a]aresample=44100,aformat=channel_layouts=stereo,volume=0.500" in filter_complex
    assert "amix=inputs=2:duration=first:dropout_transition=0:normalize=0" in filter_complex
    assert command[command.index("-map") + 3] == "[aout]"
    assert command[command.index("-t") + 1] == "5.000"


def test_short_music_track_loops_until_video_ends(tmp_path: Path):
    music_path = tmp_path / "short.mp3"
    music_path.touch()

    command = _build_command(
        {
            "enabled": True,
            "file": str(music_path),
            "music_duration": 3.0,
            "mode": "replace",
        },
    )

    assert command[command.index("-stream_loop") + 1] == "-1"
    assert command[command.index("-t") + 1] == "10.000"


def test_music_library_scans_supported_files_and_sequences_them(tmp_path: Path):
    first = tmp_path / "a.mp3"
    nested = tmp_path / "nested" / "b.wav"
    unsupported = tmp_path / "notes.txt"
    nested.parent.mkdir()
    first.touch()
    nested.touch()
    unsupported.touch()

    tracks = scan_music_folder(str(tmp_path))
    library = MusicLibrary(tracks, mode="sequential")

    assert tracks == sorted([str(first), str(nested)])
    assert len(library) == 2
    assert [library.next_track(), library.next_track(), library.next_track()] == [
        tracks[0],
        tracks[1],
        tracks[0],
    ]


def test_batch_assigns_a_music_track_to_each_enabled_video(tmp_path: Path, monkeypatch):
    tracks = [tmp_path / "first.mp3", tmp_path / "second.mp3"]
    for track in tracks:
        track.touch()

    monkeypatch.setattr(
        batch_processor_module.MusicLibrary,
        "duration_of",
        lambda _library, _path: 12.5,
    )

    processor = BatchProcessor(max_workers=1)
    processed_configs = []
    complete = threading.Event()

    def capture_config(_input_path, _output_path, config, _index):
        processed_configs.append(config["audio"]["background_music"])
        if len(processed_configs) == 2:
            complete.set()
        return {"success": True}

    processor._process_single = capture_config
    processor.start(
        ["one.mp4", "two.mp4"],
        str(tmp_path / "output"),
        {
            "audio": {
                "background_music": {
                    "enabled": True,
                    "files": [str(track) for track in tracks],
                    "selection": "sequential",
                }
            }
        },
    )

    assert complete.wait(5)
    deadline = time.time() + 5
    while processor.state == BatchProcessor.STATE_RUNNING and time.time() < deadline:
        time.sleep(0.01)

    assert [item["file"] for item in processed_configs] == [str(track) for track in tracks]
    assert [item["music_duration"] for item in processed_configs] == [12.5, 12.5]


@pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
    reason="FFmpeg and ffprobe are required for the encoding smoke test",
)
def test_ffmpeg_encodes_output_with_background_music(tmp_path: Path):
    ffmpeg_path = shutil.which("ffmpeg")
    assert ffmpeg_path is not None
    source_path = tmp_path / "source.mp4"
    music_path = tmp_path / "music.wav"
    output_path = tmp_path / "remixed.mp4"

    subprocess.run(
        [
            ffmpeg_path,
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=160x90:d=1.2:r=15",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1.2",
            "-shortest",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(source_path),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    subprocess.run(
        [
            ffmpeg_path,
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=880:duration=0.4",
            "-c:a",
            "pcm_s16le",
            str(music_path),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )

    probe = Probe()
    music_duration = probe.analyze(str(music_path)).duration
    command = CommandBuilder(ffmpeg_path).build(
        str(source_path),
        str(output_path),
        {
            "audio": {
                "background_music": {
                    "enabled": True,
                    "file": str(music_path),
                    "music_duration": music_duration,
                    "volume": 0.6,
                    "fade_in": 0.1,
                    "fade_out": 0.1,
                    "mode": "replace",
                }
            },
            "effects": {},
            "export": {
                "encoder": "libx264",
                "resolution": "original",
                "bitrate": "500k",
                "fps": 15,
            },
        },
        media_info=probe.analyze(str(source_path)),
        gpu_encoders=[],
    )
    subprocess.run(command, check=True, capture_output=True, timeout=30)

    output_info = probe.analyze(str(output_path))
    assert output_info.video_streams
    assert output_info.audio_streams
    assert output_info.duration == pytest.approx(1.2, abs=0.15)
