"""Engine tests against a local HTTP server. Run: python -m unittest discover tests"""
import hashlib
import http.server
import os
import random
import re
import shutil
import socketserver
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nilou import engine  # noqa: E402
from nilou.engine import COMPLETED, ERROR, PAUSED, Download  # noqa: E402

DATA = random.Random(7).randbytes(9 * 1024 * 1024 + 12345)
SMALL = b'hello nilou' * 100


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    throttle = 0.0
    webp = b''

    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path.startswith('/norange'):
            return self._send_full(DATA, ranges=False)
        if self.path.startswith('/chunked'):
            self.send_response(200)
            self.send_header('Transfer-Encoding', 'chunked')
            self.end_headers()
            for i in range(0, len(SMALL), 100):
                part = SMALL[i:i + 100]
                self.wfile.write(b'%x\r\n%s\r\n' % (len(part), part))
            self.wfile.write(b'0\r\n\r\n')
            return
        if self.path.startswith('/named'):
            return self._send_full(SMALL, ranges=True, extra={'Content-Disposition': 'attachment; filename="report final.txt"'})
        if self.path.startswith('/webp'):
            return self._send_full(Handler.webp, ranges=True)
        if self.path.startswith('/missing'):
            self.send_error(404)
            return
        return self._send_full(DATA, ranges=True)

    def _send_full(self, data, ranges, extra=None):
        rng = self.headers.get('Range')
        m = re.match(r'bytes=(\d+)-(\d*)', rng or '')
        if ranges and m:
            start = int(m.group(1))
            end = int(m.group(2)) if m.group(2) else len(data) - 1
            end = min(end, len(data) - 1)
            body = data[start:end + 1]
            self.send_response(206)
            self.send_header('Content-Range', f'bytes {start}-{end}/{len(data)}')
        else:
            body = data
            self.send_response(200)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Content-Type', 'application/octet-stream')
        if ranges:
            self.send_header('Accept-Ranges', 'bytes')
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        try:
            step = 64 * 1024
            for i in range(0, len(body), step):
                self.wfile.write(body[i:i + step])
                if Handler.throttle:
                    time.sleep(Handler.throttle)
        except (ConnectionError, OSError):
            pass


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True


def wait(d, statuses=(COMPLETED, ERROR), timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        if d.status in statuses:
            return d.status
        time.sleep(0.05)
    raise AssertionError(f'timed out in status {d.status} ({d.error})')


class EngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = Server(('127.0.0.1', 0), Handler)
        cls.base = f'http://127.0.0.1:{cls.httpd.server_address[1]}'
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix='nilou-test-')
        Handler.throttle = 0.0

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def check_file(self, d, data):
        with open(d.path, 'rb') as f:
            self.assertEqual(hashlib.sha256(f.read()).hexdigest(), hashlib.sha256(data).hexdigest())
        self.assertFalse(os.path.exists(d.path + engine.TEMP_SUFFIX))

    def test_multi_connection(self):
        d = Download(self.base + '/file.bin', self.dir, connections=8)
        d.start()
        self.assertEqual(wait(d), COMPLETED, d.error)
        self.assertEqual(d.filename, 'file.bin')
        self.assertTrue(d.resumable)
        self.check_file(d, DATA)

    def test_pause_resume(self):
        Handler.throttle = 0.01
        d = Download(self.base + '/big.bin', self.dir, connections=6)
        d.start()
        while d.downloaded < 2 * 1024 * 1024:
            time.sleep(0.05)
        d.stop(PAUSED)
        self.assertEqual(d.status, PAUSED)
        saved = d.to_dict()
        time.sleep(0.5)
        Handler.throttle = 0.0
        d2 = Download.from_dict(saved)       # simulate an app restart
        self.assertGreater(d2.downloaded, 0)
        d2.start()
        self.assertEqual(wait(d2), COMPLETED, d2.error)
        self.check_file(d2, DATA)

    def test_no_range_support(self):
        d = Download(self.base + '/norange/x.bin', self.dir, connections=8)
        d.start()
        self.assertEqual(wait(d), COMPLETED, d.error)
        self.assertFalse(d.resumable)
        self.check_file(d, DATA)

    def test_chunked_unknown_size(self):
        d = Download(self.base + '/chunked/data.txt', self.dir)
        d.start()
        self.assertEqual(wait(d), COMPLETED, d.error)
        self.check_file(d, SMALL)
        self.assertEqual(d.size, len(SMALL))

    def test_content_disposition_name(self):
        d = Download(self.base + '/named/get?id=1', self.dir)
        d.start()
        self.assertEqual(wait(d), COMPLETED, d.error)
        self.assertEqual(d.filename, 'report final.txt')
        self.check_file(d, SMALL)

    def test_404_is_error(self):
        d = Download(self.base + '/missing/file.zip', self.dir)
        d.start()
        self.assertEqual(wait(d), ERROR)
        self.assertIn('404', d.error)

    def test_friendly_errors(self):
        d = Download('http://127.0.0.1:1/nothing.zip', self.dir)
        d.start()
        self.assertEqual(wait(d), ERROR)
        self.assertEqual(d.error, 'The server refused the connection')

    def test_webp_saved_as_png(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest('Pillow not installed')
        import io
        from nilou import manager, paths
        buf = io.BytesIO()
        Image.new('RGBA', (40, 30), (52, 136, 236, 200)).save(buf, 'WEBP')
        Handler.webp = buf.getvalue()
        paths._data_dir = self.dir
        m = manager.DownloadManager(dict(manager.DEFAULT_SETTINGS, download_dir=self.dir))
        try:
            d = m.add(self.base + '/webp/lotus.webp')
            self.assertEqual(wait(d), COMPLETED, d.error)
            self.assertEqual(d.filename, 'lotus.png')
            with Image.open(d.path) as im:
                self.assertEqual((im.format, im.size), ('PNG', (40, 30)))
            self.assertFalse(os.path.exists(os.path.join(self.dir, 'lotus.webp')))
        finally:
            m.shutdown()

    def test_speed_limit(self):
        limiter = engine.RateLimiter(2 * 1024 * 1024)
        d = Download(self.base + '/limited.bin', self.dir, connections=4)
        d.limiter = limiter
        t0 = time.time()
        d.start()
        self.assertEqual(wait(d), COMPLETED, d.error)
        elapsed = time.time() - t0
        self.assertGreater(elapsed, 3.0)   # 9 MB at 2 MB/s should take ~4.5 s
        self.check_file(d, DATA)


if __name__ == '__main__':
    unittest.main()
