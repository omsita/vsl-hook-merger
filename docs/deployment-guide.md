# Deployment Guide

## Requirements

| Requirement | Minimum | Notes |
|---|---|---|
| Windows | 10 1809+ | For winget auto-install; tool runs on older Windows manually |
| Python | 3.10 | 3.12 recommended; must include tkinter |
| FFmpeg | 4.0 | Needs `ffmpeg.exe` + `ffprobe.exe` in same folder or PATH |

macOS / Linux: tool runs but `setup.bat` is Windows-only. Install Python + FFmpeg manually, then `python vsl_hook_merger.py`.

---

## First-Time Setup (Windows)

**Double-click `setup.bat`.**

The script checks in order:

1. `python --version` ≥ 3.10 → if missing, runs `winget install Python.Python.3.12`
2. `python -c "import tkinter"` → warns if Microsoft Store Python (often lacks tkinter)
3. `ffmpeg -version` → if missing, runs `winget install Gyan.FFmpeg`
4. `ffprobe -version`
5. Smoke-test: opens a tkinter window briefly

After winget installs Python or FFmpeg, **close and reopen the terminal** so PATH updates take effect, then run `setup.bat` again.

### No winget (Windows < 1809)

Install manually:
- **Python 3.12:** https://www.python.org/downloads/ — tick "Add python.exe to PATH"
- **FFmpeg:** https://www.gyan.dev/ffmpeg/builds/ → `release-full` build → extract → add `bin\` to PATH

---

## Running the Tool

**Double-click `run.bat`** (Windows) or:

```
python vsl_hook_merger.py
```

Settings are auto-saved to `%USERPROFILE%\.vsl-hook-merger.json` on close and on workflow change.

---

## Settings File

Location: `~/.vsl-hook-merger.json`

```json
{
  "ffmpeg_path": "C:\\ffmpeg\\bin\\ffmpeg.EXE",
  "vsl_path": "E:\\Videos\\my_vsl.mp4",
  "output_dir": "E:\\Videos\\output",
  "crf": 23,
  "non_916_mode": "blur",
  "skip_existing": true,
  "fade_duration": 0.3,
  "last_broll_dir": "",
  "workflow": "overlay",
  "normalize_audio": true
}
```

**Backward compatible:** old files missing `workflow` / `normalize_audio` keys load fine — defaults (`"overlay"` / `true`) are merged in automatically.

To reset all settings: delete the file; it is recreated with defaults on next run.

---

## Running Tests

```
python -m pytest tests/ -v -p no:asyncio
```

- `-p no:asyncio` is required — a `pytest-asyncio` version mismatch on the dev machine causes a startup crash otherwise.
- Tests in `test_audio_probing.py` are auto-skipped when ffmpeg is not on PATH.

Expected: **36 passed**.

---

## Encode Output Specs (hardcoded)

| Parameter | Value |
|---|---|
| Resolution | 1080×1920 |
| FPS | 30 |
| Video codec | libx264, profile high, level 4.1, preset medium |
| Pixel format | yuv420p |
| Audio codec | AAC, 128 kbps, 44.1 kHz, stereo |
| Container | MP4 with +faststart |

To change (e.g. preset, bitrate): edit `encode_with_progress()` in `ffmpeg_runner.py`.

---

## Typical Output Size

| VSL length | CRF 23 | CRF 20 |
|---|---|---|
| 22–23 min | ~340 MB | ~600 MB |

Facebook re-encodes on upload — use CRF 23 as default; only go lower (20–21) if source quality is critical.
