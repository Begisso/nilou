"""Small helpers: file names, categories and human-friendly formatting."""
import datetime
import os
import re
import time
import urllib.parse

CATEGORIES = [
    ('Video', {'mp4', 'mkv', 'avi', 'mov', 'wmv', 'flv', 'webm', 'm4v', 'mpg', 'mpeg', '3gp', 'ts', 'm2ts', 'vob'}),
    ('Music', {'mp3', 'wav', 'flac', 'aac', 'ogg', 'oga', 'm4a', 'wma', 'opus', 'aiff', 'alac', 'mid', 'midi'}),
    ('Images', {'jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp', 'svg', 'tif', 'tiff', 'ico', 'heic', 'avif', 'psd'}),
    ('Documents', {'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'odt', 'ods', 'odp', 'txt', 'rtf', 'csv',
                   'epub', 'mobi', 'md', 'djvu'}),
    ('Archives', {'zip', 'rar', '7z', 'tar', 'gz', 'tgz', 'bz2', 'xz', 'zst', 'iso', 'img', 'cab', 'lz', 'lzma', 'dmg'}),
    ('Programs', {'exe', 'msi', 'msix', 'msixbundle', 'appx', 'apk', 'jar', 'deb', 'rpm', 'appimage', 'vsix', 'whl'}),
]
CATEGORY_NAMES = [c for c, _ in CATEGORIES] + ['Other']

_BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {'CON', 'PRN', 'AUX', 'NUL'} | {f'COM{i}' for i in range(1, 10)} | {f'LPT{i}' for i in range(1, 10)}
_DOUBLE_EXT = ('.tar.gz', '.tar.bz2', '.tar.xz', '.tar.zst', '.tar.lz')


def extension(name):
    return name.rsplit('.', 1)[-1].lower() if '.' in (name or '') else ''


def category_of(name):
    ext = extension(name)
    for cat, exts in CATEGORIES:
        if ext in exts:
            return cat
    return 'Other'


def sanitize_filename(name, default='download'):
    name = (name or '').replace('\\', '/').split('/')[-1]
    name = _BAD_CHARS.sub('_', name).strip().rstrip('. ')
    if not name:
        name = default
    if name.split('.')[0].upper() in _RESERVED:
        name = '_' + name
    if len(name) > 180:
        stem, ext = split_ext(name)
        name = stem[:180 - len(ext)] + ext
    return name


def split_ext(name):
    low = name.lower()
    for ext in _DOUBLE_EXT:
        if low.endswith(ext) and len(name) > len(ext):
            return name[:-len(ext)], name[-len(ext):]
    return os.path.splitext(name)


def filename_from_url(url):
    try:
        path = urllib.parse.urlsplit(url).path
    except ValueError:
        return ''
    return urllib.parse.unquote(path.rstrip('/').rsplit('/', 1)[-1]) if path else ''


def parse_content_disposition(value):
    if not value:
        return None
    m = re.search(r"filename\*\s*=\s*([^']*)'[^']*'([^;]+)", value, re.I)
    if m:
        enc = (m.group(1) or 'utf-8').strip() or 'utf-8'
        raw = m.group(2).strip().strip('"')
        try:
            return urllib.parse.unquote(raw, encoding=enc, errors='replace')
        except LookupError:
            return urllib.parse.unquote(raw)
    m = re.search(r'filename\s*=\s*"((?:\\.|[^"\\])*)"', value, re.I) or re.search(r'filename\s*=\s*([^;]+)', value, re.I)
    if not m:
        return None
    name = m.group(1).strip()
    try:  # http.client decodes headers as latin-1; many servers really send UTF-8
        name = name.encode('latin-1').decode('utf-8')
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass
    if re.search(r'%[0-9A-Fa-f]{2}', name):
        name = urllib.parse.unquote(name)
    return name or None


URL_RE = re.compile(r'https?://[^\s<>"\'`]+', re.I)


def extract_urls(text):
    found = []
    for m in URL_RE.finditer(text or ''):
        url = m.group(0).rstrip('.,;)]}>')
        if url not in found:
            found.append(url)
    return found


_MEDIA_SITES = re.compile(
    r'^https?://([a-z0-9-]+\.)*(youtube\.com|youtu\.be|youtube-nocookie\.com|x\.com|twitter\.com|vimeo\.com|'
    r'tiktok\.com|instagram\.com|facebook\.com|fb\.watch|reddit\.com|v\.redd\.it|twitch\.tv|dailymotion\.com|'
    r'soundcloud\.com|bilibili\.com|bsky\.app|threads\.net|threads\.com)(/|$)', re.I)


def is_media_site(url):
    return bool(_MEDIA_SITES.match(url or ''))


def site_name(url):
    host = (urllib.parse.urlsplit(url).hostname or '').lower()
    if host.startswith('www.'):
        host = host[4:]
    if 'youtube' in host or host == 'youtu.be':
        return 'YouTube'
    if host in ('x.com', 'twitter.com', 'mobile.twitter.com', 'mobile.x.com'):
        return 'X (Twitter)'
    return host or 'web'


# --- formatting ---------------------------------------------------------------

def fmt_size(n):
    if n is None or n < 0:
        return '—'
    if n < 1024:
        return f'{int(n)} B'
    for unit in ('KB', 'MB', 'GB', 'TB'):
        n /= 1024.0
        if n < 1024 or unit == 'TB':
            if n < 10:
                return f'{n:.2f} {unit}'
            if n < 100:
                return f'{n:.1f} {unit}'
            return f'{n:.0f} {unit}'
    return '—'


def fmt_speed(bps):
    return fmt_size(bps) + '/s' if bps and bps > 0 else ''


def fmt_eta(seconds):
    if seconds is None or seconds < 0 or seconds > 86400 * 30:
        return ''
    s = int(seconds + 0.5)
    if s < 60:
        return f'{s} s'
    m, s = divmod(s, 60)
    if m < 60:
        return f'{m} min {s:02d} s' if m < 10 else f'{m} min'
    h, m = divmod(m, 60)
    if h < 24:
        return f'{h} h {m:02d} min'
    d, h = divmod(h, 24)
    return f'{d} d {h} h'


def fmt_duration(seconds):
    if not seconds:
        return ''
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f'{h}:{m:02d}:{s:02d}' if h else f'{m}:{s:02d}'


def fmt_date(ts):
    if not ts:
        return ''
    dt = datetime.datetime.fromtimestamp(ts)
    today = datetime.date.today()
    if dt.date() == today:
        return dt.strftime('%H:%M')
    if dt.date() == today - datetime.timedelta(days=1):
        return 'Yesterday'
    if dt.year == today.year:
        return f'{dt.strftime("%b")} {dt.day}'
    return dt.strftime('%Y-%m-%d')


def now():
    return time.time()
