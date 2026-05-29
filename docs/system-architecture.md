# System Architecture

## Module Map

```
vsl_hook_merger.py  ←─ entry point (tkinter GUI, main thread)
        │
        │  JobConfig (dataclass snapshot)
        ▼
    worker.py       ←─ BatchWorker(threading.Thread) + JobConfig
        │  probe_duration()
        │  probe_has_audio()
        │  probe_lufs()
        │  encode_with_progress()
        ▼
 ffmpeg_runner.py   ←─ subprocess wrappers around ffmpeg/ffprobe
        │
        │  filter_complex string
        ▼
filter_graph_builder.py  ←─ pure-function filter string builders

    settings.py     ←─ JSON persist to ~/.vsl-hook-merger.json
```

## Data Flow — Overlay Workflow

```
GUI._start()
  → JobConfig(workflow="overlay", ...)
  → BatchWorker.run()
      ├─ probe_duration(ffprobe, vsl)  → vsl_dur
      └─ for each broll:
           probe_duration(ffprobe, broll) → broll_dur
           build_filter("overlay", broll_duration=broll_dur, ...)
             → filter_complex string
           encode_with_progress(audio_map="1:a")
             → ffmpeg subprocess → {stem}_hook_VSL.mp4
```

## Data Flow — Sequential Workflow

```
GUI._start()
  → JobConfig(workflow="sequential", normalize_audio=True, ...)
  → BatchWorker.run()
      ├─ probe_duration(ffprobe, vsl)     → vsl_dur
      ├─ probe_lufs(ffmpeg, vsl)          → vsl_lufs  (once, pre-loop)
      └─ for each broll:
           probe_duration(ffprobe, broll) → broll_dur
           probe_has_audio(ffprobe, broll) → has_audio
           build_filter("sequential",
             hook_duration=broll_dur,
             has_hook_audio=has_audio,
             vsl_lufs=vsl_lufs, ...)
             → filter_complex string
           encode_with_progress(audio_map="[a]")
             → ffmpeg subprocess → {stem}_seq_VSL.mp4
```

## Threading Model

```
Main thread (tkinter event loop)
  │
  ├─ root.after(100ms) → _poll_events()
  │       reads Queue → updates widgets
  │
  └─ Queue (thread-safe)
           ↑
  Worker thread (BatchWorker)
           emits: file_start, progress, file_done,
                  file_skip, file_error, log,
                  cancelled, all_done, fatal
```

## Filter Graph — Overlay

```
[0:v] (broll) ──► scale/blur/crop/pad ──► format=yuv420p (or yuva420p+fade) ──► [hook]
[1:v] (vsl)   ──► scale 1080x1920 ──────────────────────────────────────────► [base]
[base][hook]overlay=enable='lt(t,{broll_dur})':eof_action=pass ──────────────► [v]
Audio map: 1:a (VSL audio direct, no re-encode in filter graph)
```

## Filter Graph — Sequential

```
[0:v] (hook) ──► scale/blur/crop/pad ──► format=yuv420p ──────────────► [v_hook]
[1:v] (vsl)  ──► scale 1080x1920 ──────────────────────────────────────► [v_vsl]
[v_hook][v_vsl] xfade=fade:d={fade}:offset={hook-fade},format=yuv420p ──► [v]

[0:a] (hook audio, or aevalsrc silence) ──► [loudnorm?] ──► aresample ──► [a_hook]
[1:a] (vsl  audio)                      ──────────────────► aresample ──► [a_vsl]
[a_hook][a_vsl] acrossfade=d={fade} ──────────────────────────────────► [a]
```

> **Note:** `format=yuv420p` after `xfade` is mandatory — xfade internally negotiates
> `yuv444p` even when inputs are `yuv420p`, causing libx264 high-profile to reject the stream.

## Key Files

| File | Lines | Responsibility |
|---|---|---|
| `vsl_hook_merger.py` | ~295 | tkinter GUI, event polling, settings I/O |
| `worker.py` | ~145 | BatchWorker thread, JobConfig, workflow dispatch |
| `ffmpeg_runner.py` | ~180 | subprocess: probe_duration, probe_has_audio, probe_lufs, encode_with_progress |
| `filter_graph_builder.py` | ~175 | pure filter string builders (overlay, sequential, dispatcher) |
| `settings.py` | ~42 | load/save JSON to `~/.vsl-hook-merger.json` |
| `tests/` | 3 files | 36 unit/integration tests |
