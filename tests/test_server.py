"""The localhost API must accept the extension and local tools, but never web pages."""
import json
import os
import sys
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nilou import server  # noqa: E402


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.calls = []
        cls.api = server.LocalServer(0, lambda action, data: (cls.calls.append((action, data)) or True, ''))
        assert cls.api.bind()
        cls.port = cls.api.httpd.server_address[1]
        cls.api.start()
        cls.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    @classmethod
    def tearDownClass(cls):
        cls.api.stop()

    def post(self, action, data, headers=None):
        h = {'Content-Type': 'application/json'}
        h.update(headers or {})
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}/{action}', data=json.dumps(data).encode(),
                                     headers=h, method='POST')
        try:
            with self.opener.open(req, timeout=5) as r:
                return r.status
        except urllib.error.HTTPError as e:
            return e.code

    def test_local_and_extension_allowed(self):
        self.assertEqual(self.post('download', {'url': 'https://a.test/f.zip'}), 200)
        self.assertEqual(self.post('download', {'url': 'https://a.test/g.zip'},
                                   {'Origin': 'chrome-extension://abcdef'}), 200)
        self.assertTrue(server.ping(self.port))

    def test_web_pages_rejected(self):
        before = len(self.calls)
        self.assertEqual(self.post('download', {'url': 'https://evil.test/x'}, {'Origin': 'https://evil.test'}), 403)
        self.assertEqual(self.post('download', {'url': 'https://evil.test/x'}, {'Host': 'evil.test:80'}), 403)
        self.assertEqual(self.post('download', {'url': 'https://evil.test/x'}, {'Content-Type': 'text/plain'}), 415)
        self.assertEqual(len(self.calls), before)

    def test_second_server_cannot_bind_same_port(self):
        other = server.LocalServer(self.port, lambda a, d: (True, ''))
        self.assertFalse(other.bind())


if __name__ == '__main__':
    unittest.main()
