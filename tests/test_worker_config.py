"""Tests for JobConfig new fields and worker output-name logic (Phase 3).

No real ffmpeg required — these are pure unit tests.

Run from project root::

    python -m pytest tests/test_worker_config.py -v
"""
import sys
from pathlib import Path
from queue import Queue

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from worker import BatchWorker, JobConfig  # noqa: E402
from settings import DEFAULT  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_cfg(**overrides) -> JobConfig:
    base = dict(
        ffmpeg="ffmpeg",
        ffprobe="ffprobe",
        vsl=Path("dummy_vsl.mp4"),
        output_dir=Path("output"),
        brolls=[],
        crf=23,
        non_916_mode="blur",
        skip_existing=True,
    )
    base.update(overrides)
    return JobConfig(**base)


# ---------------------------------------------------------------------------
# JobConfig field defaults
# ---------------------------------------------------------------------------

def test_job_config_workflow_default_is_overlay() -> None:
    cfg = _make_cfg()
    assert cfg.workflow == "overlay"


def test_job_config_normalize_audio_default_is_true() -> None:
    cfg = _make_cfg()
    assert cfg.normalize_audio is True


def test_job_config_sequential_workflow() -> None:
    cfg = _make_cfg(workflow="sequential")
    assert cfg.workflow == "sequential"
    assert cfg.normalize_audio is True  # still defaults to True


def test_job_config_sequential_normalize_off() -> None:
    cfg = _make_cfg(workflow="sequential", normalize_audio=False)
    assert cfg.normalize_audio is False


# ---------------------------------------------------------------------------
# Output filename suffix via _output_suffix()
# ---------------------------------------------------------------------------

def test_output_suffix_overlay() -> None:
    cfg = _make_cfg(workflow="overlay")
    worker = BatchWorker(cfg, Queue())
    assert worker._output_suffix() == "_hook_VSL"


def test_output_suffix_sequential() -> None:
    cfg = _make_cfg(workflow="sequential")
    worker = BatchWorker(cfg, Queue())
    assert worker._output_suffix() == "_seq_VSL"


# ---------------------------------------------------------------------------
# Settings DEFAULT keys present
# ---------------------------------------------------------------------------

def test_settings_default_has_workflow_key() -> None:
    assert "workflow" in DEFAULT
    assert DEFAULT["workflow"] == "overlay"


def test_settings_default_has_normalize_audio_key() -> None:
    assert "normalize_audio" in DEFAULT
    assert DEFAULT["normalize_audio"] is True


def test_settings_load_merges_missing_keys() -> None:
    """Simulate an old JSON dict that has no new keys; merge should fill defaults."""
    from settings import DEFAULT as DEFAULTS
    old_saved = {"ffmpeg_path": "/bin/ffmpeg", "vsl_path": "/video/vsl.mp4"}
    merged = {**DEFAULTS, **old_saved}
    assert merged["workflow"] == "overlay"
    assert merged["normalize_audio"] is True
    assert merged["ffmpeg_path"] == "/bin/ffmpeg"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    test_job_config_workflow_default_is_overlay()
    test_job_config_normalize_audio_default_is_true()
    test_job_config_sequential_workflow()
    test_job_config_sequential_normalize_off()
    test_output_suffix_overlay()
    test_output_suffix_sequential()
    test_settings_default_has_workflow_key()
    test_settings_default_has_normalize_audio_key()
    test_settings_load_merges_missing_keys()
    print("All 9 worker config tests passed")
