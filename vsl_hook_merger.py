"""VSL Hook Merger - GUI for batch merging B-roll hooks with a main VSL.

Supports two workflows:
  Overlay   — B-roll covers VSL start (muted); VSL audio continuous.
  Sequential — Hook plays first (own audio), then xfade+acrossfade into VSL.

Run with::

    python vsl_hook_merger.py

or double-click run.bat on Windows.
"""
import os
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from queue import Empty, Queue
from tkinter import filedialog, messagebox, ttk

import settings as cfg_store
from cloud_client import CloudBatchWorker, CloudJobConfig
from ffmpeg_runner import detect_nvenc, find_ffmpeg, find_ffprobe
from worker import BatchWorker, JobConfig

APP_TITLE = "VSL Hook Merger"
POLL_MS = 100
VIDEO_FILETYPES = [("Video", "*.mp4 *.mov *.mkv *.m4v"), ("All files", "*.*")]


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("780x720")
        self.root.minsize(680, 600)

        self.cfg = cfg_store.load()
        self.events: Queue = Queue()
        self.worker: BatchWorker | None = None
        self.brolls: list[Path] = []
        self._run_total = 0  # set per Start so all_done can show "N/N"

        self._build_ui()
        self._restore_settings()
        self._poll_events()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------------------------------------------------------------- UI
    def _build_ui(self) -> None:
        pad = {"padx": 8, "pady": 4}
        outer = ttk.Frame(self.root, padding=10)
        outer.pack(fill="both", expand=True)

        # FFmpeg path row
        r = ttk.Frame(outer); r.pack(fill="x", **pad)
        ttk.Label(r, text="FFmpeg:", width=12).pack(side="left")
        self.var_ffmpeg = tk.StringVar()
        ttk.Entry(r, textvariable=self.var_ffmpeg).pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(r, text="Browse", command=self._pick_ffmpeg).pack(side="left")
        ttk.Button(r, text="Auto",   command=self._auto_ffmpeg).pack(side="left", padx=(4, 0))

        # VSL main row
        r = ttk.Frame(outer); r.pack(fill="x", **pad)
        ttk.Label(r, text="VSL chính:", width=12).pack(side="left")
        self.var_vsl = tk.StringVar()
        ttk.Entry(r, textvariable=self.var_vsl).pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(r, text="Browse", command=self._pick_vsl).pack(side="left")

        # B-roll controls row
        r = ttk.Frame(outer); r.pack(fill="x", **pad)
        ttk.Label(r, text="B-rolls:", width=12).pack(side="left")
        ttk.Button(r, text="Add Files",       command=self._add_files).pack(side="left", padx=2)
        ttk.Button(r, text="Add Folder",      command=self._add_folder).pack(side="left", padx=2)
        ttk.Button(r, text="Remove Selected", command=self._remove_selected).pack(side="left", padx=2)
        ttk.Button(r, text="Clear",           command=self._clear_brolls).pack(side="left", padx=2)

        # B-roll listbox
        lf = ttk.Frame(outer); lf.pack(fill="both", expand=True, padx=8, pady=4)
        self.lst = tk.Listbox(lf, selectmode="extended", height=8, activestyle="dotbox")
        self.lst.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(lf, orient="vertical", command=self.lst.yview)
        sb.pack(side="left", fill="y")
        self.lst.config(yscrollcommand=sb.set)

        # Output folder row
        r = ttk.Frame(outer); r.pack(fill="x", **pad)
        ttk.Label(r, text="Output:", width=12).pack(side="left")
        self.var_out = tk.StringVar()
        ttk.Entry(r, textvariable=self.var_out).pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(r, text="Browse", command=self._pick_out).pack(side="left")
        ttk.Button(r, text="Open",   command=self._open_out).pack(side="left", padx=(4, 0))

        # Workflow row
        self._wf_frame = ttk.Frame(outer)
        self._wf_frame.pack(fill="x", **pad)
        ttk.Label(self._wf_frame, text="Workflow:", width=12).pack(side="left")
        self.var_workflow = tk.StringVar(value="overlay")
        ttk.Radiobutton(
            self._wf_frame, text="Overlay",
            variable=self.var_workflow, value="overlay",
            command=self._on_workflow_change,
        ).pack(side="left", padx=(4, 8))
        ttk.Radiobutton(
            self._wf_frame, text="Sequential",
            variable=self.var_workflow, value="sequential",
            command=self._on_workflow_change,
        ).pack(side="left", padx=4)

        # Normalize checkbox — visible only in Sequential mode
        self._normalize_frame = ttk.Frame(outer)
        self.var_normalize = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            self._normalize_frame,
            text="Normalize hook audio to VSL level",
            variable=self.var_normalize,
        ).pack(side="left", padx=24)
        # Not packed here — _on_workflow_change controls visibility

        # Options row (CRF, Non-9:16, Fade, Skip existing)
        self._opts_frame = ttk.Frame(outer)
        self._opts_frame.pack(fill="x", **pad)
        ttk.Label(self._opts_frame, text="CRF:").pack(side="left")
        self.var_crf = tk.IntVar(value=23)
        ttk.Spinbox(self._opts_frame, from_=18, to=30, width=4, textvariable=self.var_crf).pack(side="left", padx=4)

        ttk.Label(self._opts_frame, text="Non-9:16:").pack(side="left", padx=(16, 0))
        self.var_mode = tk.StringVar(value="blur")
        ttk.Combobox(self._opts_frame, textvariable=self.var_mode, state="readonly", width=8,
                     values=["blur", "crop", "pad"]).pack(side="left", padx=4)

        ttk.Label(self._opts_frame, text="Fade(s):").pack(side="left", padx=(16, 0))
        self.var_fade = tk.DoubleVar(value=0.3)
        ttk.Spinbox(self._opts_frame, from_=0.0, to=1.0, increment=0.1, width=5,
                    textvariable=self.var_fade, format="%.1f").pack(side="left", padx=4)

        self.var_skip = tk.BooleanVar(value=True)
        ttk.Checkbutton(self._opts_frame, text="Skip existing",
                        variable=self.var_skip).pack(side="left", padx=(16, 0))

        self.var_nvenc = tk.BooleanVar(value=False)
        self.chk_nvenc = ttk.Checkbutton(
            self._opts_frame, text="GPU (NVENC)",
            variable=self.var_nvenc,
        )
        self.chk_nvenc.pack(side="left", padx=(16, 0))

        # Render mode toggle: Local / Cloud
        self._render_mode_frame = ttk.Frame(outer)
        self._render_mode_frame.pack(fill="x", **pad)
        ttk.Label(self._render_mode_frame, text="Render:", width=12).pack(side="left")
        self.var_render_mode = tk.StringVar(value="local")
        ttk.Radiobutton(
            self._render_mode_frame, text="Local",
            variable=self.var_render_mode, value="local",
            command=self._on_render_mode_change,
        ).pack(side="left", padx=(4, 8))
        ttk.Radiobutton(
            self._render_mode_frame, text="Cloud (RunPod)",
            variable=self.var_render_mode, value="cloud",
            command=self._on_render_mode_change,
        ).pack(side="left", padx=4)

        # Cloud config panel (hidden by default)
        self._cloud_frame = ttk.LabelFrame(outer, text="Cloud Settings")
        # Row 1: API key + Endpoint ID
        cr1 = ttk.Frame(self._cloud_frame)
        cr1.pack(fill="x", padx=8, pady=3)
        ttk.Label(cr1, text="API Key:").pack(side="left")
        self.var_rp_key = tk.StringVar()
        ttk.Entry(cr1, textvariable=self.var_rp_key, show="*", width=30).pack(
            side="left", padx=4, fill="x", expand=True)
        ttk.Label(cr1, text="Endpoint ID:").pack(side="left", padx=(8, 0))
        self.var_rp_endpoint = tk.StringVar()
        ttk.Entry(cr1, textvariable=self.var_rp_endpoint, width=22).pack(
            side="left", padx=4)
        # Row 2: Workers + Dropbox
        cr2 = ttk.Frame(self._cloud_frame)
        cr2.pack(fill="x", padx=8, pady=(0, 5))
        ttk.Label(cr2, text="Workers:").pack(side="left")
        self.var_cloud_workers = tk.IntVar(value=5)
        ttk.Spinbox(cr2, from_=1, to=10, width=3,
                    textvariable=self.var_cloud_workers).pack(side="left", padx=4)
        ttk.Label(cr2, text="Dropbox token:").pack(side="left", padx=(8, 0))
        self.var_dbx_token = tk.StringVar()
        ttk.Entry(cr2, textvariable=self.var_dbx_token, show="*", width=20).pack(
            side="left", padx=4, fill="x", expand=True)
        ttk.Label(cr2, text="Path:").pack(side="left", padx=(4, 0))
        self.var_dbx_path = tk.StringVar(value="/VSL_Output")
        ttk.Entry(cr2, textvariable=self.var_dbx_path, width=16).pack(
            side="left", padx=4)
        ttk.Button(cr2, text="Get Token",
                   command=self._get_dropbox_token).pack(side="left", padx=(4, 0))
        # Row 3: MEGA direct pull
        cr3 = ttk.Frame(self._cloud_frame)
        cr3.pack(fill="x", padx=8, pady=(0, 5))
        self.var_mega_user = tk.StringVar()
        self.var_mega_pass = tk.StringVar()
        ttk.Label(cr3, text="MEGA:").pack(side="left")
        ttk.Entry(cr3, textvariable=self.var_mega_user, width=22).pack(
            side="left", padx=4)
        ttk.Label(cr3, text="Pass:").pack(side="left")
        ttk.Entry(cr3, textvariable=self.var_mega_pass, show="*", width=16).pack(
            side="left", padx=4, fill="x", expand=True)
        ttk.Button(cr3, text="Auto",
                   command=self._auto_mega_creds).pack(side="left", padx=(4, 0))
        # Cloud frame hidden initially
        # _on_render_mode_change controls visibility

        # Progress: current file
        r = ttk.Frame(outer); r.pack(fill="x", **pad)
        ttk.Label(r, text="Current:", width=12).pack(side="left")
        self.pb_current = ttk.Progressbar(r, mode="determinate", maximum=1.0)
        self.pb_current.pack(side="left", fill="x", expand=True, padx=4)
        self.lbl_current = ttk.Label(r, text="—", width=30, anchor="w")
        self.lbl_current.pack(side="left")

        # Progress: overall
        r = ttk.Frame(outer); r.pack(fill="x", **pad)
        ttk.Label(r, text="Overall:", width=12).pack(side="left")
        self.pb_overall = ttk.Progressbar(r, mode="determinate", maximum=1.0)
        self.pb_overall.pack(side="left", fill="x", expand=True, padx=4)
        self.lbl_overall = ttk.Label(r, text="0/0", width=30, anchor="w")
        self.lbl_overall.pack(side="left")

        # Action buttons
        r = ttk.Frame(outer); r.pack(fill="x", **pad)
        self.btn_start  = ttk.Button(r, text="Start",  command=self._start)
        self.btn_start.pack(side="left", padx=2)
        self.btn_cancel = ttk.Button(r, text="Cancel", command=self._cancel, state="disabled")
        self.btn_cancel.pack(side="left", padx=2)

        # Log
        ttk.Label(outer, text="Log:").pack(anchor="w", padx=8)
        self.txt_log = tk.Text(outer, height=9, wrap="word", state="disabled")
        self.txt_log.pack(fill="both", expand=False, padx=8, pady=(0, 8))

        # Apply default visibility (overlay → normalize hidden, local → cloud hidden)
        self._apply_workflow_visibility()
        self._apply_render_mode_visibility()

    # ---------------------------------------------------------- Settings
    def _restore_settings(self) -> None:
        self.var_ffmpeg.set(self.cfg.get("ffmpeg_path") or (find_ffmpeg() or ""))
        self.var_vsl.set(self.cfg.get("vsl_path", ""))
        self.var_out.set(self.cfg.get("output_dir", ""))
        self.var_crf.set(self.cfg.get("crf", 23))
        self.var_mode.set(self.cfg.get("non_916_mode", "blur"))
        self.var_fade.set(float(self.cfg.get("fade_duration", 0.3)))
        self.var_skip.set(self.cfg.get("skip_existing", True))
        self.var_workflow.set(self.cfg.get("workflow", "overlay"))
        self.var_normalize.set(self.cfg.get("normalize_audio", True))
        self.var_nvenc.set(self.cfg.get("use_nvenc", False))
        self.var_render_mode.set(self.cfg.get("render_mode", "local"))
        self.var_rp_key.set(self.cfg.get("runpod_api_key", ""))
        self.var_rp_endpoint.set(self.cfg.get("runpod_endpoint_id", ""))
        self.var_cloud_workers.set(self.cfg.get("cloud_max_workers", 5))
        self.var_dbx_token.set(self.cfg.get("dropbox_token", ""))
        self.var_dbx_path.set(self.cfg.get("dropbox_path", "/VSL_Output"))
        self.var_mega_user.set(self.cfg.get("mega_user", ""))
        self.var_mega_pass.set(self.cfg.get("mega_pass", ""))
        # Re-apply visibility now that vars are restored from settings
        self._apply_workflow_visibility()
        self._apply_render_mode_visibility()
        # Auto-detect NVENC support in background
        self._detect_nvenc_async()

    def _persist_settings(self) -> None:
        self.cfg.update({
            "ffmpeg_path":     self.var_ffmpeg.get(),
            "vsl_path":        self.var_vsl.get(),
            "output_dir":      self.var_out.get(),
            "crf":             int(self.var_crf.get()),
            "non_916_mode":    self.var_mode.get(),
            "fade_duration":   round(float(self.var_fade.get()), 2),
            "skip_existing":   bool(self.var_skip.get()),
            "workflow":        self.var_workflow.get(),
            "normalize_audio": bool(self.var_normalize.get()),
            "use_nvenc":       bool(self.var_nvenc.get()),
            "render_mode":     self.var_render_mode.get(),
            "runpod_api_key":  self.var_rp_key.get(),
            "runpod_endpoint_id": self.var_rp_endpoint.get(),
            "cloud_max_workers": int(self.var_cloud_workers.get()),
            "dropbox_token":   self.var_dbx_token.get(),
            "dropbox_path":    self.var_dbx_path.get(),
            "mega_user":       self.var_mega_user.get(),
            "mega_pass":       self.var_mega_pass.get(),
        })
        cfg_store.save(self.cfg)

    # --------------------------------------------------- Workflow toggle
    def _apply_workflow_visibility(self) -> None:
        """Show or hide the normalize checkbox based on selected workflow."""
        if self.var_workflow.get() == "sequential":
            self._normalize_frame.pack(
                fill="x", padx=8, pady=2, after=self._wf_frame
            )
        else:
            self._normalize_frame.pack_forget()

    def _on_workflow_change(self) -> None:
        self._apply_workflow_visibility()
        self._persist_settings()

    # -------------------------------------------- Render mode toggle
    def _apply_render_mode_visibility(self) -> None:
        if self.var_render_mode.get() == "cloud":
            self._cloud_frame.pack(
                fill="x", padx=8, pady=4, after=self._render_mode_frame,
            )
        else:
            self._cloud_frame.pack_forget()

    def _on_render_mode_change(self) -> None:
        self._apply_render_mode_visibility()
        self._persist_settings()

    def _auto_mega_creds(self) -> None:
        """Auto-detect MEGA credentials from rclone config."""
        import threading

        def _do():
            try:
                r = subprocess.run(
                    ["rclone", "config", "dump"],
                    capture_output=True, text=True, timeout=5,
                )
                if r.returncode == 0:
                    import json
                    config = json.loads(r.stdout)
                    for name, cfg in config.items():
                        if cfg.get("type") == "mega":
                            user = cfg.get("user", "")
                            pw = cfg.get("pass", "")
                            self.root.after(0, lambda: self.var_mega_user.set(user))
                            self.root.after(0, lambda: self.var_mega_pass.set(pw))
                            self.root.after(0, lambda: self._log(
                                f"MEGA auto-detected: {user}"))
                            return
                    self.root.after(0, lambda: self._log("No MEGA remote in rclone config"))
            except Exception as e:
                self.root.after(0, lambda: self._log(f"rclone error: {e}"))

        threading.Thread(target=_do, daemon=True).start()

    def _get_dropbox_token(self) -> None:
        """Run rclone authorize dropbox to get a token."""
        self._log("Running: rclone authorize dropbox")
        self._log("A browser window will open. Authorize, then copy the token.")
        import threading

        def _do():
            try:
                r = subprocess.run(
                    ["rclone", "authorize", "dropbox"],
                    capture_output=True, text=True, timeout=300,
                )
                output = r.stdout + r.stderr
                # rclone prints the token JSON between braces
                import re
                m = re.search(r'(\{"access_token".*\})', output, re.DOTALL)
                if m:
                    token = m.group(1).strip()
                    self.root.after(0, lambda: self.var_dbx_token.set(token))
                    self.root.after(0, lambda: self._log("Dropbox token saved"))
                else:
                    self.root.after(0, lambda: self._log(
                        "Could not extract token. Copy manually from rclone output."))
            except FileNotFoundError:
                self.root.after(0, lambda: self._log(
                    "rclone not found. Install: winget install Rclone.Rclone"))
            except Exception as e:
                self.root.after(0, lambda: self._log(f"Error: {e}"))

        threading.Thread(target=_do, daemon=True).start()

    # ------------------------------------------------- NVENC detection
    def _detect_nvenc_async(self) -> None:
        """Check h264_nvenc support in a thread so the GUI stays responsive."""
        import threading

        def _check():
            ffmpeg = self.var_ffmpeg.get().strip()
            available = detect_nvenc(ffmpeg)
            self.root.after(0, lambda: self._on_nvenc_detected(available))

        threading.Thread(target=_check, daemon=True).start()

    def _on_nvenc_detected(self, available: bool) -> None:
        if available:
            self.chk_nvenc.config(state="normal")
            self._log("NVENC detected — GPU encoding available")
        else:
            self.chk_nvenc.config(state="disabled")
            self.var_nvenc.set(False)

    # ---------------------------------------------------------- Pickers
    def _pick_ffmpeg(self) -> None:
        p = filedialog.askopenfilename(
            title="Chọn ffmpeg.exe",
            filetypes=[("ffmpeg", "ffmpeg*"), ("All files", "*.*")],
        )
        if p:
            self.var_ffmpeg.set(p)

    def _auto_ffmpeg(self) -> None:
        p = find_ffmpeg()
        if p:
            self.var_ffmpeg.set(p)
            self._log(f"Found ffmpeg: {p}")
            self._detect_nvenc_async()
        else:
            messagebox.showwarning(APP_TITLE, "Không tìm thấy ffmpeg trong PATH.")

    def _pick_vsl(self) -> None:
        p = filedialog.askopenfilename(title="Chọn VSL chính", filetypes=VIDEO_FILETYPES)
        if p:
            self.var_vsl.set(p)

    def _add_files(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Chọn B-roll(s)",
            initialdir=self.cfg.get("last_broll_dir") or "",
            filetypes=VIDEO_FILETYPES,
        )
        for p in paths:
            self._add_broll(Path(p))
        if paths:
            self.cfg["last_broll_dir"] = str(Path(paths[0]).parent)

    def _add_folder(self) -> None:
        d = filedialog.askdirectory(title="Chọn thư mục chứa B-roll")
        if not d:
            return
        vsl_path = self.var_vsl.get()
        exts = {".mp4", ".mov", ".mkv", ".m4v"}
        for f in sorted(Path(d).iterdir()):
            if f.suffix.lower() in exts and str(f) != vsl_path:
                self._add_broll(f)
        self.cfg["last_broll_dir"] = d

    def _add_broll(self, p: Path) -> None:
        if p in self.brolls:
            return
        self.brolls.append(p)
        self.lst.insert("end", p.name)

    def _remove_selected(self) -> None:
        for i in reversed(self.lst.curselection()):
            del self.brolls[i]
            self.lst.delete(i)

    def _clear_brolls(self) -> None:
        self.brolls.clear()
        self.lst.delete(0, "end")

    def _pick_out(self) -> None:
        d = filedialog.askdirectory(title="Chọn thư mục output")
        if d:
            self.var_out.set(d)

    def _open_out(self) -> None:
        d = self.var_out.get()
        if not d or not Path(d).exists():
            messagebox.showinfo(APP_TITLE, "Output folder chưa tồn tại.")
            return
        if sys.platform == "win32":
            os.startfile(d)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.run(["open", d], check=False)
        else:
            subprocess.run(["xdg-open", d], check=False)

    # ------------------------------------------------------- Start/Cancel
    def _start(self) -> None:
        vsl = self.var_vsl.get().strip()

        if not vsl or not Path(vsl).is_file():
            messagebox.showerror(APP_TITLE, "Chưa chọn VSL chính."); return
        if not self.brolls:
            messagebox.showerror(APP_TITLE, "Chưa thêm B-roll."); return

        self._persist_settings()

        if self.var_render_mode.get() == "cloud":
            self._start_cloud(vsl)
        else:
            self._start_local(vsl)

    def _start_local(self, vsl: str) -> None:
        ffmpeg = self.var_ffmpeg.get().strip()
        outd = self.var_out.get().strip()

        if not ffmpeg or not Path(ffmpeg).is_file():
            messagebox.showerror(APP_TITLE, "FFmpeg không hợp lệ. Bấm Auto hoặc Browse."); return
        if not outd:
            messagebox.showerror(APP_TITLE, "Chưa chọn thư mục output."); return

        ffprobe = find_ffprobe(ffmpeg)
        if not ffprobe:
            messagebox.showerror(APP_TITLE, "Không tìm thấy ffprobe (cần ở cạnh ffmpeg)."); return

        job = JobConfig(
            ffmpeg=ffmpeg,
            ffprobe=ffprobe,
            vsl=Path(vsl),
            output_dir=Path(outd),
            brolls=list(self.brolls),
            crf=int(self.var_crf.get()),
            non_916_mode=self.var_mode.get(),
            skip_existing=bool(self.var_skip.get()),
            fade_duration=round(float(self.var_fade.get()), 2),
            workflow=self.var_workflow.get(),
            normalize_audio=bool(self.var_normalize.get()),
            use_nvenc=bool(self.var_nvenc.get()),
        )

        self._run_total = len(self.brolls)
        self.btn_start.config(state="disabled")
        self.btn_cancel.config(state="normal")
        self.pb_overall["value"] = 0
        self.pb_current["value"] = 0
        self._log(f"=== Start batch ({self._run_total} files) "
                  f"[{job.workflow}] [local] ===")

        self.worker = BatchWorker(job, self.events)
        self.worker.start()

    def _start_cloud(self, vsl: str) -> None:
        api_key = self.var_rp_key.get().strip()
        endpoint_id = self.var_rp_endpoint.get().strip()

        if not api_key:
            messagebox.showerror(APP_TITLE, "Chưa nhập RunPod API Key."); return
        if not endpoint_id:
            messagebox.showerror(APP_TITLE, "Chưa nhập Endpoint ID."); return

        job = CloudJobConfig(
            runpod_api_key=api_key,
            endpoint_id=endpoint_id,
            vsl=Path(vsl),
            brolls=list(self.brolls),
            crf=int(self.var_crf.get()),
            workflow=self.var_workflow.get(),
            non_916_mode=self.var_mode.get(),
            fade_duration=round(float(self.var_fade.get()), 2),
            normalize_audio=bool(self.var_normalize.get()),
            max_workers=int(self.var_cloud_workers.get()),
            dropbox_token=self.var_dbx_token.get().strip(),
            dropbox_path=self.var_dbx_path.get().strip() or "/VSL_Output",
            mega_user=self.var_mega_user.get().strip(),
            mega_pass=self.var_mega_pass.get().strip(),
        )

        self._run_total = len(self.brolls)
        self.btn_start.config(state="disabled")
        self.btn_cancel.config(state="normal")
        self.pb_overall["value"] = 0
        self.pb_current["value"] = 0
        workers = job.max_workers
        self._log(f"=== Start batch ({self._run_total} files) "
                  f"[{job.workflow}] [cloud x{workers}] ===")

        self.worker = CloudBatchWorker(job, self.events)
        self.worker.start()

    def _cancel(self) -> None:
        if self.worker:
            self.worker.cancel()
            self._log("Cancel requested...")

    # ----------------------------------------------------------- Events
    def _poll_events(self) -> None:
        try:
            while True:
                self._handle_event(self.events.get_nowait())
        except Empty:
            pass
        self.root.after(POLL_MS, self._poll_events)

    def _handle_event(self, ev: dict) -> None:
        kind = ev["kind"]
        if kind == "file_start":
            self.lbl_current.config(text=f"{ev['idx']}/{ev['total']}: {ev['name']}")
            self.lbl_overall.config(text=f"{ev['idx'] - 1}/{ev['total']}")
            self.pb_overall["value"] = (ev["idx"] - 1) / ev["total"]
            self.pb_current["value"] = 0
            self._log(f"[{ev['idx']}/{ev['total']}] Start: {ev['name']}")
        elif kind == "progress":
            self.pb_current["value"] = ev["value"]
        elif kind == "file_done":
            self.pb_current["value"] = 1.0
            self._log(f"  OK  ({ev['size_mb']:.1f} MB)  {ev['path']}")
        elif kind == "file_skip":
            self.pb_current["value"] = 1.0
            self._log(f"  SKIP (exists)  {ev['path']}")
        elif kind == "file_error":
            self._log(f"  FAILED: {ev['name']} — {ev['error']}")
        elif kind == "log":
            self._log(ev["msg"])
        elif kind == "cancelled":
            self._log("=== Cancelled ===")
            self._finish_run()
        elif kind == "all_done":
            self.pb_overall["value"] = 1.0
            self.lbl_overall.config(text=f"{self._run_total}/{self._run_total}")
            self._log("=== Done ===")
            self._finish_run()
        elif kind == "fatal":
            self._log(f"FATAL: {ev['error']}")
            messagebox.showerror(APP_TITLE, ev["error"])
            self._finish_run()

    def _finish_run(self) -> None:
        self.btn_start.config(state="normal")
        self.btn_cancel.config(state="disabled")
        self.worker = None

    # ------------------------------------------------------------- Misc
    def _log(self, msg: str) -> None:
        self.txt_log.config(state="normal")
        self.txt_log.insert("end", msg + "\n")
        self.txt_log.see("end")
        self.txt_log.config(state="disabled")

    def _on_close(self) -> None:
        if self.worker and self.worker.is_alive():
            if not messagebox.askyesno(APP_TITLE, "Đang encode. Thoát thật sao?"):
                return
            self.worker.cancel()
        self._persist_settings()
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    try:
        root.tk.call("tk", "scaling", 1.2)
    except tk.TclError:
        pass
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
