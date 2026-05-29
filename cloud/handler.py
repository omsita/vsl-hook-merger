"""RunPod Serverless handler for VSL Hook Merger cloud encoding.

Receives VSL + B-roll files, encodes with h264_nvenc, optionally pushes
output to Dropbox via rclone.

Expected input JSON::

    {
        "vsl_url": "https://...",          # presigned URL to download VSL
        "brolls": [
            {"name": "hook1.mp4", "url": "https://..."},
            ...
        ],
        "settings": {
            "crf": 23,
            "workflow": "overlay",          # overlay | sequential
            "non_916_mode": "blur",
            "fade_duration": 0.3,
            "normalize_audio": true
        },
        "dropbox_token": "...",            # optional — rclone token JSON
        "dropbox_path": "/VSL_Output"      # optional
    }
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

# Ensure filter_graph_builder is importable (copied into Docker image)
sys.path.insert(0, os.path.dirname(__file__))
from filter_graph_builder import build_filter

WORK = Path("/tmp/vsl_work")
FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"


def probe_duration(path: str) -> float:
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def probe_has_audio(path: str) -> bool:
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-select_streams", "a",
         "-show_entries", "stream=index", "-of", "csv=p=0", path],
        capture_output=True, text=True, check=True,
    )
    return bool(out.stdout.strip())


def probe_lufs(path: str) -> float:
    import re
    out = subprocess.run(
        [FFMPEG, "-hide_banner", "-nostats", "-i", path, "-vn",
         "-af", "loudnorm=I=-16:LRA=11:TP=-1.5:print_format=json",
         "-f", "null", "-"],
        capture_output=True, text=True, check=False,
    )
    m = re.search(r'\{[^{}]*"input_i"[^{}]*\}', out.stderr, re.DOTALL)
    if not m:
        return -16.0
    data = json.loads(m.group(0))
    try:
        lufs = float(data.get("input_i", "-16"))
    except (ValueError, TypeError):
        lufs = -16.0
    if lufs == float("-inf") or lufs != lufs:
        lufs = -70.0
    return max(-70.0, min(-5.0, lufs))


def setup_mega_rclone(mega_user: str, mega_pass: str) -> None:
    """Configure rclone MEGA remote on-the-fly via env vars.

    mega_pass should be rclone-obscured (from `rclone config dump`).
    """
    os.environ["RCLONE_CONFIG_MEGA_TYPE"] = "mega"
    os.environ["RCLONE_CONFIG_MEGA_USER"] = mega_user
    os.environ["RCLONE_CONFIG_MEGA_PASS"] = mega_pass


def download_file(source: str, dest: str) -> None:
    """Download a file from URL (wget) or MEGA path (rclone copy).

    source formats:
      - "mega:path/to/file.mp4"  → rclone copy
      - "https://..."            → wget
    """
    if source.startswith("mega:"):
        dest_dir = os.path.dirname(dest)
        subprocess.run(
            ["rclone", "copy", source, dest_dir, "--retries", "3"],
            check=True, timeout=1800,
        )
        # rclone preserves filename — rename to expected dest if different
        src_name = os.path.basename(source)
        actual = os.path.join(dest_dir, src_name)
        if actual != dest and os.path.exists(actual):
            os.rename(actual, dest)
    else:
        subprocess.run(
            ["wget", "-q", "--tries=3", "--timeout=60", source, "-O", dest],
            check=True, timeout=1800,
        )


def encode_one(vsl_path: str, broll_path: str, out_path: str,
               settings: dict, vsl_dur: float, vsl_lufs: float | None) -> dict:
    """Encode one B-roll+VSL pair. Returns result dict."""
    name = Path(broll_path).stem
    workflow = settings.get("workflow", "overlay")
    crf = settings.get("crf", 23)
    mode = settings.get("non_916_mode", "blur")
    fade = settings.get("fade_duration", 0.3)

    broll_dur = probe_duration(broll_path)

    if workflow == "sequential":
        try:
            has_audio = probe_has_audio(broll_path)
        except Exception:
            has_audio = False
        filt = build_filter(
            "sequential",
            hook_duration=broll_dur, mode=mode, fade_duration=fade,
            has_hook_audio=has_audio, vsl_lufs=vsl_lufs,
        )
        fade_clamped = max(0.05, min(fade, broll_dur * 0.5))
        total_dur = max(vsl_dur, broll_dur + vsl_dur - fade_clamped)
        audio_map = "[a]"
    else:
        filt = build_filter(
            "overlay",
            broll_duration=broll_dur, mode=mode, fade_duration=fade,
        )
        total_dur = vsl_dur
        audio_map = "1:a"

    cmd = [
        FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
        "-i", broll_path, "-i", vsl_path,
        "-filter_complex", filt,
        "-map", "[v]", "-map", audio_map,
        "-c:v", "h264_nvenc", "-preset", "p4",
        "-rc", "vbr", "-cq", str(crf), "-b:v", "0",
        "-profile:v", "high",
        "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2",
        "-movflags", "+faststart", "-r", "30",
        out_path,
    ]

    t0 = time.time()
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    elapsed = time.time() - t0

    if r.returncode == 0 and os.path.exists(out_path):
        size_mb = os.path.getsize(out_path) / (1024 * 1024)
        return {"name": name, "status": "ok", "size_mb": round(size_mb, 1),
                "seconds": round(elapsed, 1)}
    else:
        return {"name": name, "status": "error",
                "error": r.stderr[:500] if r.stderr else f"exit {r.returncode}"}


def push_to_dropbox(output_dir: str, token: str, remote_path: str) -> int:
    """Upload output files to Dropbox via rclone. Returns count uploaded."""
    os.environ["RCLONE_CONFIG_DBX_TYPE"] = "dropbox"
    os.environ["RCLONE_CONFIG_DBX_TOKEN"] = token
    r = subprocess.run(
        ["rclone", "copy", output_dir, f"dbx:{remote_path}/",
         "--transfers", "4", "--retries", "3"],
        capture_output=True, text=True, timeout=1800,
    )
    if r.returncode != 0:
        return 0
    files = [f for f in os.listdir(output_dir) if f.endswith(".mp4")]
    return len(files)


def handler(event: dict) -> dict:
    """RunPod serverless handler entry point."""
    job_input = event["input"]

    vsl_source = job_input["vsl_url"]  # URL or "mega:path/to/file"
    brolls = job_input.get("brolls", [])
    settings = job_input.get("settings", {})
    dropbox_token = job_input.get("dropbox_token")
    dropbox_path = job_input.get("dropbox_path", "/VSL_Output")

    # Setup MEGA rclone if credentials provided
    mega_user = job_input.get("mega_user")
    mega_pass = job_input.get("mega_pass")
    if mega_user and mega_pass:
        setup_mega_rclone(mega_user, mega_pass)

    workflow = settings.get("workflow", "overlay")
    suffix = "_seq_VSL" if workflow == "sequential" else "_hook_VSL"

    # Setup work dirs
    for d in [WORK / "brolls", WORK / "output"]:
        d.mkdir(parents=True, exist_ok=True)

    # Download VSL
    vsl_path = str(WORK / "vsl.mp4")
    download_file(vsl_source, vsl_path)
    vsl_dur = probe_duration(vsl_path)

    # LUFS probe for sequential + normalize
    vsl_lufs = None
    if workflow == "sequential" and settings.get("normalize_audio", True):
        vsl_lufs = probe_lufs(vsl_path)

    # Download B-rolls
    broll_paths = []
    for br in brolls:
        dest = str(WORK / "brolls" / br["name"])
        source = br.get("url") or br.get("mega_path")
        download_file(source, dest)
        broll_paths.append(dest)

    # Encode all — parallel FFmpeg processes to maximize GPU NVENC utilization.
    # RTX 4090 supports 3 concurrent NVENC sessions; CPU EPYC handles the rest.
    from concurrent.futures import ThreadPoolExecutor

    def _encode_task(bp):
        stem = Path(bp).stem
        out = str(WORK / "output" / f"{stem}{suffix}.mp4")
        return encode_one(vsl_path, bp, out, settings, vsl_dur, vsl_lufs)

    max_parallel = min(3, len(broll_paths))
    with ThreadPoolExecutor(max_workers=max_parallel) as pool:
        results = list(pool.map(_encode_task, broll_paths))

    # Push to Dropbox if configured
    uploaded = 0
    if dropbox_token:
        uploaded = push_to_dropbox(
            str(WORK / "output"), dropbox_token, dropbox_path,
        )

    ok_count = sum(1 for r in results if r["status"] == "ok")
    return {
        "status": "success" if ok_count > 0 else "error",
        "total": len(brolls),
        "encoded": ok_count,
        "uploaded_to_dropbox": uploaded,
        "dropbox_path": dropbox_path if uploaded else None,
        "results": results,
    }


if __name__ == "__main__":
    # Local test mode
    try:
        import runpod
        runpod.serverless.start({"handler": handler})
    except ImportError:
        # No runpod SDK — run with test_input.json
        import json
        test_file = Path(__file__).parent / "test_input.json"
        if test_file.exists():
            with open(test_file) as f:
                test_event = {"input": json.load(f)}
            result = handler(test_event)
            print(json.dumps(result, indent=2))
        else:
            print("No runpod SDK and no test_input.json — nothing to do")
