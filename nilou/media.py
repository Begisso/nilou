"""Video/audio downloads from YouTube, X (Twitter) and other sites via yt-dlp.

yt-dlp, Deno (needed by yt-dlp for YouTube) and FFmpeg (merges video + audio)
are downloaded on first use into "Nilou Data\\tools", so Nilou.exe stays small
and the tools can be updated without rebuilding Nilou.
"""
import collections
import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
import zipfile

from . import paths
from .engine import COMPLETED, DOWNLOADING, ERROR, PAUSED, QUEUED, Download
from .util import sanitize_filename

CREATE_NO_WINDOW = 0x08000000

# (tool, download url, files to keep)
TOOLS = [
    ('yt-dlp', 'https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe', ['yt-dlp.exe']),
    ('Deno', 'https://github.com/denoland/deno/releases/latest/download/deno-x86_64-pc-windows-msvc.zip',
     ['deno.exe']),
    ('FFmpeg', 'https://github.com/yt-dlp/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip',
     ['ffmpeg.exe', 'ffprobe.exe']),
]

QUALITIES = [
    ('best', 'Best available'),
    ('2160', '2160p (4K)'),
    ('1440', '1440p'),
    ('1080', '1080p'),
    ('720', '720p'),
    ('480', '480p'),
    ('360', '360p'),
    ('mp3', 'Audio only — MP3'),
    ('m4a', 'Audio only — M4A'),
]
QUALITY_LABELS = dict(QUALITIES)


def quality_args(key):
    if key == 'mp3':
        return ['-f', 'ba/b', '-x', '--audio-format', 'mp3', '--audio-quality', '0']
    if key == 'm4a':
        return ['-f', 'ba[ext=m4a]/ba/b', '-x', '--audio-format', 'm4a']
    sort = 'res,ext:mp4:m4a' if key == 'best' else f'res:{key},ext:mp4:m4a'
    return ['-f', 'bv*+ba/b', '-S', sort, '--merge-output-format', 'mp4']


def tool_path(filename):
    return os.path.join(paths.tools_dir(), filename)


def missing_tools():
    return [t for t in TOOLS if not all(os.path.exists(tool_path(f)) for f in t[2])]


def tools_ready():
    return not missing_tools()


def _env():
    env = dict(os.environ)
    env['PATH'] = paths.tools_dir() + os.pathsep + env.get('PATH', '')
    env['PYTHONIOENCODING'] = 'utf-8'
    env['PYTHONUTF8'] = '1'
    env['NO_COLOR'] = '1'
    return env


def _base_cmd():
    return [tool_path('yt-dlp.exe'), '--ignore-config', '--encoding', 'utf-8', '--ffmpeg-location', paths.tools_dir()]


def kill_tree(proc):
    try:
        subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'], capture_output=True,
                       creationflags=CREATE_NO_WINDOW, timeout=10)
    except Exception:
        pass
    try:
        proc.kill()
    except Exception:
        pass


def write_cookie_file(cookies, path):
    """Write browser cookies (list of chrome.cookies objects) as a Netscape cookies.txt."""
    lines = ['# Netscape HTTP Cookie File']
    for c in cookies or []:
        try:
            domain = c['domain']
            host_only = c.get('hostOnly', not domain.startswith('.'))
            if not host_only and not domain.startswith('.'):
                domain = '.' + domain
            expiry = int(c.get('expirationDate') or 0)
            lines.append('\t'.join([domain, 'FALSE' if host_only else 'TRUE', c.get('path', '/'),
                                    'TRUE' if c.get('secure') else 'FALSE', str(expiry), c['name'], c['value']]))
        except (KeyError, TypeError, ValueError):
            continue
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(lines) + '\n')


class ToolInstaller:
    """Fetches missing tools in parallel using Nilou's own engine."""

    def __init__(self, tools=None):
        self.tools = tools if tools is not None else missing_tools()
        self.items = []
        self.done = False
        self.error = ''

    def start(self):
        tmp = os.path.join(paths.tools_dir(), '_download')
        os.makedirs(tmp, exist_ok=True)
        for name, url, files in self.tools:
            fname = url.rsplit('/', 1)[-1]
            for stale in (fname, fname + '.nilou'):
                try:
                    os.remove(os.path.join(tmp, stale))
                except OSError:
                    pass
            d = Download(url, tmp, filename=fname, connections=8)
            self.items.append((name, d, files))
            d.start()
        threading.Thread(target=self._watch, daemon=True).start()
        return self

    def progress(self):
        done = sum(max(0, d.downloaded) for _, d, _ in self.items)
        total = sum(d.size for _, d, _ in self.items if d.size > 0)
        return done, total

    def status_text(self):
        parts = []
        for name, d, _ in self.items:
            if d.status == COMPLETED:
                parts.append(f'{name} ✓')
            elif d.size > 0:
                parts.append(f'{name} {int(100 * d.downloaded / d.size)}%')
            else:
                parts.append(f'{name} …')
        return ' · '.join(parts)

    def cancel(self):
        for _, d, _ in self.items:
            d.stop(PAUSED)

    def _watch(self):
        while any(d.status in (DOWNLOADING, QUEUED) for _, d, _ in self.items):
            time.sleep(0.25)
        failed = [f'{name}: {d.error or d.status}' for name, d, _ in self.items if d.status != COMPLETED]
        if failed:
            self.error = 'Could not download ' + '; '.join(failed)
            self.done = True
            return
        try:
            for name, d, files in self.items:
                if d.filename.lower().endswith('.zip'):
                    with zipfile.ZipFile(d.path) as z:
                        members = z.namelist()
                        for wanted in files:
                            src = next((m for m in members
                                        if m.replace('\\', '/').rsplit('/', 1)[-1].lower() == wanted.lower()), None)
                            if src is None:
                                raise RuntimeError(f'{wanted} is missing from the {name} archive')
                            with z.open(src) as fi, open(tool_path(wanted), 'wb') as fo:
                                shutil.copyfileobj(fi, fo, 1024 * 1024)
                    os.remove(d.path)
                else:
                    os.replace(d.path, tool_path(files[0]))
        except Exception as e:  # noqa: BLE001
            self.error = f'Could not unpack the tools: {e}'
        self.done = True


def fetch_info(url, cookies=None, timeout=120):
    """Run yt-dlp -J and return a small summary dict (raises RuntimeError with yt-dlp's message)."""
    cmd = _base_cmd() + ['-J', '--no-playlist', '--flat-playlist', '--no-warnings']
    cookie_file = None
    if cookies:
        cookie_file = os.path.join(paths.sub_dir('tmp'), f'cookies-{uuid.uuid4().hex[:8]}.txt')
        write_cookie_file(cookies, cookie_file)
        cmd += ['--cookies', cookie_file]
    cmd += ['--', url]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout, creationflags=CREATE_NO_WINDOW, env=_env(),
                           stdin=subprocess.DEVNULL)
    finally:
        if cookie_file:
            try:
                os.remove(cookie_file)
            except OSError:
                pass
    out = r.stdout.decode('utf-8', 'replace')
    err = r.stderr.decode('utf-8', 'replace')
    if r.returncode != 0 or not out.strip():
        lines = [ln[6:].strip() for ln in err.splitlines() if ln.startswith('ERROR:')]
        raise RuntimeError(lines[-1] if lines else (err.strip().splitlines() or ['yt-dlp failed'])[-1])
    data = json.loads(out)
    info = {
        'title': data.get('title') or data.get('id') or 'video',
        'id': data.get('id') or '',
        'uploader': data.get('uploader') or data.get('channel') or data.get('uploader_id') or '',
        'duration': data.get('duration'),
        'thumbnail': data.get('thumbnail') or '',
        'url': data.get('webpage_url') or url,
        'extractor': data.get('extractor_key') or data.get('extractor') or '',
        'playlist': data.get('_type') == 'playlist',
        'entries': [],
        'heights': [],
        'filesize': None,
    }
    if info['playlist']:
        for e in data.get('entries') or []:
            if not e:
                continue
            u = e.get('url') or e.get('webpage_url')
            if u and not u.startswith('http') and e.get('ie_key') == 'Youtube':
                u = f'https://www.youtube.com/watch?v={u}'
            if u:
                info['entries'].append({'url': u, 'title': e.get('title') or u, 'id': e.get('id') or ''})
    heights = set()
    for f in data.get('formats') or []:
        if f.get('vcodec') not in (None, 'none') and f.get('height'):
            heights.add(int(f['height']))
    info['heights'] = sorted(heights, reverse=True)
    return info


class MediaDownload:
    """A yt-dlp job that looks like a Download to the manager and the UI."""
    kind = 'media'
    reports_speed = True

    def __init__(self, url, folder, quality='best', title='', video_id='', cookies=None, headers=None):
        self.id = uuid.uuid4().hex[:12]
        self.url = url
        self.folder = folder
        self.quality = quality
        self.title = title
        self.video_id = video_id
        ext = '.mp3' if quality == 'mp3' else '.m4a' if quality == 'm4a' else '.mp4'
        self.filename = sanitize_filename(title) + ext if title else ''
        self.cookies = list(cookies or [])
        self.headers = dict(headers or {})
        self.size = -1
        self.downloaded = 0
        self.speed = 0.0
        self.eta = None
        self.status = QUEUED
        self.error = ''
        self.message = ''
        self.added = time.time()
        self.finished_at = None
        self.resumable = True
        self.segments = []
        self.max_connections = 1
        self.content_type = ''
        self.auto_folder = False
        self.on_finish = None
        self.limiter = None
        self.resolve_name = None
        self.postprocess = None
        self._proc = None
        self._gen = 0
        self._lock = threading.Lock()
        self._samples = collections.deque()
        self._streams = ({}, {})
        self._last_error = ''

    @property
    def path(self):
        return os.path.join(self.folder, self.filename) if self.filename else ''

    @property
    def temp_path(self):
        return ''

    @property
    def display_name(self):
        return self.filename or self.title or self.url

    @property
    def category(self):
        return 'Music' if self.quality in ('mp3', 'm4a') else 'Video'

    @property
    def progress(self):
        if self.status == COMPLETED:
            return 1.0
        if self.size and self.size > 0:
            return min(1.0, self.downloaded / self.size)
        return None

    @property
    def active_connections(self):
        return 1 if self.status == DOWNLOADING else 0

    @property
    def running(self):
        p = self._proc
        return p is not None and p.poll() is None

    def start(self):
        with self._lock:
            if self.status == COMPLETED or self.running:
                return
            self._gen += 1
            gen = self._gen
            self.status = DOWNLOADING
            self.error = ''
            self.message = 'Starting…'
            self.speed = 0.0
        threading.Thread(target=self._run, args=(gen,), name=f'nilou-media-{self.id}', daemon=True).start()

    def stop(self, status=PAUSED):
        with self._lock:
            if self.status not in (DOWNLOADING, QUEUED):
                return
            self._gen += 1
            proc, self._proc = self._proc, None
            self.status = status
            self.speed = 0.0
            self.message = ''
        if proc is not None:
            kill_tree(proc)

    def reset(self):
        self.stop(PAUSED)
        self.delete_partials()
        self.size = -1
        self.downloaded = 0
        self.error = ''

    def delete_partials(self):
        if not self.video_id or not os.path.isdir(self.folder):
            return
        tag = f'[{self.video_id}]'
        partial = re.compile(r'(\.part(-Frag\d+)?$|\.ytdl$|\.temp\.\w+$|\.f[\w-]+\.\w+$)')
        for name in os.listdir(self.folder):
            if tag in name and name != self.filename and partial.search(name):
                try:
                    os.remove(os.path.join(self.folder, name))
                except OSError:
                    pass

    def to_dict(self):
        return {
            'kind': self.kind, 'id': self.id, 'url': self.url, 'folder': self.folder, 'filename': self.filename,
            'title': self.title, 'video_id': self.video_id, 'quality': self.quality,
            'cookies': self.cookies if self.status != COMPLETED else [], 'headers': self.headers,
            'size': self.size, 'downloaded': self.downloaded, 'status': self.status, 'error': self.error,
            'added': self.added, 'finished_at': self.finished_at,
        }

    @classmethod
    def from_dict(cls, data):
        d = cls(data['url'], data['folder'], data.get('quality', 'best'), data.get('title', ''),
                data.get('video_id', ''), data.get('cookies'), data.get('headers'))
        d.id = data.get('id', d.id)
        d.filename = data.get('filename', d.filename)
        d.size = data.get('size', -1)
        d.downloaded = data.get('downloaded', 0)
        status = data.get('status', PAUSED)
        d.status = QUEUED if status == DOWNLOADING else status
        d.error = data.get('error', '')
        d.added = data.get('added', d.added)
        d.finished_at = data.get('finished_at')
        return d

    @staticmethod
    def _num(value):
        try:
            v = float(value)
            return v if v == v else None   # filter NaN
        except (TypeError, ValueError):
            return None

    def _run(self, gen):
        if not tools_ready():
            self._finish(gen, -1, 'Media tools are missing. Use "Download video" to set them up again.')
            return
        os.makedirs(self.folder, exist_ok=True)
        cookie_file = None
        cmd = _base_cmd() + [
            '--newline', '--progress', '--no-simulate', '--no-mtime', '--windows-filenames', '--no-playlist',
            '-P', self.folder, '-o', '%(title).150B [%(id)s].%(ext)s',
            '--progress-template',
            'download:[nilou-p] %(progress.status)s|%(progress.downloaded_bytes)s|%(progress.total_bytes)s|'
            '%(progress.total_bytes_estimate)s|%(progress.speed)s|%(progress.eta)s|%(info.format_id)s',
            '--print', 'before_dl:[nilou-t] %(title)s',
            '--print', 'after_move:[nilou-f] %(filepath)s',
        ] + quality_args(self.quality)
        if self.cookies:
            cookie_file = os.path.join(paths.sub_dir('tmp'), f'cookies-{self.id}.txt')
            write_cookie_file(self.cookies, cookie_file)
            cmd += ['--cookies', cookie_file]
        if self.headers.get('Referer'):
            cmd += ['--referer', self.headers['Referer']]
        cmd += ['--', self.url]

        self._streams = ({}, {})
        self._last_error = ''
        last_error = ''
        rc = -1
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                    creationflags=CREATE_NO_WINDOW, env=_env(), cwd=self.folder)
        except OSError as e:
            self._finish(gen, -1, f'Could not start yt-dlp: {e}')
            return
        with self._lock:
            if gen != self._gen:
                kill_tree(proc)
                return
            self._proc = proc
        try:
            for raw in proc.stdout:
                if gen != self._gen:
                    break
                self.handle_line(raw.decode('utf-8', 'replace').strip())
            rc = proc.wait()
            last_error = self._last_error
        except Exception as e:  # noqa: BLE001
            last_error = self._last_error or str(e)
        finally:
            if cookie_file:
                try:
                    os.remove(cookie_file)
                except OSError:
                    pass
        self._finish(gen, rc, last_error)

    def handle_line(self, line):
        """Digest one line of yt-dlp output (progress template, prints and errors)."""
        totals, dones = self._streams
        if line.startswith('[nilou-p] '):
            parts = line[10:].split('|')
            if len(parts) < 7:
                return
            state, done, total, estimate, speed, eta, fid = parts[:7]
            key = fid or '?'
            dones[key] = self._num(done) or 0
            t = self._num(total) or self._num(estimate)
            if t:
                totals[key] = t
            self.downloaded = int(sum(dones.values()))
            self.size = int(sum(totals.values())) if totals else -1
            self.speed = self._num(speed) or 0.0
            self.eta = self._num(eta)
            self.message = 'Processing…' if state == 'finished' else ''
        elif line.startswith('[nilou-t] '):
            self.title = line[10:].strip()
        elif line.startswith('[nilou-f] '):
            fp = line[10:].strip()
            if fp:
                self.folder, self.filename = os.path.split(fp)
        elif line.startswith('ERROR:'):
            self._last_error = line[6:].strip()
        elif line.startswith(('[Merger]', '[ExtractAudio]', '[Fixup', '[VideoConvertor]')):
            self.message = 'Processing…'

    def _finish(self, gen, rc, error):
        with self._lock:
            if gen != self._gen:
                return
            self._proc = None
            self.speed = 0.0
            self.message = ''
            if rc == 0:
                self.status = COMPLETED
                self.finished_at = time.time()
                try:
                    self.size = self.downloaded = os.path.getsize(self.path)
                except OSError:
                    pass
            else:
                self.status = ERROR
                self.error = error or f'yt-dlp stopped with exit code {rc}'
        if self.on_finish:
            self.on_finish(self)


def update_ytdlp():
    """Self-update yt-dlp.exe. Returns its output."""
    r = subprocess.run([tool_path('yt-dlp.exe'), '-U'], capture_output=True, timeout=180,
                       creationflags=CREATE_NO_WINDOW, env=_env())
    return (r.stdout + r.stderr).decode('utf-8', 'replace').strip()


def ytdlp_version():
    try:
        r = subprocess.run([tool_path('yt-dlp.exe'), '--version'], capture_output=True, timeout=30,
                           creationflags=CREATE_NO_WINDOW, env=_env())
        return r.stdout.decode('utf-8', 'replace').strip()
    except Exception:
        return ''
