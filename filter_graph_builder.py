"""Build FFmpeg filter_complex strings for VSL hook merging.

Supports two workflows:
- Overlay: B-roll overlaid on VSL start; VSL audio continuous; B-roll muted.
- Sequential: Hook plays first (own audio+video), then xfade+acrossfade into VSL.

Both output 1080x1920 vertical video suitable for FB Reels / TikTok.
"""
from typing import Literal

Mode = Literal["blur", "crop", "pad"]


# ---------------------------------------------------------------------------
# Private helper
# ---------------------------------------------------------------------------

def _build_hook_video_chain(
    mode: Mode,
    hook_tail_fmt: str,
    out_label: str = "hook",
) -> str:
    """Return the filter fragment that scales/pads/blurs hook video into 1080x1920.

    Parameters
    ----------
    mode : 'blur' | 'crop' | 'pad'
        Non-9:16 treatment strategy.
    hook_tail_fmt : str
        Final format filter(s) appended before the output label.
        e.g. ``"format=yuv420p"`` (sequential/hard-cut) or
        ``"format=yuva420p,fade=out:st=5.7:d=0.3:alpha=1"`` (overlay fade).
    out_label : str
        Output pad label without brackets, e.g. ``"hook"`` or ``"v_hook"``.
    """
    label = f"[{out_label}]"
    if mode == "blur":
        return (
            "[0:v]split=2[bg][fg];"
            "[bg]scale=1080:1920:force_original_aspect_ratio=increase,"
            "crop=1080:1920,boxblur=20:5[bgs];"
            "[fg]scale=1080:1920:force_original_aspect_ratio=decrease[fgs];"
            f"[bgs][fgs]overlay=(W-w)/2:(H-h)/2:eof_action=pass,"
            f"setsar=1,fps=30,{hook_tail_fmt}{label};"
        )
    elif mode == "crop":
        return (
            "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,"
            f"crop=1080:1920,setsar=1,fps=30,{hook_tail_fmt}{label};"
        )
    elif mode == "pad":
        return (
            "[0:v]scale=1080:1920:force_original_aspect_ratio=decrease,"
            "pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black,"
            f"setsar=1,fps=30,{hook_tail_fmt}{label};"
        )
    else:
        raise ValueError(f"Unknown mode: {mode!r}")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_overlay_filter(
    broll_duration: float,
    mode: Mode = "blur",
    fade_duration: float = 0.0,
) -> str:
    """Return a single-line filter_complex string for the Overlay workflow.

    The B-roll (input 0) covers the VSL (input 1) for its natural duration,
    then the VSL shows through. VSL audio plays from t=0; B-roll audio is
    dropped by the caller (no -map 0:a).

    Parameters
    ----------
    broll_duration : float
        Length of the B-roll in seconds.
    mode : 'blur' | 'crop' | 'pad'
        Non-9:16 treatment strategy.
    fade_duration : float
        Fade-out alpha length in seconds (hook→VSL). 0 = hard cut.
        Clamped to [0, broll_duration].
    """
    dur = f"{broll_duration:.3f}"

    # Clamp fade so it never exceeds the B-roll itself.
    fade = max(0.0, min(fade_duration, broll_duration))

    if fade > 0.0:
        fade_start = max(0.0, broll_duration - fade)
        hook_tail_fmt = (
            f"format=yuva420p,fade=out:st={fade_start:.3f}:d={fade:.3f}:alpha=1"
        )
    else:
        hook_tail_fmt = "format=yuv420p"

    hook = _build_hook_video_chain(mode, hook_tail_fmt, "hook")
    base = "[1:v]scale=1080:1920,setsar=1,fps=30,format=yuv420p[base];"
    composite = f"[base][hook]overlay=enable='lt(t,{dur})':eof_action=pass[v]"

    return hook + base + composite


def build_sequential_filter(
    hook_duration: float,
    mode: Mode = "blur",
    fade_duration: float = 0.3,
    has_hook_audio: bool = True,
    vsl_lufs: float | None = None,
) -> str:
    """Return a single-line filter_complex string for the Sequential workflow.

    Hook (input 0) plays first at full quality with its own audio, then
    cross-fades into the VSL (input 1). Optionally applies loudnorm on hook
    audio to match VSL loudness so the transition sounds smooth.

    Parameters
    ----------
    hook_duration : float
        Length of the hook clip in seconds.
    mode : 'blur' | 'crop' | 'pad'
        Non-9:16 treatment for hook video.
    fade_duration : float
        Cross-fade duration in seconds. Clamped to [0.05, hook_duration * 0.5].
        xfade requires a positive value; half-clip cap prevents artifacts.
    has_hook_audio : bool
        If False, inject silence of hook_duration instead of reading [0:a].
        Use when hook has no audio stream at all.
    vsl_lufs : float | None
        Integrated LUFS of the VSL (from probe_lufs). When provided, apply
        loudnorm on hook audio to match this level. VSL audio passes through
        untouched. When None, hook audio is resampled but not loudnorm'd.

    Notes
    -----
    Output duration ≈ hook_duration + vsl_duration − fade_duration.
    Progress percentage in encode_with_progress should use this total.
    """
    # Clamp fade: ≥0.05s (xfade requires positive), ≤ half of hook to avoid artifacts
    fade = max(0.05, min(fade_duration, hook_duration * 0.5))
    fade_f = f"{fade:.3f}"
    xfade_offset = max(0.0, hook_duration - fade)

    # --- Video chains ---
    # Hook: same spatial treatment as overlay but plain yuv420p (xfade handles transition)
    hook_video = _build_hook_video_chain(mode, "format=yuv420p", "v_hook")
    vsl_video = "[1:v]scale=1080:1920,setsar=1,fps=30,format=yuv420p[v_vsl];"
    # Force yuv420p after xfade: xfade negotiates yuv444p internally even when
    # both inputs are yuv420p, which makes libx264 high-profile reject the stream.
    xfade = (
        f"[v_hook][v_vsl]xfade=transition=fade:duration={fade_f}"
        f":offset={xfade_offset:.3f},format=yuv420p[v];"
    )

    # --- Audio chains ---
    if has_hook_audio:
        if vsl_lufs is not None:
            # Match hook loudness to VSL so the crossfade sounds balanced
            lufs_f = f"{vsl_lufs:.1f}"
            hook_audio = (
                f"[0:a]loudnorm=I={lufs_f}:LRA=11:TP=-1.5,"
                "aresample=44100,"
                "aformat=channel_layouts=stereo:sample_rates=44100[a_hook];"
            )
        else:
            hook_audio = (
                "[0:a]aresample=44100,"
                "aformat=channel_layouts=stereo:sample_rates=44100[a_hook];"
            )
    else:
        # Hook has no audio stream — generate silence of exact hook duration.
        # Use channel_layout short form 'c' (not 'cl') for aevalsrc.
        hook_audio = (
            f"aevalsrc=0:d={hook_duration:.3f}:s=44100:c=stereo,"
            "aformat=channel_layouts=stereo:sample_rates=44100[a_hook];"
        )

    vsl_audio = (
        "[1:a]aresample=44100,"
        "aformat=channel_layouts=stereo:sample_rates=44100[a_vsl];"
    )
    acrossfade = f"[a_hook][a_vsl]acrossfade=d={fade_f}[a]"

    return hook_video + vsl_video + xfade + hook_audio + vsl_audio + acrossfade


def build_filter(
    workflow: Literal["overlay", "sequential"],
    **kwargs,
) -> str:
    """Dispatcher: route to overlay or sequential filter builder.

    Overlay kwargs  : broll_duration, mode, fade_duration
    Sequential kwargs: hook_duration, mode, fade_duration, has_hook_audio, vsl_lufs

    Raises ValueError for unknown workflow strings.
    """
    if workflow == "overlay":
        return build_overlay_filter(
            broll_duration=kwargs["broll_duration"],
            mode=kwargs.get("mode", "blur"),
            fade_duration=kwargs.get("fade_duration", 0.0),
        )
    if workflow == "sequential":
        return build_sequential_filter(
            hook_duration=kwargs["hook_duration"],
            mode=kwargs.get("mode", "blur"),
            fade_duration=kwargs.get("fade_duration", 0.3),
            has_hook_audio=kwargs.get("has_hook_audio", True),
            vsl_lufs=kwargs.get("vsl_lufs", None),
        )
    raise ValueError(
        f"Unknown workflow: {workflow!r}. Expected 'overlay' or 'sequential'."
    )
