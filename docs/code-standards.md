# Code Standards

## Language & Runtime

- Python 3.10+ (uses `X | Y` union type syntax, `match`-compatible)
- stdlib only — no `pip install` required
- All files UTF-8 encoded

## File Naming

Python modules use **snake_case** (import requirement).  
Tests use `test_{module}.py` naming under `tests/`.

## Module Size Limit

Keep individual `.py` files under **200 lines**. If a file grows beyond that, extract a focused sub-module (e.g. pull filter helpers into a separate file).

## Type Annotations

- Use `X | None` (Python 3.10+), not `Optional[X]`
- Annotate all public function signatures
- Private helpers (prefix `_`) may omit annotations when obvious

## Docstrings

- Module-level: one-liner purpose statement
- Public functions: Google-style short summary + Parameters/Returns when non-obvious
- Private helpers: one-liner is sufficient

## Error Handling

- Worker thread: wrap every external call (probe, encode) in `try/except Exception`; emit `log` or `file_error` events — never let exceptions propagate silently
- `probe_lufs` failure is **graceful** — set `vsl_lufs = None`, batch continues
- GUI: show `messagebox.showerror` only for fatal pre-flight errors (bad ffmpeg path, no VSL selected)

## Subprocess Calls

- Always pass `creationflags=_no_window_flag()` to hide console window on Windows
- Use `check=True` for probing calls (ffprobe); use `check=False` for ffmpeg encode/measure (return code checked manually)
- Decode with `errors="replace"` to survive non-ASCII in ffmpeg stderr

## Filter Graph Builder

- `build_overlay_filter` and `build_sequential_filter` are **pure functions** — no side effects, no subprocess calls
- Return single-line strings (no embedded newlines) — ffmpeg `-filter_complex` accepts them as one argument
- Always end video chain with explicit `format=yuv420p` (or `yuva420p` for alpha overlay)
- Always add `format=yuv420p` **after** `xfade` — xfade internally negotiates `yuv444p`

## Settings

- New keys added to `DEFAULT` dict in `settings.py` — old JSON files missing the key load cleanly via `{**DEFAULT, **saved}` merge
- Never raise in `load()` or `save()` — silently degrade

## Testing

- Run with: `python -m pytest tests/ -v -p no:asyncio`  
  (system has `pytest-asyncio` version mismatch; `-p no:asyncio` disables the broken plugin)
- Tests that require ffmpeg use `pytest.mark.skipif(not shutil.which("ffmpeg"), ...)`
- Filter-graph tests are pure string assertions — no ffmpeg required
- Snapshot test `test_overlay_unchanged_after_refactor` pins the exact overlay filter string; update it intentionally if the filter changes

## Commit Conventions

```
feat: add sequential workflow with xfade+acrossfade
fix: force yuv420p after xfade to prevent 4:4:4 encoder error
refactor: extract _build_hook_video_chain helper
test: add probe_lufs integration test with anullsrc fixture
```

No AI references in commit messages.
