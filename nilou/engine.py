"""Nilou's multi-connection HTTP(S) download engine.

A download is split into byte-range segments that are fetched in parallel.
When a connection finishes its segment it steals half of the largest remaining
one, so every connection stays busy until the very end. Progress is persisted
as the list of unfinished segments, which makes downloads resumable across
pauses, crashes and restarts.
"""
import collections
import mimetypes
import os
import re
import socket
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from . import winutil
from .util import category_of, filename_from_url, parse_content_disposition, sanitize_filename

QUEUED, DOWNLOADING, PAUSED, COMPLETED, ERROR = 'queued', 'downloading', 'paused', 'completed', 'error'

CHUNK = 128 * 1024
MIN_PIECE = 512 * 1024          # never split a segment into pieces smaller than this
TIMEOUT = 30
MAX_RETRIES = 6
TEMP_SUFFIX = '.nilou'
DEFAULT_UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
              '(KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36')
_FATAL_HTTP = {400, 401, 403, 404, 405, 410, 416, 451}


class _Redirect(urllib.request.HTTPRedirectHandler):
    """Follow redirects, but never forward cookies/credentials to another host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None:
            if urllib.parse.urlsplit(req.full_url).hostname != urllib.parse.urlsplit(new.full_url).hostname:
                new.remove_header('Cookie')
                new.remove_header('Authorization')
        return new


_OPENER = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ssl.create_default_context()),
                                      _Redirect())


def make_request(url, headers=None):
    h = {'User-Agent': DEFAULT_UA, 'Accept': '*/*', 'Accept-Encoding': 'identity'}
    for key, value in (headers or {}).items():
        if value:
            h[key] = str(value).replace('\r', ' ').replace('\n', ' ')
    return urllib.request.Request(url, headers=h)


def open_url(url, headers=None, timeout=TIMEOUT):
    return _OPENER.open(make_request(url, headers), timeout=timeout)


def describe_error(exc):
    """A short English message (Windows' own socket errors are localized and long)."""
    if isinstance(exc, urllib.error.HTTPError):
        return f'HTTP {exc.code} {exc.reason}'.strip()
    if isinstance(exc, urllib.error.URLError):
        if not isinstance(exc.reason, BaseException):
            return str(exc.reason)
        exc = exc.reason
    if isinstance(exc, socket.gaierror):
        return 'Could not find the server (check the address and your internet connection)'
    if isinstance(exc, ssl.SSLCertVerificationError):
        return f'Security certificate problem: {exc.verify_message}'
    if isinstance(exc, ssl.SSLError):
        return 'Secure connection failed'
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return 'The connection timed out'
    if isinstance(exc, ConnectionRefusedError):
        return 'The server refused the connection'
    if isinstance(exc, (ConnectionResetError, ConnectionAbortedError)):
        return 'The server dropped the connection'
    if isinstance(exc, ConnectionError):
        return str(exc) or 'The connection was lost'
    if isinstance(exc, PermissionError):
        return f'Permission denied: {exc.filename}' if exc.filename else 'Permission denied'
    if isinstance(exc, OSError):
        if exc.errno == 28 or getattr(exc, 'winerror', None) == 112:
            return 'Not enough disk space'
        if exc.filename:
            return f'{exc.strerror}: {exc.filename}'
        return exc.strerror or str(exc)
    return str(exc) or exc.__class__.__name__


def _name_with_ext(name, content_type):
    name = sanitize_filename(name or '')
    generic = ('application/octet-stream', 'binary/octet-stream', 'application/force-download', 'application/download')
    if '.' not in name.strip('.') and content_type and content_type not in generic:
        ext = mimetypes.guess_extension(content_type, strict=False)
        if ext:
            name += ext
    return name


class ProbeInfo:
    def __init__(self):
        self.url = ''
        self.final_url = ''
        self.size = -1
        self.resumable = False
        self.filename = ''
        self.content_type = ''
        self.response = None   # an open 200 response we can stream from directly

    def close(self):
        if self.response is not None:
            try:
                self.response.close()
            except Exception:
                pass
            self.response = None


def probe(url, headers=None, timeout=TIMEOUT):
    """Ask the server about a file: size, name and whether byte ranges work."""
    ranged = dict(headers or {})
    ranged['Range'] = 'bytes=0-0'
    try:
        resp = open_url(url, ranged, timeout)
    except urllib.error.HTTPError as e:
        e.close()
        resp = open_url(url, headers, timeout)   # some servers dislike Range on the first request

    info = ProbeInfo()
    info.url = url
    info.final_url = resp.geturl()
    hdr = resp.headers
    info.content_type = (hdr.get('Content-Type') or '').split(';')[0].strip().lower()
    name = (parse_content_disposition(hdr.get('Content-Disposition'))
            or filename_from_url(info.final_url) or filename_from_url(url))
    if resp.status == 206:
        m = re.match(r'\s*bytes\s+\d+-\d+/(\d+|\*)', hdr.get('Content-Range') or '', re.I)
        info.size = int(m.group(1)) if m and m.group(1) != '*' else -1
        info.resumable = True
        resp.close()
    else:
        length = (hdr.get('Content-Length') or '').strip()
        info.size = int(length) if length.isdigit() else -1
        info.resumable = False
        info.response = resp
    info.filename = _name_with_ext(name, info.content_type)
    return info


class RateLimiter:
    """Token bucket shared by every connection (global speed limit)."""

    def __init__(self, bytes_per_sec=0):
        self._lock = threading.Lock()
        self.rate = 0
        self._tokens = 0.0
        self._last = time.monotonic()
        self.set_rate(bytes_per_sec)

    def set_rate(self, bytes_per_sec):
        with self._lock:
            self.rate = max(0, int(bytes_per_sec or 0))
            self._tokens = 0.0
            self._last = time.monotonic()

    def consume(self, n, stop_event):
        rate = self.rate
        if rate <= 0:
            return
        with self._lock:
            now = time.monotonic()
            self._tokens = min(float(rate), self._tokens + (now - self._last) * rate)
            self._last = now
            self._tokens -= n
            deficit = -self._tokens
        if deficit > 0:
            stop_event.wait(deficit / rate)


class Segment:
    __slots__ = ('start', 'end', 'pos', 'active')

    def __init__(self, start, end, pos=None):
        self.start = start
        self.end = end              # inclusive; None = read until the server closes
        self.pos = start if pos is None else pos
        self.active = False

    @property
    def done(self):
        return self.end is not None and self.pos > self.end

    @property
    def remaining(self):
        return 0 if self.end is None else max(0, self.end - self.pos + 1)


class _Session:
    """One start->stop run of a download. Pausing kills the session, resuming creates a new one."""

    def __init__(self):
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.fh = None
        self.workers = 0
        self.finished = False
        self.last_error = ''


class _ServerError(Exception):
    pass


class Download:
    kind = 'http'
    reports_speed = False

    def __init__(self, url, folder, filename='', headers=None, connections=8):
        self.id = uuid.uuid4().hex[:12]
        self.url = url
        self.folder = folder
        self.filename = filename or ''
        self.headers = dict(headers or {})
        self.max_connections = max(1, int(connections))
        self.size = -1
        self.downloaded = 0
        self.resumable = None
        self.segments = []
        self.status = QUEUED
        self.error = ''
        self.message = ''
        self.content_type = ''
        self.added = time.time()
        self.finished_at = None
        self.speed = 0.0
        self.eta = None
        self.auto_folder = False
        # wired up by the manager
        self.limiter = None
        self.on_finish = None
        self.resolve_name = None
        self.postprocess = None
        self._sess = None
        self._samples = collections.deque()

    # ----- derived -------------------------------------------------------------
    @property
    def path(self):
        return os.path.join(self.folder, self.filename) if self.filename else ''

    @property
    def temp_path(self):
        return self.path + TEMP_SUFFIX if self.filename else ''

    @property
    def display_name(self):
        return self.filename or filename_from_url(self.url) or self.url

    @property
    def category(self):
        return category_of(self.display_name)

    @property
    def progress(self):
        if self.status == COMPLETED:
            return 1.0
        if self.size and self.size > 0:
            return min(1.0, self.downloaded / self.size)
        return None

    @property
    def active_connections(self):
        return sum(1 for s in list(self.segments) if s.active)

    @property
    def running(self):
        sess = self._sess
        return sess is not None and not sess.finished and not sess.stop.is_set()

    # ----- control ---------------------------------------------------------------
    def start(self):
        if self.status == COMPLETED or self.running:
            return
        sess = _Session()
        self._sess = sess
        self.status = DOWNLOADING
        self.error = ''
        self.message = 'Connecting…'
        self.speed = 0.0
        self._samples.clear()
        threading.Thread(target=self._run, args=(sess,), name=f'nilou-{self.id}', daemon=True).start()

    def stop(self, status=PAUSED):
        sess = self._sess
        if sess is not None:
            with sess.lock:
                if not sess.finished and not sess.stop.is_set():
                    sess.stop.set()
                    self._close_file(sess)
                    self.status = status
                    self.speed = 0.0
                    self.message = ''
                    return
        if self.status in (QUEUED, DOWNLOADING):
            self.status = status
            self.speed = 0.0
            self.message = ''

    def reset(self):
        """Forget all progress (used by Restart)."""
        self.stop(PAUSED)
        if self.temp_path:
            try:
                os.remove(self.temp_path)
            except OSError:
                pass
        self.segments = []
        self.downloaded = 0
        self.size = -1
        self.resumable = None
        self.error = ''

    # ----- persistence -------------------------------------------------------------
    def to_dict(self):
        sess = self._sess
        if sess is not None:
            with sess.lock:
                if sess.fh is not None:
                    try:
                        sess.fh.flush()
                    except (OSError, ValueError):
                        pass
                segs = [[s.start, s.end, s.pos] for s in self.segments if not s.done]
                downloaded = self.downloaded
        else:
            segs = [[s.start, s.end, s.pos] for s in self.segments if not s.done]
            downloaded = self.downloaded
        return {
            'kind': self.kind, 'id': self.id, 'url': self.url, 'folder': self.folder, 'filename': self.filename,
            'headers': self.headers, 'connections': self.max_connections, 'size': self.size,
            'downloaded': downloaded, 'resumable': self.resumable, 'segments': segs,
            'status': self.status, 'error': self.error, 'content_type': self.content_type,
            'added': self.added, 'finished_at': self.finished_at, 'auto_folder': self.auto_folder,
        }

    @classmethod
    def from_dict(cls, data):
        d = cls(data['url'], data['folder'], data.get('filename', ''), data.get('headers'),
                data.get('connections', 8))
        d.id = data.get('id', d.id)
        d.size = data.get('size', -1)
        d.downloaded = data.get('downloaded', 0)
        d.resumable = data.get('resumable')
        d.segments = [Segment(s, e, p) for s, e, p in data.get('segments', [])]
        status = data.get('status', PAUSED)
        d.status = QUEUED if status == DOWNLOADING else status
        d.error = data.get('error', '')
        d.content_type = data.get('content_type', '')
        d.added = data.get('added', d.added)
        d.finished_at = data.get('finished_at')
        d.auto_folder = data.get('auto_folder', False)
        return d

    # ----- the actual work ----------------------------------------------------------
    def _run(self, sess):
        info = None
        try:
            info = probe(self.url, self.headers)
            if sess.stop.is_set():
                info.close()
                return
            if not self.filename:
                if self.resolve_name:
                    self.resolve_name(self, info.filename)
                else:
                    self.filename = info.filename
            os.makedirs(self.folder, exist_ok=True)
            if not self.content_type:
                self.content_type = info.content_type

            with sess.lock:
                if sess.stop.is_set():
                    info.close()
                    return
                temp = self.temp_path
                can_resume = (self.resumable and info.resumable and self.size > 0 and info.size == self.size
                              and os.path.exists(temp) and (self.segments or self.downloaded))
                if can_resume:
                    fh = open(temp, 'r+b')
                    info.close()
                    self.downloaded = self.size - sum(s.remaining for s in self.segments)
                else:
                    self.size = info.size
                    self.resumable = info.resumable
                    self.downloaded = 0
                    if self.resumable and self.size > 0:
                        n = max(1, min(self.max_connections, self.size // MIN_PIECE))
                        step = self.size // n
                        self.segments = [Segment(i * step, self.size - 1 if i == n - 1 else (i + 1) * step - 1)
                                         for i in range(n)]
                    else:
                        self.segments = [Segment(0, self.size - 1 if self.size >= 0 else None)]
                    fh = open(temp, 'wb')
                    if self.size > 0:
                        winutil.set_sparse(fh)
                        fh.truncate(self.size)
                sess.fh = fh
                self.message = ''
                if self.size == 0:
                    stream = None
                    workers = 0
                elif self.resumable and self.size > 0:
                    stream = None
                    workers = self.max_connections
                else:
                    stream = info.response
                    info.response = None
                    workers = 1
                sess.workers = workers
            if workers == 0:
                self._finalize(sess)
                return
            for i in range(workers):
                threading.Thread(target=self._worker, args=(sess, stream if i == 0 else None),
                                 name=f'nilou-{self.id}-{i}', daemon=True).start()
        except Exception as e:  # noqa: BLE001 - every failure becomes a visible error
            if info is not None:
                info.close()
            self._fail(sess, describe_error(e))

    def _claim(self, sess):
        with sess.lock:
            if sess.stop.is_set():
                return None
            for seg in self.segments:
                if not seg.active and not seg.done:
                    seg.active = True
                    return seg
            if not self.resumable or self.size <= 0:
                return None
            best, best_rem = None, 0
            for seg in self.segments:
                if seg.active and seg.remaining > best_rem:
                    best, best_rem = seg, seg.remaining
            if best is None or best_rem < 2 * MIN_PIECE:
                return None
            mid = best.pos + best_rem // 2
            new = Segment(mid, best.end)
            new.active = True
            best.end = mid - 1
            self.segments.append(new)
            self.segments.sort(key=lambda s: s.start)
            return new

    def _worker(self, sess, stream=None):
        seg = None
        retries = 0
        try:
            while not sess.stop.is_set():
                if seg is None:
                    seg = self._claim(sess)
                    if seg is None:
                        break
                    retries = 0
                try:
                    self._transfer(sess, seg, stream)
                    stream = None
                except Exception as e:  # noqa: BLE001
                    stream = None
                    if sess.stop.is_set():
                        break
                    code = getattr(e, 'code', None)
                    if isinstance(e, urllib.error.HTTPError):
                        e.close()
                    with sess.lock:
                        others = sess.workers - 1
                    if code in (429, 503) and others > 0:
                        break           # the server wants fewer connections; others will take this segment
                    retries += 1
                    if code in _FATAL_HTTP or isinstance(e, _ServerError) or retries > MAX_RETRIES:
                        sess.last_error = describe_error(e)
                        break
                    self.message = f'Reconnecting ({retries}/{MAX_RETRIES})…'
                    sess.stop.wait(min(2 ** retries, 20))
                    continue
                if sess.stop.is_set():
                    break
                with sess.lock:
                    if seg.done:
                        seg.active = False
                        if seg in self.segments:
                            self.segments.remove(seg)
                        seg = None
        finally:
            with sess.lock:
                if seg is not None:
                    seg.active = False
                sess.workers -= 1
                last = sess.workers == 0
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    pass
            if last:
                self._workers_done(sess)

    def _transfer(self, sess, seg, resp=None):
        if resp is None:
            headers = dict(self.headers)
            with sess.lock:
                if not self.resumable and seg.pos > 0:
                    self.downloaded -= seg.pos    # no resume support: start this stream over
                    seg.pos = 0
                start, end = seg.pos, seg.end
            if self.resumable:
                headers['Range'] = f'bytes={start}-' + ('' if end is None else str(end))
            resp = open_url(self.url, headers)
            if self.resumable:
                if resp.status == 206:
                    m = re.match(r'\s*bytes\s+(\d+)-', resp.headers.get('Content-Range') or '', re.I)
                    if m and int(m.group(1)) != start:
                        resp.close()
                        raise _ServerError('The server sent the wrong part of the file')
                elif start != 0:
                    resp.close()
                    raise ConnectionError('The server ignored the resume request')
        self.message = ''
        read = getattr(resp, 'read1', None) or resp.read
        limiter = self.limiter
        try:
            while True:
                if sess.stop.is_set():
                    return
                with sess.lock:
                    want = CHUNK if seg.end is None else min(CHUNK, seg.end - seg.pos + 1)
                if want <= 0:
                    return
                data = read(want)
                if not data:
                    if seg.end is None:
                        with sess.lock:
                            seg.end = seg.pos - 1
                            self.size = self.downloaded
                        return
                    raise ConnectionError('The connection closed early')
                with sess.lock:
                    if sess.stop.is_set() or sess.fh is None:
                        return
                    if seg.end is not None:
                        allowed = seg.end - seg.pos + 1
                        if allowed <= 0:
                            return
                        if len(data) > allowed:
                            data = data[:allowed]
                    sess.fh.seek(seg.pos)
                    sess.fh.write(data)
                    seg.pos += len(data)
                    self.downloaded += len(data)
                if limiter is not None:
                    limiter.consume(len(data), sess.stop)
        finally:
            try:
                resp.close()
            except Exception:
                pass

    def _workers_done(self, sess):
        if sess.stop.is_set():
            return
        with sess.lock:
            incomplete = any(not s.done for s in self.segments)
        if incomplete:
            self._fail(sess, sess.last_error or 'The connection was lost')
        else:
            self._finalize(sess)

    @staticmethod
    def _close_file(sess):
        if sess.fh is not None:
            try:
                sess.fh.flush()
                sess.fh.close()
            except (OSError, ValueError):
                pass
            sess.fh = None

    def _finalize(self, sess):
        with sess.lock:
            if sess.stop.is_set() or sess.finished:
                return
            sess.finished = True
            fh, sess.fh = sess.fh, None
        try:
            if fh is not None:
                fh.flush()
                if self.size >= 0:
                    fh.truncate(self.size)
                winutil.set_sparse(fh, False)
                fh.close()
            final = self.path
            if os.path.exists(final):
                stem, ext = os.path.splitext(self.filename)
                i = 1
                while os.path.exists(os.path.join(self.folder, f'{stem} ({i}){ext}')):
                    i += 1
                self.filename = f'{stem} ({i}){ext}'
                final = self.path
            os.replace(final + TEMP_SUFFIX, final)
            self.segments = []
            if self.size >= 0:
                self.downloaded = self.size
            if self.postprocess is not None:
                try:
                    self.postprocess(self)
                except Exception:   # noqa: BLE001 - a failed conversion must not lose the download
                    pass
            self.status = COMPLETED
            self.finished_at = time.time()
        except Exception as e:  # noqa: BLE001
            self.status = ERROR
            self.error = f'Could not save the file: {describe_error(e)}'
        self.speed = 0.0
        self.message = ''
        if self.on_finish:
            self.on_finish(self)

    def _fail(self, sess, message):
        with sess.lock:
            if sess.stop.is_set() or sess.finished:
                return
            sess.finished = True
            sess.stop.set()
            self._close_file(sess)
        self.status = ERROR
        self.error = message
        self.speed = 0.0
        self.message = ''
        if self.on_finish:
            self.on_finish(self)
