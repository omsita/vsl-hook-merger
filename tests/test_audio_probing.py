"""Tests for probe_has_audio() and probe_lufs() in ffmpeg_runner.

Tests generate small synthetic fixtures via ffmpeg at runtime so they work
without shipping binary media files.  All tests are skipped automatically when
ffmpeg/ffprobe are not found on the PATH.

Run from project root::

    pytest tests/test_audio_probing.py -v
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ffmpeg_runner import probe_has_audio, probe_lufs  # noqa: E402

# ---------------------------------------------------------------------------
# Skip guard — require ffmpeg + ffprobe on PATH
# ---------------------------------------------------------------------------

FFMPEG = shutil.which("ffmpeg") or ""
FFPROBE = shutil.which("ffprobe") or ""

pytestmark = pytest.mark.skipif(
    not FFMPEG or not FFPROBE,
    reason="ffmpeg/ffprobe not found on PATH",
)

_NO_WIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _run(cmd: list[str]) -> None:
    """Run an ffmpeg command to create a test fixture; raise on failure."""
    subprocess.run(
        cmd, check=True, capture_output=True,
        creationflags=_NO_WIN,
    )


def make_tone_file(dest: Path, duration: float = 1.0, freq: int = 1000) -> None:
    """Synthesize a WAV file with a sine tone at maximum amplitude."""
    _run([
        FFMPEG, "-y", "-hide_banner",
        "-f", "lavfi",
        "-i", f"sine=frequency={freq}:duration={duration}",
        "-ar", "44100", "-ac", "2",
        str(dest),
    ])


def make_silence_file(dest: Path, duration: float = 1.0) -> None:
    """Synthesize a WAV file containing pure silence via anullsrc + -t."""
    _run([
        FFMPEG, "-y", "-hide_banner",
        "-f", "lavfi",
        "-i", "anullsrc=r=44100:cl=stereo",
        "-t", str(duration),
        str(dest),
    ])


def make_video_only_file(dest: Path, duration: float = 1.0) -> None:
    """Synthesize an MP4 file with video but NO audio stream."""
    _run([
        FFMPEG, "-y", "-hide_banner",
        "-f", "lavfi",
        "-i", f"color=c=black:s=1080x1920:r=30:d={duration}",
        "-an",  # no audio
        "-c:v", "libx264", "-preset", "ultrafast",
        str(dest),
    ])


# ---------------------------------------------------------------------------
# probe_has_audio tests
# ---------------------------------------------------------------------------

def test_has_audio_true_on_tone(tmp_path: Path) -> None:
    tone = tmp_path / "tone.wav"
    make_tone_file(tone)
    assert probe_has_audio(FFPROBE, tone) is True


def test_has_audio_false_on_video_only(tmp_path: Path) -> None:
    vid = tmp_path / "video_only.mp4"
    make_video_only_file(vid)
    assert probe_has_audio(FFPROBE, vid) is False


def test_has_audio_true_on_silence(tmp_path: Path) -> None:
    silence = tmp_path / "silence.wav"
    make_silence_file(silence)
    # Silent file still HAS an audio stream — it just contains zeros
    assert probe_has_audio(FFPROBE, silence) is True


# ---------------------------------------------------------------------------
# probe_lufs tests
# ---------------------------------------------------------------------------

def test_lufs_returns_negative_float(tmp_path: Path) -> None:
    """1kHz tone at max amplitude → LUFS should be a negative float."""
    tone = tmp_path / "tone.wav"
    make_tone_file(tone, duration=2.0)
    result = probe_lufs(FFMPEG, tone)
    assert isinstance(result, float)
    assert result < 0.0, f"LUFS must be negative, got {result}"
    # 1kHz full-scale sine → roughly -18 LUFS ± 5 is a reasonable sanity band
    assert -30.0 <= result <= -5.0, f"Unexpected LUFS value: {result}"


def test_lufs_on_silent_file_handled(tmp_path: Path) -> None:
    """Silent input → probe returns clamped floor (-70.0), not an exception."""
    silence = tmp_path / "silence.wav"
    make_silence_file(silence, duration=1.0)
    # Loudnorm reports -inf for silence; we clamp to -70.0
    result = probe_lufs(FFMPEG, silence)
    assert result == pytest.approx(-70.0), f"Expected -70.0 for silence, got {result}"


def test_lufs_raises_on_no_audio(tmp_path: Path) -> None:
    """Video-only file (no audio stream) → RuntimeError from missing loudnorm JSON."""
    vid = tmp_path / "video_only.mp4"
    make_video_only_file(vid)
    with pytest.raises(RuntimeError, match=r"(parse|open|audio)"):
        probe_lufs(FFMPEG, vid)


def test_lufs_clamped_to_sane_range(tmp_path: Path) -> None:
    """Result always in [-70, -5] regardless of input level."""
    tone = tmp_path / "tone.wav"
    make_tone_file(tone, duration=2.0)
    result = probe_lufs(FFMPEG, tone)
    assert -70.0 <= result <= -5.0
