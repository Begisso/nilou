"""The download queue: scheduling, persistence, settings and post-processing."""
import json
import logging
import os
import queue
import threading
import time

from . import paths, winutil
from .engine import COMPLETED, DOWNLOADING, ERROR, PAUSED, QUEUED, TEMP_SUFFIX, Download, RateLimiter
from .media import MediaDownload
from .util import category_of, sanitize_filename, split_ext

log = logging.getLogger('nilou')

DEFAULT_SETTINGS = {
    'download_dir': '',
    'category_subfolders': False,
    'max_active': 3,
    'connections': 8,
    'speed_limit_kbps': 0,
    'theme': 'system',
    'close_to_tray': True,
    'minimize_to_tray': True,
    'notify_complete': True,
    'browser_show_dialog': True,
    'clipboard_monitor': False,
    'webp_to_png': True,
    'start_with_windows': False,
    'video_quality': '1080',
    'port': 9614,
    'geometry': '',
    'zoomed': False,
    'tray_hint_shown': False,
}


def _settings_path():
    return os.path.join(paths.data_dir(), 'settings.json')


def _list_path():
    return os.path.join(paths.data_dir(), 'downloads.json')


def _write_json(path, data):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def load_settings():
    settings = dict(DEFAULT_SETTINGS)
    try:
        with open(_settings_path(), encoding='utf-8-sig') as f:
            saved = json.load(f)
        settings.update({k: v for k, v in saved.items() if k in DEFAULT_SETTINGS})
    except (OSError, ValueError):
        pass
    if not settings['download_dir']:
        settings['download_dir'] = winutil.downloads_folder()
    return settings


def save_settings(settings):
    try:
        _write_json(_settings_path(), settings)
    except OSError:
        log.exception('could not save settings')


def is_webp(path):
    try:
        with open(path, 'rb') as f:
            head = f.read(12)
        return head[:4] == b'RIFF' and head[8:12] == b'WEBP'
    except OSError:
        return False


class DownloadManager:
    def __init__(self, settings):
        self.settings = settings
        self.downloads = []
        self.lock = threading.RLock()
        self.events = queue.Queue()
        self.limiter = RateLimiter(settings['speed_limit_kbps'] * 1024)
        self._wake = threading.Event()
        self._dirty = False
        self._running = True
        self._load()
        self._thread = threading.Thread(target=self._loop, name='nilou-scheduler', daemon=True)
        self._thread.start()

    # ----- persistence -------------------------------------------------------------
    def _load(self):
        try:
            with open(_list_path(), encoding='utf-8-sig') as f:
                items = json.load(f)
        except (OSError, ValueError):
            return
        for data in items:
            try:
                d = MediaDownload.from_dict(data) if data.get('kind') == 'media' else Download.from_dict(data)
            except (KeyError, TypeError, ValueError):
                continue
            self._wire(d)
            self.downloads.append(d)

    def save(self):
        with self.lock:
            items = [d.to_dict() for d in self.downloads]
            self._dirty = False
        try:
            _write_json(_list_path(), items)
        except OSError:
            log.exception('could not save the download list')

    def save_settings(self):
        save_settings(self.settings)

    # ----- wiring ---------------------------------------------------------------------
    def _wire(self, d):
        d.limiter = self.limiter
        d.on_finish = self._on_finish
        d.resolve_name = self._resolve_name
        d.postprocess = self._postprocess

    def _on_finish(self, d):
        if d.status == COMPLETED and d.kind == 'http':
            d.headers.pop('Cookie', None)
        self._dirty = True
        self.events.put(('finished', d))
        self._wake.set()

    def _unique_name(self, folder, name, exclude=None):
        taken = {os.path.normcase(os.path.join(o.folder, o.filename))
                 for o in self.downloads if o is not exclude and o.filename and o.status != COMPLETED}
        stem, ext = split_ext(name)
        i = 0
        while True:
            candidate = name if i == 0 else f'{stem} ({i}){ext}'
            full = os.path.join(folder, candidate)
            if (not os.path.exists(full) and not os.path.exists(full + TEMP_SUFFIX)
                    and os.path.normcase(full) not in taken):
                return candidate
            i += 1

    def _resolve_name(self, d, suggested):
        with self.lock:
            name = sanitize_filename(suggested)
            if d.auto_folder and self.settings['category_subfolders']:
                d.folder = os.path.join(self.settings['download_dir'], category_of(name))
            d.filename = self._unique_name(d.folder, name, d)
            self._dirty = True

    def _postprocess(self, d):
        """Runs on the worker thread right after a file is saved."""
        if d.kind != 'http' or not self.settings.get('webp_to_png', True) or not is_webp(d.path):
            return
        try:
            from PIL import Image
        except ImportError:
            return
        d.message = 'Converting to PNG…'
        src = d.path
        with self.lock:
            stem = os.path.splitext(d.filename)[0]
            new_name = self._unique_name(d.folder, stem + '.png', d)
        dest = os.path.join(d.folder, new_name)
        with Image.open(src) as im:
            if getattr(im, 'is_animated', False) and getattr(im, 'n_frames', 1) > 1:
                im.save(dest, 'PNG', save_all=True)
            else:
                if im.mode not in ('RGB', 'RGBA', 'L', 'LA', 'P'):
                    im = im.convert('RGBA')
                im.save(dest, 'PNG')
        os.remove(src)
        d.filename = new_name
        d.size = d.downloaded = os.path.getsize(dest)

    # ----- public actions ------------------------------------------------------------
    def default_folder(self):
        return self.settings['download_dir']

    def add(self, url, filename=None, folder=None, headers=None, start=True, size=-1):
        auto = not folder or os.path.normcase(os.path.abspath(folder)) == os.path.normcase(
            os.path.abspath(self.settings['download_dir']))
        d = Download(url, folder or self.settings['download_dir'], headers=headers,
                     connections=self.settings['connections'])
        d.auto_folder = auto
        if size and size > 0:
            d.size = size
        self._wire(d)
        with self.lock:
            if filename:
                self._resolve_name(d, filename)
            d.status = QUEUED if start else PAUSED
            self.downloads.append(d)
            self._dirty = True
        self._wake.set()
        return d

    def add_media(self, url, quality, folder=None, title='', video_id='', cookies=None, headers=None, start=True):
        d = MediaDownload(url, folder or self.settings['download_dir'], quality, title, video_id, cookies, headers)
        self._wire(d)
        with self.lock:
            d.status = QUEUED if start else PAUSED
            self.downloads.append(d)
            self._dirty = True
        self._wake.set()
        return d

    def get(self, download_id):
        with self.lock:
            return next((d for d in self.downloads if d.id == download_id), None)

    def resume(self, items):
        with self.lock:
            for d in items:
                if d.status in (PAUSED, ERROR):
                    d.status = QUEUED
                    d.error = ''
            self._dirty = True
        self._wake.set()

    def pause(self, items):
        with self.lock:
            for d in items:
                if d.status in (DOWNLOADING, QUEUED):
                    d.stop(PAUSED)
            self._dirty = True
        self._wake.set()

    def restart(self, items):
        with self.lock:
            for d in items:
                d.reset()
                if d.status == COMPLETED:
                    d.finished_at = None
                d.status = QUEUED
            self._dirty = True
        self._wake.set()

    def remove(self, items, delete_files=False):
        with self.lock:
            for d in items:
                if d not in self.downloads:
                    continue
                d.stop(PAUSED)
                self.downloads.remove(d)
                if d.kind == 'media':
                    d.delete_partials()
                elif d.temp_path:
                    try:
                        os.remove(d.temp_path)
                    except OSError:
                        pass
                if delete_files and d.status == COMPLETED and d.path:
                    try:
                        os.remove(d.path)
                    except OSError:
                        pass
            self._dirty = True
        self._wake.set()

    def pause_all(self):
        self.pause([d for d in self.downloads if d.status in (DOWNLOADING, QUEUED)])

    def resume_all(self):
        self.resume([d for d in self.downloads if d.status in (PAUSED, ERROR)])

    def clear_completed(self):
        with self.lock:
            self.downloads = [d for d in self.downloads if d.status != COMPLETED]
            self._dirty = True

    def set_speed_limit(self, kbps):
        self.settings['speed_limit_kbps'] = max(0, int(kbps))
        self.limiter.set_rate(self.settings['speed_limit_kbps'] * 1024)
        self.save_settings()

    def stats(self):
        with self.lock:
            items = list(self.downloads)
        active = [d for d in items if d.status == DOWNLOADING]
        return {
            'speed': sum(d.speed for d in active),
            'active': len(active),
            'queued': sum(1 for d in items if d.status == QUEUED),
            'total': len(items),
        }

    # ----- background loop ------------------------------------------------------------
    def _loop(self):
        last_save = time.monotonic()
        while self._running:
            self._wake.wait(0.5)
            self._wake.clear()
            if not self._running:
                break
            try:
                self._schedule()
                self._sample_speeds()
                now = time.monotonic()
                busy = any(d.status == DOWNLOADING for d in self.downloads)
                if (self._dirty and now - last_save > 1.0) or (busy and now - last_save > 5.0):
                    self.save()
                    last_save = now
            except Exception:  # noqa: BLE001
                log.exception('scheduler error')

    def _schedule(self):
        with self.lock:
            slots = self.settings['max_active'] - sum(1 for d in self.downloads if d.status == DOWNLOADING)
            for d in self.downloads:
                if slots <= 0:
                    break
                if d.status == QUEUED:
                    d.start()
                    slots -= 1
                    self._dirty = True

    def _sample_speeds(self):
        now = time.monotonic()
        with self.lock:
            items = list(self.downloads)
        for d in items:
            if d.status != DOWNLOADING:
                d._samples.clear()
                if not d.reports_speed:
                    d.speed = 0.0
                continue
            if d.reports_speed:
                continue
            samples = d._samples
            samples.append((now, d.downloaded))
            while len(samples) > 2 and now - samples[0][0] > 3.0:
                samples.popleft()
            if len(samples) >= 2 and samples[-1][0] > samples[0][0]:
                d.speed = max(0.0, (samples[-1][1] - samples[0][1]) / (samples[-1][0] - samples[0][0]))
            if d.speed > 0 and d.size > 0:
                d.eta = (d.size - d.downloaded) / d.speed
            else:
                d.eta = None

    def shutdown(self):
        self._running = False
        self._wake.set()
        with self.lock:
            for d in self.downloads:
                if d.status == DOWNLOADING:
                    d.stop(QUEUED)     # picked up again automatically on next launch
        self.save()
        save_settings(self.settings)
