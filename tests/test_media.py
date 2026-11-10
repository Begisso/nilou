"""Offline tests for the yt-dlp integration (no network, no external tools)."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nilou import media, util  # noqa: E402
from nilou.grab import _Collector  # noqa: E402


class MediaParsingTests(unittest.TestCase):
    def test_progress_from_two_streams(self):
        d = media.MediaDownload('https://youtu.be/x', 'C:\\Videos', '1080', 'Test')
        d.handle_line('[nilou-t] Lotus timelapse')
        d.handle_line('[nilou-p] downloading|1048576|10485760|NA|524288.5|17|137')
        self.assertEqual((d.downloaded, d.size), (1048576, 10485760))
        self.assertAlmostEqual(d.speed, 524288.5)
        d.handle_line('[nilou-p] finished|10485760|10485760|NA|NA|NA|137')
        self.assertEqual(d.message, 'Processing…')
        d.handle_line('[nilou-p] downloading|1000|NA|2000000|1000|5|140')   # audio stream, size estimated
        self.assertEqual((d.downloaded, d.size), (10486760, 12485760))
        self.assertEqual(d.message, '')
        d.handle_line('[Merger] Merging formats into "C:\\Videos\\Lotus timelapse [x].mp4"')
        self.assertEqual(d.message, 'Processing…')
        d.handle_line('[nilou-f] C:\\Videos\\Lotus timelapse [x].mp4')
        self.assertEqual(d.filename, 'Lotus timelapse [x].mp4')
        self.assertEqual(d.title, 'Lotus timelapse')
        d.handle_line('ERROR: [youtube] x: Video unavailable')
        self.assertEqual(d._last_error, '[youtube] x: Video unavailable')

    def test_quality_args(self):
        self.assertIn('res:720,ext:mp4:m4a', media.quality_args('720'))
        self.assertIn('mp3', media.quality_args('mp3'))
        self.assertIn('--merge-output-format', media.quality_args('best'))

    def test_cookie_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'c.txt')
            media.write_cookie_file([
                {'domain': '.x.com', 'hostOnly': False, 'path': '/', 'secure': True, 'expirationDate': 1900000000.5,
                 'name': 'auth_token', 'value': 'abc'},
                {'domain': 'x.com', 'hostOnly': True, 'path': '/', 'secure': False, 'name': 'lang', 'value': 'en'},
            ], path)
            lines = open(path, encoding='utf-8').read().splitlines()
        self.assertEqual(lines[0], '# Netscape HTTP Cookie File')
        self.assertEqual(lines[1].split('\t'), ['.x.com', 'TRUE', '/', 'TRUE', '1900000000', 'auth_token', 'abc'])
        self.assertEqual(lines[2].split('\t')[:2], ['x.com', 'FALSE'])

    def test_media_site_detection(self):
        for url in ('https://www.youtube.com/watch?v=abc', 'https://youtu.be/abc', 'https://x.com/user/status/1',
                    'https://twitter.com/user/status/1', 'https://m.youtube.com/shorts/abc'):
            self.assertTrue(util.is_media_site(url), url)
        for url in ('https://example.com/video.mp4', 'https://notyoutube.com/watch', 'https://xbox.com/'):
            self.assertFalse(util.is_media_site(url), url)
        self.assertEqual(util.site_name('https://x.com/a/status/1'), 'X (Twitter)')


class GrabTests(unittest.TestCase):
    def test_collects_media(self):
        p = _Collector('https://site.test/gallery/')
        p.feed('<title> Lotus  pond </title><img srcset="a-1x.jpg 1x, a-2x.jpg 2x" width="800" height="600">'
               '<img data-src="/lazy.webp"><video poster="p.jpg"><source src="clip.mp4"></video>'
               '<a href="files/report.pdf">pdf</a><a href="/about">about</a>'
               '<meta property="og:image" content="https://cdn.test/og.png">')
        urls = {it['url']: it['type'] for it in p.items.values()}
        self.assertEqual(urls, {
            'https://site.test/gallery/a-2x.jpg': 'image', 'https://site.test/lazy.webp': 'image',
            'https://site.test/gallery/p.jpg': 'image', 'https://site.test/gallery/clip.mp4': 'video',
            'https://site.test/gallery/files/report.pdf': 'file', 'https://cdn.test/og.png': 'image',
        })
        self.assertEqual(' '.join(p.title.split()), 'Lotus pond')


if __name__ == '__main__':
    unittest.main()
