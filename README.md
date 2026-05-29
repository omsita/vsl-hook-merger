# VSL Hook Merger

Tool GUI Python ghép B-roll hook với VSL chính, batch nhiều file, output chuẩn FB Reels / TikTok (1080×1920, H.264, AAC, +faststart).

Hỗ trợ **hai workflow**:

| | Overlay | Sequential |
|---|---|---|
| Hook placement | Chồng lên đầu VSL | Phát trước VSL |
| VSL audio | Liên tục từ giây 0 | Bắt đầu sau hook |
| Hook audio | Câm | Full (tùy chọn loudnorm) |
| Tổng thời lượng | = VSL | ≈ hook + VSL − 0.3 s |
| Tên output | `{stem}_hook_VSL.mp4` | `{stem}_seq_VSL.mp4` |
| Phù hợp | Teaser ngắn ≤ 6 s | Hook full reveal 4–10 s |

---

## Cài đặt lần đầu (máy mới)

**Double-click `setup.bat`** — script tự:

1. Kiểm tra Python ≥ 3.10 (tự cài bằng `winget install Python.Python.3.12` nếu thiếu)
2. Kiểm tra tkinter (cảnh báo nếu dùng Microsoft Store Python)
3. Kiểm tra FFmpeg (tự cài `Gyan.FFmpeg` qua winget nếu thiếu)
4. Kiểm tra ffprobe
5. Smoke test tkinter mở được window

Sau khi winget cài xong, đóng cửa sổ và mở lại `setup.bat` để PATH cập nhật.

Nếu không có winget (Windows < 1809):
- Python: <https://www.python.org/downloads/> (tick "Add python.exe to PATH")
- FFmpeg: <https://www.gyan.dev/ffmpeg/builds/> → `release-full` → giải nén → thêm `bin\` vào PATH

---

## Chạy tool

**Double-click `run.bat`** hoặc:

```
python vsl_hook_merger.py
```

---

## Workflow — Overlay

1. **FFmpeg**: bấm **Auto** hoặc **Browse** chọn `ffmpeg.exe`.
2. **VSL chính**: chọn file VSL gốc 9:16.
3. **B-rolls**: Add Files / Add Folder.
4. **Output**: chọn thư mục output.
5. **Workflow**: chọn **Overlay**.
6. Tùy chỉnh CRF, Non-9:16, Fade, Skip existing.
7. Bấm **Start**.

Output: `{tên_broll}_hook_VSL.mp4` — B-roll che full frame đầu video, VSL audio chạy xuyên suốt.

## Workflow — Sequential

Giống Overlay nhưng:

1. **Workflow**: chọn **Sequential**.
2. Tùy chọn **Normalize hook audio to VSL level** (mặc định ON):
   - ON: tool đo LUFS của VSL trước khi encode (~10–30 s cho VSL dài), rồi áp `loudnorm` lên hook để transition âm thanh mượt.
   - OFF: hook audio giữ nguyên level gốc.
3. Bấm **Start**.

Output: `{tên_broll}_seq_VSL.mp4` — hook phát full trước, fade xfade 0.3 s vào VSL.

> **Lưu ý:** Fade(s) trong Sequential là thời gian cross-fade xfade/acrossfade (cả hình + tiếng). Trong Overlay, Fade(s) là thời gian fade-out alpha của hook.

---

## Tùy chỉnh options

| Option | Mô tả | Mặc định |
|---|---|---|
| CRF 18–30 | Chất lượng video (nhỏ = to file hơn) | 23 |
| Non-9:16 | Cách xử lý hook không vuông 9:16 | blur |
| Fade(s) 0.0–1.0 | Thời gian transition | 0.3 |
| Skip existing | Bỏ qua file đã encode | ✓ |
| Normalize (Sequential) | Đo LUFS VSL → loudnorm hook | ✓ |

**Non-9:16 modes:**
- `blur` — blur background + hook centered (đẹp nhất)
- `crop` — zoom fill 9:16 (mất rìa)
- `pad` — letterbox đen 2 bên (giữ nguyên nội dung)

---

## Cấu trúc code

```
vsl-hook-merger/
├── vsl_hook_merger.py        # GUI tkinter (entry point)
├── worker.py                 # Thread xử lý batch + JobConfig
├── ffmpeg_runner.py          # Subprocess wrappers (probe + encode)
├── filter_graph_builder.py   # Build filter_complex string (pure functions)
├── settings.py               # Persist JSON ~/.vsl-hook-merger.json
├── setup.bat                 # Cài lần đầu (winget)
├── run.bat                   # Launcher Windows
├── docs/                     # Tài liệu kỹ thuật
└── tests/                    # 36 unit/integration tests
```

---

## Specs encode (cố định)

| Tham số | Giá trị |
|---|---|
| Resolution | 1080×1920 |
| FPS | 30 |
| Video codec | libx264 high@4.1, preset medium |
| Pixel format | yuv420p |
| Audio | AAC 128k 44.1kHz stereo |
| Container | MP4 +faststart |

Muốn đổi → sửa trong `ffmpeg_runner.py` → `encode_with_progress`.

---

## Test

```
python -m pytest tests/ -v -p no:asyncio
```

36 tests — filter graph (20), audio probing (7), worker config (9).

---

## Tips

- File output ~340 MB / 23 phút (CRF 23). FB re-encode khi upload — đừng nén quá mạnh.
- Sequential mode thêm 4–10 s tổng thời lượng so với VSL gốc.
- Normalize OFF nếu hook đã mix âm thanh cân bằng hoặc dùng nhạc nền riêng.
- Cancel xóa file đang ghi để run lại không bị Skip existing hiểu nhầm.
- VSL dài > 90 s không upload Reels được trên một số tài khoản, nhưng vẫn đăng Feed / Reel dài tuỳ account.
