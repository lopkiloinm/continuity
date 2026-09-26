import csv
import io
import json
import threading
import unittest
from http.client import HTTPConnection
from http.server import HTTPServer

from continuity import server
from continuity.engine import Job


class QuietHandler(server.Handler):
    def log_message(self, *args):
        pass


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.http = HTTPServer(('127.0.0.1', 0), QuietHandler)
        cls.thread = threading.Thread(target=cls.http.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.http.server_close()
        cls.thread.join()

    def setUp(self):
        server.job = Job()

    def request(self, path, payload=None, headers=None):
        connection = HTTPConnection('127.0.0.1', self.http.server_port)
        connection.request('POST' if payload is not None else 'GET', path,
                           json.dumps(payload) if payload is not None else None,
                           headers or {'Content-Type': 'application/json'})
        response = connection.getresponse()
        result = (response.status, response.read())
        connection.close()
        return result

    def test_browser_assets_and_complete_export(self):
        for path in ('/', '/app.js', '/style.css'):
            status, body = self.request(path)
            self.assertEqual(status, 200)
            self.assertTrue(body)
        self.assertEqual(self.request('/api/result.csv')[0], 409)
        for path, data in (('start', {}), ('fail', {}), ('evaluate', {'scenario': 'clean'}), ('resume', {})):
            self.assertEqual(self.request('/api/' + path, data)[0], 200)
        status, body = self.request('/api/result.csv')
        self.assertEqual(status, 200)
        rows = list(csv.DictReader(io.StringIO(body.decode())))
        self.assertEqual(len(rows), 30)
        self.assertEqual(len({row['record_id'] for row in rows}), 30)
        status, body = self.request('/api/receipt')
        self.assertEqual(json.loads(body)['state'], 'completed')
        self.assertEqual(self.request('/api/resume', {})[0], 409)

    def test_cancel_and_invalid_requests(self):
        for path, data in (('start', {}), ('fail', {}), ('evaluate', {'scenario': 'changed_address'})):
            self.assertEqual(self.request('/api/' + path, data)[0], 200)
        token = server.job.snapshot()['approval_hash']
        self.assertEqual(self.request('/api/decide', {'approved': 'false', 'approval_hash': token})[0], 400)
        status, body = self.request('/api/decide', {'approved': False, 'approval_hash': token})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['state'], 'cancelled')
        self.assertEqual(self.request('/api/resume', {})[0], 409)
        self.assertEqual(self.request('/api/start', [1, 2])[0], 400)
        self.assertEqual(self.request('/api/unknown', {})[0], 404)

    def test_cross_origin_mutation_rejected(self):
        status, _ = self.request('/api/start', {}, {'Content-Type': 'application/json', 'Origin': 'https://example.com'})
        self.assertEqual(status, 403)
        self.assertEqual(server.job.state, 'ready')


if __name__ == '__main__':
    unittest.main()
