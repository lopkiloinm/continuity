import csv
import io
import json
import threading
import unittest
from http.client import HTTPConnection
from http.server import HTTPServer

from continuity import server
from continuity.world import Config, WorldClient
from test_world import Provider


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
        server.sessions.clear()
        server.world_client = WorldClient(Config())
        self.cookie = ''

    def request(self, path, payload=None, headers=None):
        connection = HTTPConnection('127.0.0.1', self.http.server_port)
        request_headers = dict(headers or {'Content-Type': 'application/json'})
        if self.cookie:
            request_headers['Cookie'] = self.cookie
        connection.request('POST' if payload is not None else 'GET', path,
                           json.dumps(payload) if payload is not None else None,
                           request_headers)
        response = connection.getresponse()
        if response.getheader('Set-Cookie'):
            self.cookie = response.getheader('Set-Cookie').split(';')[0]
        result = (response.status, response.read())
        connection.close()
        return result

    def test_browser_assets_and_complete_export(self):
        for path in ('/', '/app.js', '/style.css'):
            status, body = self.request(path)
            self.assertEqual(status, 200)
            self.assertTrue(body)
        self.assertEqual(self.request('/api/result.csv')[0], 409)
        next(iter(server.sessions.values())).owner = ('test-issuer', 'test-owner')
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
        self.request('/api/job')
        next(iter(server.sessions.values())).owner = ('test-issuer', 'test-owner')
        for path, data in (('start', {}), ('fail', {}), ('evaluate', {'scenario': 'changed_address'})):
            self.assertEqual(self.request('/api/' + path, data)[0], 200)
        token = next(iter(server.sessions.values())).job.snapshot()['approval_hash']
        self.assertEqual(self.request('/api/decide', {'approved': 'false', 'approval_hash': token})[0], 400)
        status, body = self.request('/api/decide', {'approved': False, 'approval_hash': token})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['state'], 'cancelled')
        self.assertEqual(self.request('/api/resume', {})[0], 409)
        self.assertEqual(self.request('/api/start', [1, 2])[0], 400)
        self.assertEqual(self.request('/api/unknown', {})[0], 404)

    def test_missing_credentials_and_no_approval_bypass(self):
        status, body = self.request('/api/world/start', {'purpose': 'owner'})
        self.assertEqual(status, 503)
        self.assertEqual(json.loads(body)['code'], 'not_configured')
        self.assertEqual(self.request('/api/start', {})[0], 409)
        session = next(iter(server.sessions.values()))
        session.owner = ('test-issuer', 'test-owner')
        self.request('/api/start', {})
        self.request('/api/fail', {})
        self.request('/api/evaluate', {'scenario': 'changed_address'})
        token = session.job.snapshot()['approval_hash']
        self.assertEqual(self.request('/api/decide', {'approved': True, 'approval_hash': token,
            'evidence': {'binding': token, 'expires_at': 9999999999}})[0], 409)
        self.assertEqual(session.job.state, 'awaiting_approval')
        self.assertIsNone(session.job.agent)

    def test_sessions_are_isolated(self):
        _, body = self.request('/api/job')
        first = json.loads(body)['id']
        self.cookie = ''
        _, body = self.request('/api/job')
        self.assertNotEqual(first, json.loads(body)['id'])

    def test_new_job_keeps_owner_but_discards_handoff_authorization(self):
        self.request('/api/job')
        session = next(iter(server.sessions.values()))
        session.owner = ('test-issuer', 'verified-owner')
        self.request('/api/start', {})
        self.request('/api/fail', {})
        self.request('/api/evaluate', {'scenario': 'changed_address'})
        original_id = session.job.id
        session.world.evidence = {'binding': session.job.snapshot()['approval_hash'], 'expires_at': 9999999999}
        status, body = self.request('/api/reset', {})
        result = json.loads(body)
        self.assertEqual(status, 200)
        self.assertNotEqual(result['id'], original_id)
        self.assertTrue(result['world']['owner_connected'])
        self.assertFalse(result['world']['can_approve'])
        self.assertIsNone(session.world.evidence)
        self.assertIsNone(session.world.attempt)
        self.assertIsNone(result['expires_at'])
        self.assertEqual(result['spent_micro_usdc'], 0)
        self.assertEqual(self.request('/api/start', {})[0], 200)
        self.request('/api/fail', {})
        self.request('/api/evaluate', {'scenario': 'changed_address'})
        self.assertEqual(self.request('/api/decide', {'approved': True,
            'approval_hash': session.job.snapshot()['approval_hash']})[0], 409)

    def test_owner_verification_is_not_bounded_by_old_job_deadline(self):
        import time
        provider = Provider()
        server.world_client = WorldClient(Config('test-client', 'test-secret'), provider)
        self.request('/api/job')
        session = next(iter(server.sessions.values()))
        session.job.expires_at = 1  # A saved pre-fix job that sat on the setup screen.
        status, _ = self.request('/api/world/start', {'purpose': 'owner'})
        self.assertEqual(status, 200)
        self.assertGreater(session.world.attempt['expires_at'], time.time())

    def test_full_owner_and_handoff_verification_through_http(self):
        provider = Provider()
        server.world_client = WorldClient(Config('test-client', 'test-secret'), provider)
        status, body = self.request('/api/world/start', {'purpose': 'owner'})
        self.assertEqual(status, 200)
        session = next(iter(server.sessions.values()))
        session.world.attempt['next_poll'] = 0
        status, body = self.request('/api/world/poll', {})
        self.assertTrue(json.loads(body)['world']['owner_connected'])
        self.assertFalse(json.loads(body)['world']['can_approve'])
        for path, data in (('start', {}), ('fail', {}), ('evaluate', {'scenario': 'changed_address'})):
            self.assertEqual(self.request('/api/' + path, data)[0], 200)
        binding = session.job.snapshot()['approval_hash']
        self.assertEqual(self.request('/api/world/start', {'purpose': 'handoff', 'approval_hash': binding})[0], 200)
        session.world.attempt['next_poll'] = 0
        _, body = self.request('/api/world/poll', {})
        result = json.loads(body)
        self.assertTrue(result['world']['can_approve'])
        self.assertEqual(result['state'], 'awaiting_approval')
        self.assertIsNone(result['active_agent'])
        self.assertEqual(self.request('/api/decide', {'approved': True, 'approval_hash': binding})[0], 200)
        self.assertEqual(self.request('/api/decide', {'approved': True, 'approval_hash': binding})[0], 409)
        self.assertEqual(self.request('/api/resume', {})[0], 200)
        _, receipt = self.request('/api/receipt')
        self.assertIsNotNone(json.loads(receipt)['world_receipt'])
        for secret in ('test-secret', 'private-device-code', 'owner-a', 'id_token'):
            self.assertNotIn(secret, receipt.decode())

    def test_provider_denial_cancels_handoff(self):
        from continuity.world import OAuthError
        provider = Provider()
        server.world_client = WorldClient(Config('test-client', 'test-secret'), provider)
        self.request('/api/job')
        session = next(iter(server.sessions.values()))
        session.owner = ('test-issuer', 'test-owner')
        for path, data in (('start', {}), ('fail', {}), ('evaluate', {'scenario': 'changed_address'})):
            self.request('/api/' + path, data)
        self.request('/api/world/start', {'purpose': 'handoff', 'approval_hash': session.job.snapshot()['approval_hash']})
        session.world.attempt['next_poll'] = 0
        provider.error = OAuthError('access_denied', 'User denied verification')
        _, body = self.request('/api/world/poll', {})
        self.assertEqual(json.loads(body)['state'], 'cancelled')
        self.assertIsNone(session.job.agent)
        self.assertEqual(session.job.spent, 60_000)

    def test_cross_origin_mutation_rejected(self):
        status, _ = self.request('/api/start', {}, {'Content-Type': 'application/json', 'Origin': 'https://example.com'})
        self.assertEqual(status, 403)
        self.assertEqual(len(server.sessions), 0)


if __name__ == '__main__':
    unittest.main()
