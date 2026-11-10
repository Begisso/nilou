"""Tiny localhost API used by the browser extension and for single-instance handoff.

Only requests from 127.0.0.1 with no Origin (other local programs, e.g. a
second Nilou.exe) or a browser-extension Origin are accepted, so web pages
cannot push downloads into Nilou.
"""
import http.server
import json
import socket
import socketserver
import threading
import time
import urllib.request

from . import APP_ID, VERSION

_EXTENSION_ORIGINS = ('chrome-extension://', 'moz-extension://', 'extension://', 'safari-web-extension://')


class _Server(socketserver.ThreadingMixIn, socketserver.TCPServer):
    daemon_threads = True
    allow_reuse_address = False

    def server_bind(self):
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class _Handler(http.server.BaseHTTPRequestHandler):
    server_version = 'Nilou/' + VERSION

    def log_message(self, *args):
        pass

    def _allowed(self):
        host = (self.headers.get('Host') or '').rsplit(':', 1)[0].strip('[]').lower()
        if host not in ('127.0.0.1', 'localhost'):
            return False
        origin = self.headers.get('Origin')
        if origin and not origin.startswith(_EXTENSION_ORIGINS):
            return False
        return True

    def _send(self, code, payload):
        body = json.dumps(payload).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def _note_extension(self):
        origin = self.headers.get('Origin') or ''
        if origin.startswith(_EXTENSION_ORIGINS):
            self.server.owner.extension_seen = time.time()

    def do_GET(self):
        if not self._allowed():
            return self._send(403, {'ok': False, 'error': 'forbidden'})
        if self.path.split('?')[0] == '/ping':
            self._note_extension()
            return self._send(200, {'ok': True, 'app': APP_ID, 'version': VERSION})
        self._send(404, {'ok': False, 'error': 'not found'})

    def do_POST(self):
        try:
            length = int(self.headers.get('Content-Length') or 0)
        except ValueError:
            length = -1
        if length < 0 or length > 4 * 1024 * 1024:
            self.close_connection = True
            return self._send(413, {'ok': False, 'error': 'too large'})
        body = self.rfile.read(length)    # always drain the body so the reply is not lost to a TCP reset
        if not self._allowed():
            return self._send(403, {'ok': False, 'error': 'forbidden'})
        ctype = (self.headers.get('Content-Type') or '').split(';')[0].strip().lower()
        if ctype != 'application/json':
            return self._send(415, {'ok': False, 'error': 'expected application/json'})
        try:
            data = json.loads(body or b'{}')
            if not isinstance(data, dict):
                raise ValueError
        except ValueError:
            return self._send(400, {'ok': False, 'error': 'bad json'})
        self._note_extension()
        action = self.path.split('?')[0].strip('/')
        if action not in ('download', 'media', 'grab', 'show', 'add'):
            return self._send(404, {'ok': False, 'error': 'not found'})
        ok, error = self.server.owner.dispatch(action, data)
        self._send(200 if ok else 400, {'ok': ok, 'error': error})


class LocalServer:
    def __init__(self, port, handler):
        self.port = port
        self.handler = handler          # callable(action, data) -> (ok, error)
        self.httpd = None
        self._serving = False
        self.extension_seen = 0.0

    def bind(self):
        try:
            self.httpd = _Server(('127.0.0.1', self.port), _Handler)
        except OSError:
            self.httpd = None
            return False
        self.httpd.owner = self
        return True

    def start(self):
        if self.httpd and not self._serving:
            self._serving = True
            threading.Thread(target=self.httpd.serve_forever, name='nilou-api', daemon=True).start()

    def stop(self):
        if self.httpd:
            try:
                if self._serving:          # shutdown() blocks forever if serve_forever never ran
                    self.httpd.shutdown()
                self.httpd.server_close()
            except Exception:
                pass
            self._serving = False

    def dispatch(self, action, data):
        try:
            return self.handler(action, data)
        except Exception as e:  # noqa: BLE001
            return False, str(e)


_LOCAL = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def ping(port, timeout=1.5):
    try:
        with _LOCAL.open(f'http://127.0.0.1:{port}/ping', timeout=timeout) as r:
            return json.loads(r.read()).get('app') == APP_ID
    except Exception:
        return False


def send(port, action, data, timeout=3):
    req = urllib.request.Request(f'http://127.0.0.1:{port}/{action}', data=json.dumps(data).encode('utf-8'),
                                 headers={'Content-Type': 'application/json'}, method='POST')
    try:
        with _LOCAL.open(req, timeout=timeout) as r:
            return bool(json.loads(r.read()).get('ok'))
    except Exception:
        return False
