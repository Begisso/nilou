---
name: nilou-dev
description: Build, test, run, screenshot and release Nilou (the portable Windows download manager in this repo). Use when changing Nilou's code, rebuilding Nilou.exe, regenerating the lotus icon, checking the UI visually, or publishing a release.
---

# Working on Nilou

Read `CLAUDE.md` first for the architecture and gotchas, and `docs/HISTORY.md` for why things are the way they are.

## Set up once

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install pillow pyinstaller pyflakes
```

## Change → verify loop

1. Edit code under `nilou/` (stdlib only; Pillow is optional at runtime — guard imports).
2. Run the tests and the linter:
   ```powershell
   .\.venv\Scripts\python -m unittest discover tests
   .\.venv\Scripts\python -m pyflakes nilou tests tools
   ```
   Engine changes need a test in `tests/test_engine.py` (it has a local Range-capable HTTP server).
   yt-dlp changes: feed sample output lines to `MediaDownload.handle_line` in `tests/test_media.py`.
3. Look at the UI. Run `pythonw Nilou.pyw` (data goes to `.\Nilou Data`, gitignored), then screenshot the window by
   title with Pillow's `ImageGrab` after `SetProcessDpiAwareness(2)` and `DwmGetWindowAttribute(hwnd, 9, …)` for the
   frame rect. Check **both** themes (Settings → Theme). To open a dialog without clicking, POST to the local API:
   `/grab` (items list), `/media` (`{"url": …}`), `/download` with `"ask": true` for the add dialog.
4. Only stop processes you started (by PID) — never kill every `python`/`pythonw`.

## Icon

`tools/make_icon.py` draws the lotus with exactly the 10 colors in `PALETTE` and writes `assets/nilou.ico`,
`assets/nilou-*.png`, `assets/ui/check-*.png` and `extension/icons/*`. Keep the palette at 10 colors; gradients only
blend between palette colors. Commit the generated files.

## Build the exe

```powershell
powershell -ExecutionPolicy Bypass -File build.ps1
```

It renders the icon, runs the tests and produces `dist\Nilou.exe`. Smoke-test it from an empty folder: it must create
`Nilou Data\` beside itself, answer `GET http://127.0.0.1:9614/ping`, and a second launch with a URL must hand the URL
to the first instance and exit with code 0.

## Release

1. Bump `VERSION` in `nilou/__init__.py`, `tools/version_info.txt` and `extension/manifest.json` together.
2. Build, commit, tag `vX.Y.Z`, push.
3. `gh release create vX.Y.Z dist/Nilou.exe --title "Nilou X.Y.Z" --notes "<what changed>"` — the exe goes on the
   release, never into git.
