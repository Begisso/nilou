"""Find images, videos, audio and files linked from a web page."""
import html.parser
import urllib.parse

from .engine import open_url
from .util import CATEGORIES, extension, filename_from_url

_IMAGE = dict(CATEGORIES)['Images']
_VIDEO = dict(CATEGORIES)['Video'] | {'m3u8'}
_AUDIO = dict(CATEGORIES)['Music']
_FILES = dict(CATEGORIES)['Documents'] | dict(CATEGORIES)['Archives'] | dict(CATEGORIES)['Programs']
_FILES -= {'md', 'txt', 'csv'}


def kind_of(url, hint=None):
    ext = extension(filename_from_url(url))
    if ext in _IMAGE:
        return 'image'
    if ext in _VIDEO:
        return 'video'
    if ext in _AUDIO:
        return 'audio'
    if ext in _FILES:
        return 'file'
    return hint


def _largest_from_srcset(srcset):
    best, best_score = None, -1.0
    for part in (srcset or '').split(','):
        bits = part.strip().split()
        if not bits:
            continue
        score = 1.0
        if len(bits) > 1:
            try:
                score = float(bits[1].rstrip('wx'))
            except ValueError:
                pass
        if score > best_score:
            best, best_score = bits[0], score
    return best


class _Collector(html.parser.HTMLParser):
    def __init__(self, base):
        super().__init__(convert_charrefs=True)
        self.base = base
        self.items = {}
        self.title = ''
        self._in_title = False
        self._media_stack = []

    def add(self, url, kind, **extra):
        if not url:
            return
        url = url.strip()
        if url.startswith(('data:', 'blob:', 'javascript:', '#')):
            return
        try:
            url = urllib.parse.urljoin(self.base, url)
        except ValueError:
            return
        if not url.lower().startswith(('http://', 'https://')):
            return
        url = url.split('#', 1)[0]
        if url not in self.items:
            item = {'url': url, 'type': kind or 'file', 'name': filename_from_url(url)}
            item.update({k: v for k, v in extra.items() if v})
            self.items[url] = item

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or '') for k, v in attrs}
        if tag == 'base' and a.get('href'):
            self.base = urllib.parse.urljoin(self.base, a['href'])
        elif tag == 'title':
            self._in_title = True
        elif tag == 'img':
            size = {}
            for dim in ('width', 'height'):
                if a.get(dim, '').isdigit():
                    size[dim[0]] = int(a[dim])
            src = (_largest_from_srcset(a.get('srcset') or a.get('data-srcset'))
                   or a.get('data-src') or a.get('data-original') or a.get('data-lazy-src') or a.get('src'))
            self.add(src, 'image', alt=a.get('alt', '')[:80], **size)
        elif tag in ('video', 'audio'):
            self._media_stack.append(tag)
            self.add(a.get('src'), tag)
            if a.get('poster'):
                self.add(a['poster'], 'image')
        elif tag == 'source':
            parent = self._media_stack[-1] if self._media_stack else None
            src = a.get('src') or _largest_from_srcset(a.get('srcset'))
            self.add(src, kind_of(src or '', parent or 'image'))
        elif tag == 'a' and a.get('href'):
            kind = kind_of(a['href'])
            if kind:
                self.add(a['href'], kind)
        elif tag == 'meta':
            key = (a.get('property') or a.get('name') or '').lower()
            if key in ('og:image', 'og:image:url', 'og:image:secure_url', 'twitter:image', 'twitter:image:src'):
                self.add(a.get('content'), 'image')
            elif key in ('og:video', 'og:video:url', 'og:video:secure_url', 'twitter:player:stream'):
                self.add(a.get('content'), 'video')
            elif key in ('og:audio', 'og:audio:url'):
                self.add(a.get('content'), 'audio')
        elif tag == 'link' and 'image_src' in a.get('rel', ''):
            self.add(a.get('href'), 'image')

    def handle_endtag(self, tag):
        if tag == 'title':
            self._in_title = False
        elif tag in ('video', 'audio') and self._media_stack:
            self._media_stack.pop()

    def handle_data(self, data):
        if self._in_title:
            self.title += data


def grab_page(url, headers=None, limit=8 * 1024 * 1024):
    """Download a page and list the media on it: {'page', 'title', 'items': [...]}"""
    with open_url(url, headers) as resp:
        final = resp.geturl()
        ctype = (resp.headers.get('Content-Type') or '').lower()
        if 'html' not in ctype and 'xml' not in ctype:
            raise ValueError('This link is a file, not a web page')
        raw = resp.read(limit)
        charset = resp.headers.get_content_charset() or 'utf-8'
    try:
        text = raw.decode(charset, 'replace')
    except LookupError:
        text = raw.decode('utf-8', 'replace')
    parser = _Collector(final)
    parser.feed(text)
    parser.close()
    return {'page': final, 'title': ' '.join(parser.title.split()), 'items': list(parser.items.values())}
