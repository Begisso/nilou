<p align="center"><img src="assets/nilou-256.png" width="128" alt="Nilou lotus icon"></p>

<h1 align="center">Nilou</h1>
<p align="center">A fast, portable download manager for Windows — one exe, lives in your tray.</p>

## What it does

- **Faster downloads** — splits each file across up to 32 connections and keeps every connection busy by
  stealing work from the slowest one.
- **Pause and resume anything** — progress survives pauses, crashes and reboots (when the server allows resuming).
- **Catches browser downloads** — the Nilou extension hands Chrome / Edge / Brave downloads to Nilou, with your
  cookies, so logged-in downloads work.
- **YouTube, X (Twitter) and 1000+ sites** — pick 4K/1080p/720p… or audio-only MP3/M4A. Uses yt-dlp under the hood.
- **Grab media from a page** — lists every image, video, audio file and document on a page; tick what you want.
- **WebP → PNG** — WebP images are saved as PNG automatically (animated WebP becomes animated PNG).
- **Lives in the tray** — closing or minimizing hides Nilou to the notification area; you get a notification when a
  download finishes.
- **Portable** — no installer. Settings and the download list sit in a `Nilou Data` folder next to `Nilou.exe`.
- Speed limit, simultaneous-download limit, sorting into folders by type, light/dark theme, clipboard watching.

## Get started

1. Download [`Nilou.exe`](Nilou.exe) from this repo (or build it yourself — see
   [Build from source](#build-from-source)), put it anywhere you like (a USB stick works too) and run it.
   The exe is not code-signed, so Windows SmartScreen may warn on first launch (*More info → Run anyway*).
2. Paste a link with **Ctrl+V** or click **Add URL**.
3. Optional: **Connect browser** (bottom-right of the window) walks you through loading the extension:
   open `edge://extensions` or `chrome://extensions`, switch on *Developer mode*, click *Load unpacked*, and pick the
   folder Nilou shows you.

The first time you download a video, Nilou offers a one-time setup that fetches **yt-dlp**, **Deno** (YouTube
needs it) and **FFmpeg** (merges video + audio) into `Nilou Data\tools` — about 200 MB. *Settings → Update yt-dlp*
keeps it current when sites change.

| Shortcut | Action |
| --- | --- |
| Ctrl+V | Download the link on the clipboard (video links open the video downloader) |
| Ctrl+N | Add a download |
| Space | Pause / resume the selection |
| Enter | Open the finished file |
| Delete | Remove from the list |
| Ctrl+F | Search |

## Build from source

Requires Python 3.12+ on Windows.

```powershell
powershell -ExecutionPolicy Bypass -File build.ps1   # venv, icon, tests, then dist\Nilou.exe
```

Run without building: `pythonw Nilou.pyw` (Pillow is optional — without it WebP→PNG and video thumbnails are off).
Tests: `python -m unittest discover tests`.

## How it works

| Part | File |
| --- | --- |
| Multi-connection engine (segments, work stealing, resume, sparse files) | `nilou/engine.py` |
| Queue, persistence, settings, WebP→PNG | `nilou/manager.py` |
| yt-dlp jobs and one-time tool installer | `nilou/media.py` |
| Page media scanner | `nilou/grab.py` |
| Localhost API for the extension + single-instance handoff | `nilou/server.py` |
| Tray icon and notifications (pure ctypes) | `nilou/tray.py` |
| Window, dialogs, theme | `nilou/ui.py`, `nilou/dialogs.py`, `nilou/theme.py` |
| Browser extension (Manifest V3) | `extension/` |
| Lotus icon renderer (10-color palette) | `tools/make_icon.py` |

The local API listens on `127.0.0.1:9614` and only accepts requests from local programs or browser extensions —
web pages are rejected, so a website cannot push downloads into Nilou.
