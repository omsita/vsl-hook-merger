"""Persist user settings to a JSON file in the user's home directory.

Stores last-used paths and options so the GUI can restore state on launch.
"""
import json
from pathlib import Path

SETTINGS_PATH = Path.home() / ".vsl-hook-merger.json"

DEFAULT = {
    "ffmpeg_path": "",
    "vsl_path": "",
    "output_dir": "",
    "crf": 23,
    "non_916_mode": "blur",
    "skip_existing": True,
    "fade_duration": 0.3,   # seconds; 0 = hard cut
    "last_broll_dir": "",
    "workflow": "overlay",  # "overlay" | "sequential"
    "normalize_audio": True,  # only used when workflow == "sequential"
    "use_nvenc": False,  # h264_nvenc GPU encoder (auto-detected)
    "render_mode": "local",  # "local" | "cloud"
    "runpod_api_key": "",
    "runpod_endpoint_id": "",
    "cloud_max_workers": 5,
    "dropbox_token": "",
    "dropbox_path": "/VSL_Output",
}


def load() -> dict:
    """Return merged defaults + saved settings. Never raises."""
    if SETTINGS_PATH.exists():
        try:
            data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            return {**DEFAULT, **data}
        except Exception:
            pass
    return DEFAULT.copy()


def save(data: dict) -> None:
    """Best-effort persist. Silently swallows IO errors."""
    try:
        SETTINGS_PATH.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        pass
