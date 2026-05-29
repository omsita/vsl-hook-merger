"""Background worker thread that runs the batch encode and reports events.

The GUI polls a thread-safe Queue and renders progress without freezing.
"""
import threading
from dataclasses import dataclass, field
from pathlib import Path
from queue import Queue

from ffmpeg_runner import (
    encode_with_progress,
    probe_duration,
    probe_has_audio,
    probe_lufs,
)
from filter_graph_builder import build_filter


@dataclass
class JobConfig:
    """Snapshot of UI state at the moment the user clicks Start."""
    ffmpeg: str
    ffprobe: str
    vsl: Path
    output_dir: Path
    brolls: list[Path]
    crf: int
    non_916_mode: str
    skip_existing: bool
    fade_duration: float = 0.0   # seconds; 0 = hard cut hook -> VSL
    workflow: str = "overlay"    # "overlay" | "sequential"
    normalize_audio: bool = True  # only used when workflow == "sequential"
    use_nvenc: bool = False      # h264_nvenc (GPU) instead of libx264 (CPU)


class BatchWorker(threading.Thread):
    """Daemon thread; emits dict events to a Queue for the GUI to consume.

    Event kinds:
      file_start  {idx, total, name}
      progress    {idx, value}       # 0..1
      file_done   {idx, name, path, size_mb}
      file_skip   {idx, name, path}
      file_error  {idx, name, error}
      log         {msg}
      cancelled   {}
      all_done    {}
      fatal       {error}
    """

    def __init__(self, cfg: JobConfig, events: Queue):
        super().__init__(daemon=True)
        self.cfg = cfg
        self.events = events
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def is_cancelled(self) -> bool:
        return self._cancel.is_set()

    def _emit(self, kind: str, **data) -> None:
        self.events.put({"kind": kind, **data})

    def _output_suffix(self) -> str:
        """Return filename suffix based on workflow."""
        return "_seq_VSL" if self.cfg.workflow == "sequential" else "_hook_VSL"

    def run(self) -> None:
        try:
            vsl_dur = probe_duration(self.cfg.ffprobe, self.cfg.vsl)
        except Exception as e:
            self._emit("fatal", error=f"Cannot probe VSL: {e}")
            return

        # --- Sequential-only: measure VSL LUFS once before the per-broll loop ---
        vsl_lufs: float | None = None
        if self.cfg.workflow == "sequential" and self.cfg.normalize_audio:
            self._emit("log", msg="Measuring VSL loudness…")
            try:
                vsl_lufs = probe_lufs(self.cfg.ffmpeg, self.cfg.vsl)
                self._emit("log", msg=f"VSL loudness: {vsl_lufs:.1f} LUFS")
            except Exception as e:
                self._emit("log", msg=f"LUFS probe failed, skipping loudnorm ({e})")
                vsl_lufs = None  # graceful degradation — batch continues

        total = len(self.cfg.brolls)
        self.cfg.output_dir.mkdir(parents=True, exist_ok=True)
        suffix = self._output_suffix()

        for idx, broll in enumerate(self.cfg.brolls, start=1):
            if self.is_cancelled():
                self._emit("cancelled")
                return

            out_path = self.cfg.output_dir / f"{broll.stem}{suffix}.mp4"
            self._emit("file_start", idx=idx, total=total, name=broll.name)

            if self.cfg.skip_existing and out_path.exists():
                self._emit("file_skip", idx=idx, name=broll.name, path=str(out_path))
                continue

            try:
                broll_dur = probe_duration(self.cfg.ffprobe, broll)
            except Exception as e:
                self._emit("file_error", idx=idx, name=broll.name, error=f"probe: {e}")
                continue

            if self.cfg.workflow == "sequential":
                # Probe whether the hook clip has an audio stream (skip for overlay —
                # overlay drops hook audio entirely so we never need to know).
                try:
                    has_hook_audio = probe_has_audio(self.cfg.ffprobe, broll)
                except Exception:
                    has_hook_audio = False

                filt = build_filter(
                    "sequential",
                    hook_duration=broll_dur,
                    mode=self.cfg.non_916_mode,
                    fade_duration=self.cfg.fade_duration,
                    has_hook_audio=has_hook_audio,
                    vsl_lufs=vsl_lufs,
                )
                # Sequential total ≈ hook + vsl − fade, but never less than vsl alone.
                fade_clamped = max(0.05, min(self.cfg.fade_duration, broll_dur * 0.5))
                total_duration = max(vsl_dur, broll_dur + vsl_dur - fade_clamped)
                audio_map = "[a]"  # acrossfade filter output
            else:
                filt = build_filter(
                    "overlay",
                    broll_duration=broll_dur,
                    mode=self.cfg.non_916_mode,
                    fade_duration=self.cfg.fade_duration,
                )
                total_duration = vsl_dur
                audio_map = "1:a"  # VSL audio passes through directly

            rc = encode_with_progress(
                ffmpeg=self.cfg.ffmpeg,
                broll=broll,
                vsl=self.cfg.vsl,
                output=out_path,
                filter_complex=filt,
                crf=self.cfg.crf,
                total_duration=total_duration,
                on_progress=lambda p, i=idx: self._emit("progress", idx=i, value=p),
                on_log=lambda m: self._emit("log", msg=m),
                is_cancelled=self.is_cancelled,
                audio_map=audio_map,
                use_nvenc=self.cfg.use_nvenc,
            )

            if self.is_cancelled():
                # Best-effort: remove the partial output so a re-run doesn't skip it.
                try:
                    if out_path.exists():
                        out_path.unlink()
                except OSError:
                    pass
                self._emit("cancelled")
                return

            if rc == 0 and out_path.exists():
                size_mb = out_path.stat().st_size / (1024 * 1024)
                self._emit("file_done", idx=idx, name=broll.name,
                           path=str(out_path), size_mb=size_mb)
            else:
                self._emit("file_error", idx=idx, name=broll.name,
                           error=f"ffmpeg exit {rc}")

        self._emit("all_done")
