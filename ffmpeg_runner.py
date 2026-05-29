"""FFmpeg subprocess wrapper: probe duration/audio + encode with progress reporting."""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable, Optional


def _no_window_flag() -> int:
    """Hide console window on Windows when ffmpeg spawns."""
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def find_ffmpeg(custom_path: str = "") -> Optional[str]:
    """Return absolute path to ffmpeg, or None if not found."""
    if custom_path and Path(custom_path).is_file():
        return custom_path
    return shutil.which("ffmpeg")


def find_ffprobe(ffmpeg_path: str = "") -> Optional[str]:
    """Locate ffprobe, preferring the sibling of a custom ffmpeg path."""
    if ffmpeg_path:
        sibling = Path(ffmpeg_path).with_name(
            "ffprobe.exe" if sys.platform == "win32" else "ffprobe"
        )
        if sibling.is_file():
            return str(sibling)
    return shutil.which("ffprobe")


def detect_nvenc(ffmpeg_path: str = "") -> bool:
    """Return True if ffmpeg supports h264_nvenc (NVIDIA GPU encoder).

    Runs ``ffmpeg -encoders`` and checks for h264_nvenc in the output.
    Returns False on any error (no GPU, driver issue, ffmpeg too old).
    """
    ffmpeg = ffmpeg_path or find_ffmpeg() or "ffmpeg"
    try:
        out = subprocess.run(
            [ffmpeg, "-hide_banner", "-encoders"],
            capture_output=True, text=True, timeout=10,
            creationflags=_no_window_flag(),
        )
        return "h264_nvenc" in out.stdout
    except Exception:
        return False


def probe_duration(ffprobe: str, path: Path) -> float:
    """Return duration in seconds for a media file."""
    out = subprocess.run(
        [
            ffprobe, "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True, text=True, check=True,
        creationflags=_no_window_flag(),
    )
    return float(out.stdout.strip())


def probe_has_audio(ffprobe: str, path: Path) -> bool:
    """Return True if the media file has at least one audio stream.

    Uses ffprobe to list audio stream indices. Empty output means no audio.
    Raises subprocess.CalledProcessError if ffprobe cannot open the file.
    """
    out = subprocess.run(
        [
            ffprobe, "-v", "error",
            "-select_streams", "a",
            "-show_entries", "stream=index",
            "-of", "csv=p=0",
            str(path),
        ],
        capture_output=True, text=True, errors="replace", check=True,
        creationflags=_no_window_flag(),
    )
    return bool(out.stdout.strip())


def probe_lufs(ffmpeg: str, path: Path) -> float:
    """Return integrated LUFS of the media file via loudnorm measure pass.

    Runs ffmpeg with ``-vn`` (skip video decode for speed) and the loudnorm
    filter in print_format=json mode.  The JSON block is emitted to STDERR at
    the end of the run; we parse the ``input_i`` field which is the EBU R128
    integrated loudness before any normalization.

    Runtime: ≈10–30 s for a 23-minute file on a typical machine.
    Call once per batch (from the worker thread), not per B-roll.

    Returns
    -------
    float
        Integrated LUFS in the range [-70.0, -5.0].

    Raises
    ------
    RuntimeError
        If loudnorm JSON is absent from ffmpeg output (file has no audio,
        is corrupt, or loudnorm filter is unavailable on this build).
    """
    out = subprocess.run(
        [
            ffmpeg, "-hide_banner", "-nostats",
            "-i", str(path),
            "-vn",
            "-af", "loudnorm=I=-16:LRA=11:TP=-1.5:print_format=json",
            "-f", "null", "-",
        ],
        capture_output=True, text=True, errors="replace", check=False,
        creationflags=_no_window_flag(),
    )

    # loudnorm prints JSON block to stderr at the end of the run
    m = re.search(r'\{[^{}]*"input_i"[^{}]*\}', out.stderr, re.DOTALL)
    if not m:
        # Surface the first 400 chars of stderr for diagnostics
        preview = out.stderr.strip()[:400] or "(empty stderr)"
        if "no such file" in preview.lower() or "invalid data" in preview.lower():
            raise RuntimeError(f"Cannot open file for LUFS probe: {path.name}")
        raise RuntimeError(
            f"Could not parse loudnorm output for {path.name}.\n"
            f"ffmpeg stderr: {preview}"
        )

    data = json.loads(m.group(0))
    raw = data.get("input_i", "-70")

    # loudnorm reports "-inf" for completely silent or very short clips
    try:
        lufs = float(raw)
    except (ValueError, TypeError):
        lufs = -70.0

    if lufs == float("-inf") or lufs != lufs:  # -inf or NaN
        lufs = -70.0

    # Clamp to a sane range so downstream filter math cannot produce garbage
    return max(-70.0, min(-5.0, lufs))


def encode_with_progress(
    ffmpeg: str,
    broll: Path,
    vsl: Path,
    output: Path,
    filter_complex: str,
    crf: int,
    total_duration: float,
    on_progress: Callable[[float], None],
    on_log: Callable[[str], None],
    is_cancelled: Callable[[], bool],
    audio_map: str = "1:a",
    use_nvenc: bool = False,
) -> int:
    """Encode one B-roll+VSL pair. Streams progress 0..1 to callback.

    Returns the ffmpeg process exit code (0 = success).
    Caller polls ``is_cancelled`` to request early termination.

    Parameters
    ----------
    audio_map : str
        FFmpeg stream specifier or filter label for the output audio.
        Use the default ``"1:a"`` for overlay mode (VSL audio direct).
        Use ``"[a]"`` for sequential mode (acrossfade filter output).
    use_nvenc : bool
        When True, use h264_nvenc (NVIDIA GPU) instead of libx264 (CPU).
        Typically 10-15x faster on RTX 3060/4090 with comparable quality
        for social media output (FB/TikTok re-encode anyway).
    """
    if use_nvenc:
        video_codec_args = [
            "-c:v", "h264_nvenc",
            "-preset", "p4",
            "-rc", "vbr", "-cq", str(crf), "-b:v", "0",
            "-profile:v", "high",
        ]
    else:
        video_codec_args = [
            "-c:v", "libx264", "-profile:v", "high", "-level", "4.1",
            "-preset", "medium", "-crf", str(crf),
        ]

    cmd = [
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(broll), "-i", str(vsl),
        "-filter_complex", filter_complex,
        "-map", "[v]", "-map", audio_map,
        *video_codec_args,
        "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2",
        "-movflags", "+faststart", "-r", "30",
        "-progress", "pipe:1", "-nostats",
        str(output),
    ]
    on_log(f"$ ffmpeg ... -> {output.name}")

    p = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        creationflags=_no_window_flag(),
    )

    try:
        assert p.stdout is not None
        for line in p.stdout:
            if is_cancelled():
                p.terminate()
                break
            line = line.strip()
            if line.startswith("out_time_us="):
                try:
                    micro = int(line.split("=", 1)[1])
                    pct = min(micro / 1_000_000.0 / total_duration, 1.0)
                    on_progress(pct)
                except ValueError:
                    pass
            elif line == "progress=end":
                on_progress(1.0)
    finally:
        p.wait()
        if p.returncode != 0 and not is_cancelled():
            err = (p.stderr.read() if p.stderr else "").strip()
            if err:
                on_log(f"ffmpeg stderr: {err[:600]}")

    return p.returncode
