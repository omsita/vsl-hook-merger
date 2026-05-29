"""Smoke tests for the filter graph builder.

Run from project root::

    python -m tests.test_filter_graph_builder

or with pytest if installed::

    pytest tests/
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from filter_graph_builder import (  # noqa: E402
    build_overlay_filter,
    build_sequential_filter,
    build_filter,
)

# ---------------------------------------------------------------------------
# Overlay tests (original 10 — must remain green after refactor)
# ---------------------------------------------------------------------------

def test_blur_mode_contains_duration_and_blur() -> None:
    s = build_overlay_filter(6.083, "blur")
    assert "lt(t,6.083)" in s
    assert "boxblur" in s
    assert "[base][hook]overlay=" in s


def test_crop_mode_has_no_blur() -> None:
    s = build_overlay_filter(4.0, "crop")
    assert "boxblur" not in s
    assert "crop=1080:1920" in s


def test_pad_mode_letterbox() -> None:
    s = build_overlay_filter(10.0, "pad")
    assert "pad=1080:1920" in s
    assert "boxblur" not in s


def test_invalid_mode_raises() -> None:
    try:
        build_overlay_filter(5.0, "wat")  # type: ignore[arg-type]
    except ValueError:
        return
    raise AssertionError("Expected ValueError for unknown mode")


def test_duration_precision_3_decimals() -> None:
    s = build_overlay_filter(7.123456, "blur")
    assert "lt(t,7.123)" in s


def test_default_no_fade_keeps_yuv420p() -> None:
    s = build_overlay_filter(6.0, "blur")
    assert "format=yuv420p" in s
    assert "fade=out" not in s
    assert "yuva420p" not in s


def test_fade_emits_yuva_and_fade_with_correct_start() -> None:
    s = build_overlay_filter(6.0, "blur", fade_duration=0.3)
    assert "format=yuva420p" in s
    # fade should start at broll_duration - fade_duration
    assert "fade=out:st=5.700:d=0.300:alpha=1" in s


def test_fade_works_in_crop_and_pad_modes() -> None:
    for mode in ("crop", "pad"):
        s = build_overlay_filter(8.0, mode, fade_duration=0.5)  # type: ignore[arg-type]
        assert "format=yuva420p" in s
        assert "fade=out:st=7.500:d=0.500:alpha=1" in s


def test_fade_clamped_to_broll_duration() -> None:
    # Fade longer than broll itself -> clamp to broll length, fade across whole clip.
    s = build_overlay_filter(2.0, "blur", fade_duration=5.0)
    assert "fade=out:st=0.000:d=2.000:alpha=1" in s


def test_negative_fade_is_treated_as_zero() -> None:
    s = build_overlay_filter(5.0, "blur", fade_duration=-1.0)
    assert "fade=out" not in s
    assert "format=yuv420p" in s


# ---------------------------------------------------------------------------
# Sequential tests (6 new)
# ---------------------------------------------------------------------------

def test_sequential_basic_xfade_offset() -> None:
    """xfade offset == hook_dur - fade_dur; output label is [v]."""
    s = build_sequential_filter(6.0, "blur", fade_duration=0.3)
    # offset = 6.0 - 0.3 = 5.7; format=yuv420p must follow xfade
    assert "xfade=transition=fade:duration=0.300:offset=5.700,format=yuv420p[v]" in s
    assert "[v_hook][v_vsl]xfade=" in s


def test_sequential_with_loudnorm() -> None:
    """loudnorm=I=<vsl_lufs> present in hook audio chain when vsl_lufs given."""
    s = build_sequential_filter(6.0, "blur", fade_duration=0.3, vsl_lufs=-16.5)
    assert "loudnorm=I=-16.5:LRA=11:TP=-1.5" in s


def test_sequential_without_loudnorm() -> None:
    """No loudnorm when vsl_lufs is None (hook passthrough with resample only)."""
    s = build_sequential_filter(6.0, "blur", fade_duration=0.3, vsl_lufs=None)
    assert "loudnorm" not in s
    assert "[0:a]aresample=44100" in s


def test_sequential_silent_hook() -> None:
    """aevalsrc silence injected when hook has no audio stream."""
    s = build_sequential_filter(6.0, "blur", fade_duration=0.3, has_hook_audio=False)
    assert "aevalsrc=0" in s
    # No [0:a] input — hook audio comes from generated silence source
    assert "[0:a]" not in s
    # VSL audio still mapped
    assert "[1:a]" in s


def test_sequential_non_916_blur() -> None:
    """Hook video chain uses blur treatment with [v_hook] output label."""
    s = build_sequential_filter(5.0, "blur", fade_duration=0.3)
    assert "boxblur" in s
    assert "[v_hook]" in s
    # No alpha fade in sequential video (xfade handles it)
    assert "yuva420p" not in s


def test_sequential_xfade_output_forced_yuv420p() -> None:
    """xfade output must be followed by format=yuv420p to prevent 4:4:4 encoder error.

    libx264 high profile does not support yuv444p, but xfade internally negotiates
    it even when both inputs are yuv420p.  Regression test for the encoder crash:
      x264 [error]: high profile doesn't support 4:4:4
    """
    s = build_sequential_filter(6.0, "blur", fade_duration=0.3)
    # format=yuv420p must appear immediately after xfade (before [v] label)
    assert "xfade=transition=fade:duration=0.300:offset=5.700,format=yuv420p[v]" in s


def test_overlay_unchanged_after_refactor() -> None:
    """Snapshot: overlay output is byte-for-byte identical after _build_hook_video_chain refactor."""
    expected = (
        "[0:v]split=2[bg][fg];"
        "[bg]scale=1080:1920:force_original_aspect_ratio=increase,"
        "crop=1080:1920,boxblur=20:5[bgs];"
        "[fg]scale=1080:1920:force_original_aspect_ratio=decrease[fgs];"
        "[bgs][fgs]overlay=(W-w)/2:(H-h)/2:eof_action=pass,"
        "setsar=1,fps=30,"
        "format=yuva420p,fade=out:st=5.783:d=0.300:alpha=1[hook];"
        "[1:v]scale=1080:1920,setsar=1,fps=30,format=yuv420p[base];"
        "[base][hook]overlay=enable='lt(t,6.083)':eof_action=pass[v]"
    )
    actual = build_overlay_filter(6.083, "blur", fade_duration=0.3)
    assert actual == expected, f"\nExpected:\n{expected}\n\nActual:\n{actual}"


# ---------------------------------------------------------------------------
# Dispatcher test
# ---------------------------------------------------------------------------

def test_build_filter_dispatcher_overlay() -> None:
    s1 = build_overlay_filter(5.0, "blur", 0.3)
    s2 = build_filter("overlay", broll_duration=5.0, mode="blur", fade_duration=0.3)
    assert s1 == s2


def test_build_filter_dispatcher_sequential() -> None:
    s1 = build_sequential_filter(5.0, "blur", 0.3)
    s2 = build_filter("sequential", hook_duration=5.0, mode="blur", fade_duration=0.3)
    assert s1 == s2


def test_build_filter_unknown_workflow_raises() -> None:
    try:
        build_filter("unknown")  # type: ignore[arg-type]
    except ValueError:
        return
    raise AssertionError("Expected ValueError for unknown workflow")


# ---------------------------------------------------------------------------
# Entry point for python -m tests.test_filter_graph_builder
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    test_blur_mode_contains_duration_and_blur()
    test_crop_mode_has_no_blur()
    test_pad_mode_letterbox()
    test_invalid_mode_raises()
    test_duration_precision_3_decimals()
    test_default_no_fade_keeps_yuv420p()
    test_fade_emits_yuva_and_fade_with_correct_start()
    test_fade_works_in_crop_and_pad_modes()
    test_fade_clamped_to_broll_duration()
    test_negative_fade_is_treated_as_zero()
    test_sequential_basic_xfade_offset()
    test_sequential_with_loudnorm()
    test_sequential_without_loudnorm()
    test_sequential_silent_hook()
    test_sequential_non_916_blur()
    test_overlay_unchanged_after_refactor()
    test_build_filter_dispatcher_overlay()
    test_build_filter_dispatcher_sequential()
    test_build_filter_unknown_workflow_raises()
    test_sequential_xfade_output_forced_yuv420p()
    print("All 20 tests passed")
