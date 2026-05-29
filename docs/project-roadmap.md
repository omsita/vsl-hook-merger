# Project Roadmap

## Current State (v2.0 — Sequential Workflow)

| Feature | Status |
|---|---|
| Overlay workflow (B-roll + VSL overlay) | ✅ Complete |
| Batch processing with progress bars | ✅ Complete |
| Non-9:16 hook: blur / crop / pad | ✅ Complete |
| Alpha fade transition (overlay → VSL) | ✅ Complete |
| setup.bat first-run installer | ✅ Complete |
| Sequential workflow (hook → xfade → VSL) | ✅ Complete |
| `probe_has_audio` / `probe_lufs` utilities | ✅ Complete |
| Loudnorm match-to-VSL (EBU R128) | ✅ Complete |
| Workflow radio buttons + normalize checkbox in GUI | ✅ Complete |
| Settings persist workflow + normalize_audio | ✅ Complete |
| 36-test suite (filter, audio probe, worker config) | ✅ Complete |

## Known Limitations

| Issue | Severity | Notes |
|---|---|---|
| Only 1 B-roll per output (no stacking) | Low | By design — each hook gets its own output |
| No delay on hook appearance (always t=0) | Low | Not requested |
| No preview frame before encode | Low | Would require separate ffmpeg thumbnail call |
| FB Reels 90s cap on some accounts | Informational | Sequential mode adds 4–10 s on top of VSL |
| No trim / cut tool for B-rolls | Low | User trims externally before adding |

## Potential Future Work

| Feature | Effort | Priority |
|---|---|---|
| Preview thumbnail (first frame of output) | S | Medium |
| Drag-and-drop B-roll list reorder | S | Low |
| Custom output filename template | S | Low |
| macOS / Linux `setup.sh` counterpart | M | Low |
| Configurable xfade transition type (dissolve, wipeleft, …) | S | Low |
| Multi-VSL support (different VSL per hook) | M | Low |
| Integration test: real encode with short synthetic clips | M | Medium |

## Version History

### v2.0 — Sequential Workflow
- Added `build_sequential_filter()` with xfade + acrossfade
- Added `probe_has_audio()` and `probe_lufs()` in `ffmpeg_runner.py`
- `JobConfig` gains `workflow` + `normalize_audio` fields
- Worker probes VSL LUFS once per batch (graceful degradation on failure)
- GUI: Workflow radio buttons + conditional normalize checkbox
- Bug fix: `format=yuv420p` after xfade to prevent libx264 4:4:4 rejection
- Bug fix: `aevalsrc` uses `c=stereo` not `cl=stereo`
- Test count: 36 (up from 10)

### v1.1 — Fade Transition
- Added `fade_duration` spinbox (0.0–1.0 s, default 0.3)
- `build_overlay_filter` supports alpha fade via `yuva420p` + `fade=out:alpha=1`
- 10 filter tests

### v1.0 — Initial Release
- Overlay workflow batch tool
- GUI: FFmpeg/VSL/B-roll/Output pickers, CRF, Non-9:16 mode, Skip existing
- `setup.bat` first-run installer
