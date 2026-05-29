# VSL Hook Merger — Product Overview

## Purpose

Batch-merge B-roll "hook" videos with a long-form VSL (Video Sales Letter) for Facebook Reels / TikTok. Produces output files ready for upload without manual FFmpeg command-line work.

## Workflows

### Overlay (original)
B-roll overlays the start of the VSL. VSL audio plays continuously from t=0; B-roll audio is muted. Total output duration = VSL duration. Ideal for short teaser hooks (≤6 s) where the VSL brand/audio should not be interrupted.

### Sequential
Hook plays first (full video + own audio), then cross-fades into the VSL. Loudnorm optionally matches hook audio level to VSL so the transition is seamless. Total output ≈ hook\_dur + VSL\_dur − 0.3 s. Ideal for full-reveal hooks (4–10 s) where you want the hook to breathe before the VSL starts.

## Users

Single operator (content creator) running the tool on a Windows desktop machine. All settings persisted between sessions.

## Inputs

| Input | Description |
|---|---|
| FFmpeg binary | `ffmpeg.exe` + `ffprobe.exe` from PATH or manual Browse |
| VSL main file | Long-form 9:16 vertical video (e.g. 22–23 min) |
| B-roll hook files | One or more short 9:16 or non-9:16 clips |
| Output directory | Folder to write merged outputs |

## Outputs

| File pattern | Workflow | Duration |
|---|---|---|
| `{hook_stem}_hook_VSL.mp4` | Overlay | = VSL duration |
| `{hook_stem}_seq_VSL.mp4` | Sequential | ≈ hook + VSL − fade |P

Encoding: 1080×1920, H.264 high@4.1, CRF 23, AAC 128 k, 30 fps, yuv420p, +faststart.

## Constraints

- No external Python packages (stdlib only).
- Python ≥ 3.10 required (uses `X | Y` union types).
- FFmpeg ≥ 4.0 required (loudnorm JSON output exists since 3.4).
- Windows primary target; macOS/Linux work with minor PATH differences.
- No preview / trim / multi-hook stacking in scope.
