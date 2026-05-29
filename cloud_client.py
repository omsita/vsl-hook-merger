"""RunPod Serverless client for cloud batch encoding.

Uploads VSL + B-rolls to a temporary file host, splits B-rolls across N
workers, submits jobs, polls status, and emits events to the same Queue
the GUI already consumes.
"""

import json
import math
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from queue import Queue
from typing import Optional

import requests


RUNPOD_API = "https://api.runpod.ai/v2"


@dataclass
class CloudJobConfig:
    """Settings for a cloud batch run."""
    runpod_api_key: str
    endpoint_id: str
    vsl: Path
    brolls: list[Path]
    crf: int
    workflow: str
    non_916_mode: str
    fade_duration: float
    normalize_audio: bool
    max_workers: int = 5
    dropbox_token: str = ""
    dropbox_path: str = "/VSL_Output"


class CloudBatchWorker(threading.Thread):
    """Daemon thread that manages cloud rendering jobs.

    Emits the same event dict format as worker.BatchWorker so the GUI
    can handle both local and cloud transparently.

    Event kinds emitted:
      log          {msg}
      file_start   {idx, total, name}
      progress     {idx, value}
      file_done    {idx, name, path, size_mb}
      file_error   {idx, name, error}
      all_done     {}
      cancelled    {}
      fatal        {error}
    """

    def __init__(self, cfg: CloudJobConfig, events: Queue):
        super().__init__(daemon=True)
        self.cfg = cfg
        self.events = events
        self._cancel = threading.Event()
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {cfg.runpod_api_key}",
            "Content-Type": "application/json",
        })

    def cancel(self) -> None:
        self._cancel.set()

    def is_cancelled(self) -> bool:
        return self._cancel.is_set()

    def _emit(self, kind: str, **data) -> None:
        self.events.put({"kind": kind, **data})

    def run(self) -> None:
        try:
            self._run_pipeline()
        except Exception as e:
            self._emit("fatal", error=str(e))

    def _run_pipeline(self) -> None:
        cfg = self.cfg
        total_brolls = len(cfg.brolls)

        # --- Step 1: Upload files to get presigned URLs ---
        self._emit("log", msg=f"Uploading VSL + {total_brolls} B-rolls...")

        vsl_url = self._upload_file(cfg.vsl, "Uploading VSL")
        if not vsl_url:
            self._emit("fatal", error="Failed to upload VSL")
            return

        if self.is_cancelled():
            self._emit("cancelled")
            return

        broll_entries = []
        for i, br in enumerate(cfg.brolls):
            if self.is_cancelled():
                self._emit("cancelled")
                return
            self._emit("log", msg=f"  Upload B-roll {i+1}/{total_brolls}: {br.name}")
            url = self._upload_file(br, f"B-roll {i+1}/{total_brolls}")
            if url:
                broll_entries.append({"name": br.name, "url": url})
            else:
                self._emit("log", msg=f"  SKIP upload failed: {br.name}")

        if not broll_entries:
            self._emit("fatal", error="No B-rolls uploaded successfully")
            return

        self._emit("log", msg=f"Upload done: VSL + {len(broll_entries)} B-rolls")

        # --- Step 2: Split B-rolls across workers ---
        n_workers = min(cfg.max_workers, len(broll_entries))
        chunks = self._split_list(broll_entries, n_workers)
        self._emit("log", msg=f"Splitting into {len(chunks)} workers "
                   f"({[len(c) for c in chunks]} files each)")

        settings = {
            "crf": cfg.crf,
            "workflow": cfg.workflow,
            "non_916_mode": cfg.non_916_mode,
            "fade_duration": cfg.fade_duration,
            "normalize_audio": cfg.normalize_audio,
        }

        # --- Step 3: Submit jobs ---
        job_ids = []
        for i, chunk in enumerate(chunks):
            if self.is_cancelled():
                self._emit("cancelled")
                return

            payload = {
                "input": {
                    "vsl_url": vsl_url,
                    "brolls": chunk,
                    "settings": settings,
                }
            }
            if cfg.dropbox_token:
                payload["input"]["dropbox_token"] = cfg.dropbox_token
                payload["input"]["dropbox_path"] = cfg.dropbox_path

            job_id = self._submit_job(payload)
            if job_id:
                job_ids.append({"id": job_id, "chunk": chunk, "worker": i + 1})
                self._emit("log", msg=f"  Worker {i+1}: job {job_id} "
                           f"({len(chunk)} files)")
            else:
                self._emit("log", msg=f"  Worker {i+1}: FAILED to submit")
                for br in chunk:
                    self._emit("file_error", idx=0, name=br["name"],
                               error="Job submit failed")

        if not job_ids:
            self._emit("fatal", error="No jobs submitted successfully")
            return

        self._emit("log", msg=f"Submitted {len(job_ids)} jobs, polling...")

        # --- Step 4: Poll all jobs ---
        completed_jobs = set()
        file_idx = 0

        while len(completed_jobs) < len(job_ids):
            if self.is_cancelled():
                self._cancel_jobs(job_ids)
                self._emit("cancelled")
                return

            time.sleep(5)

            for job in job_ids:
                if job["id"] in completed_jobs:
                    continue

                status = self._check_job(job["id"])
                if not status:
                    continue

                state = status.get("status")

                if state == "IN_PROGRESS":
                    self._emit("log",
                               msg=f"  Worker {job['worker']}: encoding...")
                elif state == "COMPLETED":
                    completed_jobs.add(job["id"])
                    output = status.get("output", {})
                    results = output.get("results", [])

                    for r in results:
                        file_idx += 1
                        name = r.get("name", "?")
                        if r.get("status") == "ok":
                            self._emit("file_start", idx=file_idx,
                                       total=total_brolls, name=name)
                            self._emit("progress", idx=file_idx, value=1.0)
                            size = r.get("size_mb", 0)
                            path = r.get("name", "")
                            if cfg.dropbox_token:
                                path = f"Dropbox:{cfg.dropbox_path}/{name}"
                            self._emit("file_done", idx=file_idx, name=name,
                                       path=path, size_mb=size)
                        else:
                            self._emit("file_start", idx=file_idx,
                                       total=total_brolls, name=name)
                            self._emit("file_error", idx=file_idx, name=name,
                                       error=r.get("error", "unknown"))

                    uploaded = output.get("uploaded_to_dropbox", 0)
                    encoded = output.get("encoded", 0)
                    self._emit("log",
                               msg=f"  Worker {job['worker']}: done "
                               f"({encoded} encoded, {uploaded} uploaded)")

                elif state == "FAILED":
                    completed_jobs.add(job["id"])
                    error = status.get("error", "Unknown error")
                    self._emit("log",
                               msg=f"  Worker {job['worker']}: FAILED — {error}")
                    for br in job["chunk"]:
                        file_idx += 1
                        self._emit("file_error", idx=file_idx, name=br["name"],
                                   error=f"Worker failed: {error}")

        self._emit("all_done")

    # ----------------------------------------------------------------
    # RunPod API helpers
    # ----------------------------------------------------------------

    def _submit_job(self, payload: dict) -> Optional[str]:
        """Submit async job to RunPod endpoint. Returns job ID or None."""
        url = f"{RUNPOD_API}/{self.cfg.endpoint_id}/run"
        try:
            r = self._session.post(url, json=payload, timeout=30)
            r.raise_for_status()
            return r.json().get("id")
        except Exception as e:
            self._emit("log", msg=f"Submit error: {e}")
            return None

    def _check_job(self, job_id: str) -> Optional[dict]:
        """Check job status. Returns status dict or None on error."""
        url = f"{RUNPOD_API}/{self.cfg.endpoint_id}/status/{job_id}"
        try:
            r = self._session.get(url, timeout=15)
            r.raise_for_status()
            return r.json()
        except Exception:
            return None

    def _cancel_jobs(self, jobs: list[dict]) -> None:
        """Best-effort cancel all running jobs."""
        for job in jobs:
            url = f"{RUNPOD_API}/{self.cfg.endpoint_id}/cancel/{job['id']}"
            try:
                self._session.post(url, timeout=10)
            except Exception:
                pass

    # ----------------------------------------------------------------
    # File upload via RunPod presigned URL
    # ----------------------------------------------------------------

    def _upload_file(self, path: Path, label: str = "") -> Optional[str]:
        """Upload file and return a download URL.

        Uses RunPod's built-in blob storage for serverless file transfer.
        Falls back to base64 inline if file is small enough (<10MB).
        """
        file_size = path.stat().st_size

        # For files up to 10MB, use base64 inline (no upload needed).
        # The handler accepts both URL and inline data.
        if file_size < 10 * 1024 * 1024:
            return self._file_to_data_url(path)

        # Use RunPod's presigned upload
        upload_url = self._get_presigned_upload_url(path.name)
        if not upload_url:
            return None

        try:
            with open(path, "rb") as f:
                r = requests.put(
                    upload_url["put_url"],
                    data=f,
                    headers={"Content-Type": "application/octet-stream"},
                    timeout=600,
                )
                r.raise_for_status()
            return upload_url["get_url"]
        except Exception as e:
            self._emit("log", msg=f"Upload failed ({label}): {e}")
            return None

    def _get_presigned_upload_url(self, filename: str) -> Optional[dict]:
        """Get presigned PUT/GET URLs from RunPod blob storage."""
        url = f"{RUNPOD_API}/{self.cfg.endpoint_id}/upload"
        try:
            r = self._session.post(
                url, json={"name": filename}, timeout=15,
            )
            r.raise_for_status()
            data = r.json()
            return {"put_url": data["presignedUrl"], "get_url": data["url"]}
        except Exception:
            # Fallback: no presigned URL support → use data URL for
            # files up to 50MB (RunPod payload limit)
            return None

    def _file_to_data_url(self, path: Path) -> str:
        """Encode file as base64 data URL for inline transfer."""
        import base64
        with open(path, "rb") as f:
            data = base64.b64encode(f.read()).decode("ascii")
        return f"data:application/octet-stream;base64,{data}"

    # ----------------------------------------------------------------
    # Utility
    # ----------------------------------------------------------------

    @staticmethod
    def _split_list(items: list, n: int) -> list[list]:
        """Split items into n roughly equal chunks."""
        if n <= 0:
            return [items]
        k = math.ceil(len(items) / n)
        return [items[i:i + k] for i in range(0, len(items), k)]
