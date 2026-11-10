"""Entry point: single-instance handoff, logging, then the UI."""
import argparse
import logging
import logging.handlers
import os
import sys

from . import APP_NAME, paths, server, util, winutil


def _setup_logging():
    log_path = os.path.join(paths.data_dir(), 'nilou.log')
    handler = logging.handlers.RotatingFileHandler(log_path, maxBytes=512 * 1024, backupCount=1, encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(threadName)s: %(message)s'))
    root = logging.getLogger('nilou')
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    if sys.stderr is None or sys.stdout is None:      # windowed exe / pythonw: keep stray prints harmless
        stream = open(os.devnull, 'w', encoding='utf-8')
        sys.stdout = sys.stdout or stream
        sys.stderr = sys.stderr or stream


def _make_shortcuts():
    exe, args = paths.launch_command()
    icon = exe if paths.FROZEN else paths.resource_path('assets', 'nilou.ico')
    programs = os.path.join(os.environ.get('APPDATA', ''), r'Microsoft\Windows\Start Menu\Programs')
    desktop = os.path.join(os.path.expanduser('~'), 'Desktop')
    ok = True
    for folder in (programs, desktop):
        ok &= winutil.create_shortcut(os.path.join(folder, APP_NAME + '.lnk'), exe, args, paths.app_dir(), icon)
    return ok


def main(argv=None):
    parser = argparse.ArgumentParser(prog=APP_NAME)
    parser.add_argument('urls', nargs='*', help='links to download')
    parser.add_argument('--minimized', action='store_true', help='start in the tray')
    parser.add_argument('--shortcuts', action='store_true', help='create Start menu and desktop shortcuts and exit')
    args = parser.parse_args(argv)

    _setup_logging()
    log = logging.getLogger('nilou')

    if args.shortcuts:
        sys.exit(0 if _make_shortcuts() else 1)

    from .manager import load_settings
    settings = load_settings()
    port = settings['port']
    urls = [u for u in args.urls if u.lower().startswith(('http://', 'https://'))]

    api = server.LocalServer(port, handler=lambda action, data: (False, 'starting'))
    bound = api.bind()
    if not bound and server.ping(port):
        # Nilou is already running: hand over the links (or just show it) and quit.
        for url in urls:
            server.send(port, 'add', {'url': url})
        if not urls:
            server.send(port, 'show', {})
        return

    winutil.enable_dpi_awareness()
    winutil.set_app_id('Nilou.DownloadManager')
    from .manager import DownloadManager
    from .ui import App

    manager = DownloadManager(settings)
    try:
        app = App(manager, api if bound else None, server_ok=bound, start_hidden=args.minimized and not urls)
    except Exception:
        log.exception('could not start the window')
        manager.shutdown()
        api.stop()
        raise
    api.handler = app.api
    api.start()
    for url in urls:
        app.q.put(('media' if util.is_media_site(url) else 'download', {'url': url}))
    log.info('%s started (port %s, data %s)', APP_NAME, port if bound else 'none', paths.data_dir())
    try:
        app.run()
    except KeyboardInterrupt:
        app.quit()
