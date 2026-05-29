# Codebase Summary

## Project

`vsl-hook-merger` — Python tkinter GUI tool that batch-merges B-roll hook videos with a long-form VSL using FFmpeg. Two workflows: Overlay and Sequential.

## Directory Layout

```
vsl-hook-merger/
├── vsl_hook_merger.py        # GUI entry point (tkinter App class)
├── worker.py                 # BatchWorker thread + JobConfig dataclass
├── ffmpeg_runner.py          # ffmpeg/ffprobe subprocess wrappers
├── filter_graph_builder.py   # Pure filter_complex string builders
├── settings.py               # JSON settings persist/load
├── setup.bat                 # First-run installer (winget Python+FFmpeg)
├── run.bat                   # Windows launcher
├── requirements.txt          # Empty — stdlib only
├── docs/                     # Project documentation
└── tests/
    ├── test_filter_graph_builder.py   # 20 filter string tests (no ffmpeg needed)
    ├── test_audio_probing.py          # 7 integration tests (ffmpeg fixtures)
    └── test_worker_config.py          # 9 unit tests (JobConfig + settings)
```

## Module Summaries

### `vsl_hook_merger.py` (~295 lines)
tkinter `App` class. Builds GUI with pack layout. Key vars: `var_workflow` (overlay/sequential), `var_normalize` (bool), `var_fade`, `var_crf`, `var_mode`, `var_skip`. Polls a `Queue` every 100 ms via `root.after` to receive worker events without blocking the UI. Settings loaded from / saved to `settings.py` on start and on `_on_workflow_change`.

### `worker.py` (~145 lines)
`JobConfig` dataclass — snapshot of UI state at run time:
- `ffmpeg`, `ffprobe` paths
- `vsl`, `output_dir`, `brolls` paths
- `crf`, `non_916_mode`, `skip_existing`, `fade_duration`
- `workflow: str = "overlay"` | `"sequential"`
- `normalize_audio: bool = True`

`BatchWorker(threading.Thread)` — runs the batch. For sequential: probes VSL LUFS once before the loop (graceful fail → `vsl_lufs=None`). Per broll: probes `has_hook_audio`, dispatches to `build_filter()`, calls `encode_with_progress()`, emits Queue events.

### `ffmpeg_runner.py` (~180 lines)
- `find_ffmpeg(custom_path)` / `find_ffprobe(ffmpeg_path)` — locate binaries
- `probe_duration(ffprobe, path) → float` — ffprobe duration
- `probe_has_audio(ffprobe, path) → bool` — ffprobe audio stream check
- `probe_lufs(ffmpeg, path) → float` — EBU R128 integrated LUFS via loudnorm measure pass; `-vn` skips video decode; parses `input_i` from JSON in stderr; clamps to `[-70.0, -5.0]`
- `encode_with_progress(ffmpeg, broll, vsl, output, ..., audio_map="1:a") → int` — Popen with `-progress pipe:1`, streams `out_time_us=` lines, calls `on_progress(0..1)`, respects `is_cancelled()`

### `filter_graph_builder.py` (~175 lines)
Pure functions; no imports beyond `typing`.

- `_build_hook_video_chain(mode, hook_tail_fmt, out_label)` — private helper for 3 non-9:16 modes (blur/crop/pad), shared by both workflows
- `build_overlay_filter(broll_duration, mode, fade_duration)` — alpha overlay with optional `yuva420p` fade
- `build_sequential_filter(hook_duration, mode, fade_duration, has_hook_audio, vsl_lufs)` — xfade + acrossfade; aevalsrc silence for no-audio hooks; loudnorm on hook when `vsl_lufs` given; **`format=yuv420p` forced after xfade**
- `build_filter(workflow, **kwargs)` — dispatcher

### `settings.py` (~42 lines)
`DEFAULT` dict + `load()` / `save()`. Settings file: `~/.vsl-hook-merger.json`. Old JSON missing new keys silently gets defaults via `{**DEFAULT, **saved}`.

## Public API Surface

```python
# filter_graph_builder
build_overlay_filter(broll_duration, mode="blur", fade_duration=0.0) -> str
build_sequential_filter(hook_duration, mode="blur", fade_duration=0.3,
                        has_hook_audio=True, vsl_lufs=None) -> str
build_filter(workflow, **kwargs) -> str

# ffmpeg_runner
find_ffmpeg(custom_path="") -> str | None
find_ffprobe(ffmpeg_path="") -> str | None
probe_duration(ffprobe, path) -> float
probe_has_audio(ffprobe, path) -> bool
probe_lufs(ffmpeg, path) -> float        # raises RuntimeError if no audio stream
encode_with_progress(ffmpeg, broll, vsl, output, filter_complex, crf,
                     total_duration, on_progress, on_log,
                     is_cancelled, audio_map="1:a") -> int

# worker
@dataclass JobConfig(...)
class BatchWorker(threading.Thread): cancel(), is_cancelled(), run()

# settings
DEFAULT: dict
load() -> dict
save(data: dict) -> None
```

## Test Coverage

| Test file | Tests | Requires ffmpeg |
|---|---|---|
| `test_filter_graph_builder.py` | 20 | No |
| `test_audio_probing.py` | 7 | Yes (auto-skip if absent) |
| `test_worker_config.py` | 9 | No |
| **Total** | **36** | — |

Run: `python -m pytest tests/ -v -p no:asyncio`

## Known Quirks

- `pytest-asyncio` version mismatch on this machine → always pass `-p no:asyncio`
- `aevalsrc` channel layout uses `c=stereo` (not `cl=stereo`) on ffmpeg ≥ 5.x
- `xfade` filter outputs `yuv444p` internally → `format=yuv420p` must follow it
- `probe_lufs` runtime on 23-min VSL: 10–30 s (runs in worker thread, not GUI thread)
