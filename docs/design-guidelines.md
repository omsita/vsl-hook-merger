# Design Guidelines

## UI Layout Principles

- **Single window, no dialogs for progress** — all feedback (progress bars, log) lives in the main window.
- **Pack layout** — all frames use `pack` (not `grid`). Row order in the window matches logical workflow order: ffmpeg → VSL → B-rolls → output → options → progress → log.
- **Conditional visibility** — use `pack_forget()` / `pack(after=frame)` to show/hide widget rows based on selected workflow. Do not resize or grey-out rows; remove them cleanly.
- **Minimal window size**: 680×600. Default: 780×720. Resizable.

## Widget Conventions

| Widget type | Usage |
|---|---|
| `ttk.Entry` + `ttk.Button` | File/folder pickers |
| `ttk.Spinbox` | Numeric values (CRF, Fade) |
| `ttk.Combobox` | Enum choices (Non-9:16 mode) |
| `ttk.Radiobutton` | Mutually exclusive modes (Workflow) |
| `ttk.Checkbutton` | Boolean toggles (Skip existing, Normalize) |
| `ttk.Progressbar` | `mode="determinate"`, `maximum=1.0` |
| `tk.Text` (disabled) | Log output — enable/insert/disable pattern |

## Settings Persistence UX

- Settings save on **window close** and on **workflow radio button change** (immediate persist so changing workflow is never lost).
- FFmpeg path: auto-populated from PATH via "Auto" button on first run; user can override.
- Last used B-roll directory: remembered for the next "Add Files" dialog.

## Event Communication Pattern

Worker → GUI is **one-way via Queue**. Never call GUI methods from the worker thread. The GUI polls the Queue with `root.after(100, _poll_events)`.

Event kinds and their UI effect:

| Kind | UI action |
|---|---|
| `file_start` | Update current label + reset current progress bar |
| `progress` | Update current progress bar value |
| `file_done` | Log OK + size |
| `file_skip` | Log SKIP |
| `file_error` | Log FAILED |
| `log` | Append to log text widget |
| `cancelled` | Log + re-enable Start button |
| `all_done` | Set overall bar to 100%, log Done |
| `fatal` | Log + messagebox.showerror + re-enable Start |

## Log Format

```
=== Start batch (N files) [workflow] ===
Measuring VSL loudness…
VSL loudness: -23.5 LUFS
[1/3] Start: hook_A.mp4
$ ffmpeg ... -> hook_A_seq_VSL.mp4
  OK  (342.1 MB)  E:\output\hook_A_seq_VSL.mp4
[2/3] Start: hook_B.mp4
  SKIP (exists)  E:\output\hook_B_seq_VSL.mp4
=== Done ===
```

Keep log lines short. Truncate ffmpeg stderr to 600 chars to avoid flooding the log widget.
