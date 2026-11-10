# Nilou — notes for Claude

Portable Windows download manager: Python 3.12 + Tkinter, shipped as one PyInstaller exe (`dist\Nilou.exe`;
the current build is committed at the repo root as `Nilou.exe` — refresh it when releasing).
Session history and the reasoning behind decisions: `docs/HISTORY.md`. Build/test/release workflow: the
`nilou-dev` skill in `.claude/skills/nilou-dev/SKILL.md`.

## Commands

- Tests: `.venv\Scripts\python -m unittest discover tests` (17 tests; engine tests spin up a local HTTP server)
- Lint: `.venv\Scripts\python -m pyflakes nilou tests tools`
- Icon + checkbox images: `.venv\Scripts\python tools\make_icon.py` (needs Pillow; output is committed)
- Exe: `powershell -ExecutionPolicy Bypass -File build.ps1` → `dist\Nilou.exe`
- Run from source: `pythonw Nilou.pyw` (data goes to `.\Nilou Data`, gitignored)

## Layout

- `nilou/engine.py` — `Download`: probe → N byte-range segments → worker threads; finished workers split the
  largest active segment (`_claim`). State persisted as unfinished `[start, end, pos]` segments. Temp file is
  `<name>.nilou`, pre-sized and marked sparse (avoids NTFS zero-fill stalls).
- `nilou/media.py` — `MediaDownload` has the same surface as `Download` (status, size, downloaded, start/stop,
  to_dict) but runs `yt-dlp.exe`; progress comes from a `--progress-template` line prefixed `[nilou-p]`.
  `ToolInstaller` fetches yt-dlp, Deno and FFmpeg with Nilou's own engine into `Nilou Data\tools`.
- `nilou/manager.py` — queue/scheduler thread, JSON persistence, settings, WebP→PNG post-processing.
- `nilou/server.py` — localhost API (`/ping`, `/download`, `/media`, `/grab`, `/show`, `/add`). Rejects any
  `Origin` that is not a browser extension and any `Host` that is not localhost. Also gives single-instance:
  a second exe that cannot bind the port forwards its links and exits.
- `nilou/tray.py` — ctypes `Shell_NotifyIcon` on its own thread; talks to the UI only through `App.q`.
- `nilou/ui.py` — main window drawn on Canvases (list, sidebar, details). `dialogs.py` — all dialogs.
- `extension/` — MV3 extension; `shared.js` holds the page scanner (`nilouCollectMedia`) and API calls.

## Rules and gotchas

- Tk is single-threaded: other threads put events on `App.q` (polled every 120 ms) or use `dialogs.run_bg`.
- `tk.Canvas.lift()` is tag-raise; use `tk.Misc.lift(canvas)` to raise the widget.
- `socketserver.shutdown()` blocks forever if `serve_forever()` never ran — `LocalServer.stop` guards this.
- Read the POST body before answering 403/415, otherwise the client sees a TCP reset instead of the status.
- JSON files may carry a BOM if a user edits them in PowerShell 5 — load with `utf-8-sig`.
- Data dir is portable (`<exe dir>\Nilou Data`) and falls back to `%APPDATA%\Nilou` when not writable.
- Keep `nilou/` stdlib-only; Pillow is optional at runtime (thumbnails, WebP→PNG) and bundled in the exe.
- The icon palette is exactly 10 colors (`PALETTE` in `tools/make_icon.py`); gradients blend between them.
- Video downloads are not covered end-to-end by tests (they need the network and external binaries);
  `tests/test_media.py` covers the yt-dlp output parsing offline.
