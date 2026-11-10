# Claude session history

How Nilou was built with Claude Code (Claude Opus 5.5), in one session on 2026-11-10. Requests are
paraphrased in order; each is followed by what was done and why.

## 1. "Make me a Download Manager, I don't want to download from browser again"

- Checked the machine: Python 3.12 with Tkinter, no Node, no .NET SDK, git + GitHub CLI signed in.
  Chose **Python + Tkinter, standard library only**, so the app needs nothing installed.
- Wrote a multi-connection HTTP engine (`nilou/engine.py`): byte-range segments, a worker per connection, and
  *work stealing* — a connection that finishes splits the largest remaining segment, so all connections stay
  busy to the end. Resume state is the list of unfinished segments.
- Pre-sized temp files are marked **sparse**: otherwise NTFS zero-fills the gap when a far segment writes first,
  which stalls large downloads.
- To replace the browser, a **Manifest V3 extension** captures downloads (`downloads.onCreated` → pause →
  hand to Nilou with cookies → cancel in the browser; if Nilou is not running the browser download simply
  resumes) and adds right-click actions.
- The localhost API only accepts browser-extension origins and local programs, so web pages cannot push
  downloads into Nilou.

## 2. "one exe, portable, can be minimized to tray"

- Packaged with **PyInstaller `--onefile --windowed`** → `dist\Nilou.exe` (~18 MB, Pillow included).
- Portable data: `Nilou Data` next to the exe (falls back to `%APPDATA%\Nilou` if that folder is read-only).
  The browser extension is bundled inside the exe and unpacked next to it on demand.
- Tray icon written with ctypes (`Shell_NotifyIconW`): close and minimize hide to the tray, right-click menu,
  toast notifications when downloads finish. Start-with-Windows launches with `--minimized`.
- The local API port doubles as a single-instance lock: launching the exe again forwards links and exits.

## 3. "Name it Nilou, remove background and simplify to 10 colors with gradient" (lotus image attached)

- The pasted image was not saved to disk and carried a stock-photo watermark, so it was **redrawn as an
  original vector lotus** (`tools/make_icon.py`) instead of traced: transparent background, exactly 10 colors
  (indigo, violet, royal, blue, sky, ice, white, orange, yellow, cyan), petals filled with gradients between
  them. Rendered with Pillow at 1024 px and downsampled to every icon size (16–512, `.ico`, extension icons).
- The app's accent colors and the extension's popup follow the lotus blues.

## 4. "and throw to git"

- Initialized a repository, committed, and pushed to a **public** GitHub repo (`Begisso/nilou`, after a follow-up
  "public git"); `Nilou.exe` is attached to the `v1.0.0` release rather than committed.
- No git identity was configured, so the repo-local author is `Begisso` with the GitHub no-reply address.

## 5. "Include grab media from page, youtube downloader and twitter downloader, download webp as png"

- **Grab media from page**: the extension scans the live page (all frames) for images (largest `srcset`),
  video/audio sources, posters, Open Graph media and linked files, then opens a picker in Nilou. Nilou can also
  scan a pasted page URL itself (`nilou/grab.py`, static HTML).
- **YouTube / X (Twitter)**: driven by **yt-dlp**. Since late 2025 yt-dlp needs a JavaScript runtime (Deno) for
  YouTube, and FFmpeg to merge separate video and audio streams. Nilou downloads all three on first use into
  `Nilou Data\tools` with its own engine, so the exe stays small and yt-dlp can self-update when sites change.
  Quality picker (best/4K/1440/1080/720/480/360, MP3, M4A), playlists, cookies from the browser for X.
- **WebP → PNG**: after a download finishes, files that are WebP by their magic bytes are converted with Pillow
  (animated WebP → animated PNG) and the WebP is removed. Can be turned off in Settings.

## 6. "claude history skill md"

Interpreted as three files for future Claude sessions:
- `docs/HISTORY.md` — this file.
- `CLAUDE.md` — project map, commands and gotchas.
- `.claude/skills/nilou-dev/SKILL.md` — a skill for building, testing and releasing Nilou.

## Verification done

- 17 unit tests: multi-connection integrity (SHA-256), pause → save → restore → resume, servers without range
  support, chunked/unknown size, Content-Disposition names, HTTP 404, speed limit, plain-English socket errors,
  WebP→PNG, yt-dlp output parsing, Netscape cookie files, media-site detection, page scanning, API origin checks,
  single-instance port lock.
- Screenshots in light and dark themes of the main window and dialogs; exe tested from a separate folder
  (portable data, single-instance handoff, close-to-tray, show from tray, clean exit).
- **Not verified**: a live YouTube/X download. Running the downloaded yt-dlp/Deno/FFmpeg binaries was blocked
  by the session's safety policy, so that path was covered only by offline tests.

## Bugs found and fixed during the session

- `Canvas.lift()` is Tk's tag-raise → used `tk.Misc.lift`.
- `socketserver.shutdown()` deadlocks when `serve_forever()` never started.
- A 403 sent before reading the POST body reached the client as a TCP reset.
- Settings written by PowerShell 5 have a UTF-8 BOM → JSON is read with `utf-8-sig`.
- Windows socket errors are localized (Russian on this machine) → mapped to short English messages.
