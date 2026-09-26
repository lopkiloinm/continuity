import json
import os
import unittest
from unittest.mock import patch

from cryptography.fernet import Fernet
from continuity import server
from continuity.storage import RedisStore, StorageError, SessionBusy, RateLimited, ACQUIRE, COMMIT, RELEASE, RATE


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.locks = {}
        self.counts = {}

    def __call__(self, command, script, numkeys, *args):
        if script == ACQUIRE:
            key, lock, lease = args
            if lock in self.locks:
                return [0]
            self.locks[lock] = lease
            return [1, self.values.get(key, '')]
        if script == COMMIT:
            key, lock, lease, value = args
            if self.locks.get(lock) != lease:
                return 0
            self.values[key] = value
            del self.locks[lock]
            return 1
        if script == RELEASE:
            lock, lease = args
            if self.locks.get(lock) == lease:
                del self.locks[lock]
                return 1
            return 0
        if script == RATE:
            key, seconds = args
            self.counts[key] = self.counts.get(key, 0) + 1
            return self.counts[key]
        raise AssertionError('Unexpected command')


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.backend = FakeRedis()
        self.key = Fernet.generate_key().decode()
        self.store = RedisStore('https://example.upstash.io', 'private', self.key, self.backend)

    def test_encrypted_round_trip_across_instances(self):
        lease, payload = self.store.acquire('session-a')
        self.assertIsNone(payload)
        session = server.Session()
        session.owner = ('private-issuer', 'private-subject')
        session.job.start()
        self.store.commit('session-a', lease, session.serialize())
        ciphertext = next(iter(self.backend.values.values()))
        self.assertNotIn('private-subject', ciphertext)
        other_process = RedisStore('https://example.upstash.io', 'private', self.key, self.backend)
        lease, payload = other_process.acquire('session-a')
        restored = server.Session.restore(payload)
        self.assertEqual(restored.owner, session.owner)
        self.assertEqual(restored.job.id, session.job.id)
        self.assertEqual(len(restored.job.rows), 17)
        self.assertEqual(restored.job.spent, 60_000)
        other_process.release('session-a', lease)

    def test_device_attempt_and_owner_binding_survive_serialization(self):
        session = server.Session()
        session.world.attempt = {'owner': ('issuer', 'subject'), 'device_code': 'private-code', 'status': 'pending'}
        restored = server.Session.restore(json.loads(json.dumps(session.serialize())))
        self.assertEqual(restored.world.attempt['owner'], ('issuer', 'subject'))
        self.assertEqual(restored.world.attempt['device_code'], 'private-code')

    def test_old_ready_session_migrates_without_losing_owner(self):
        session = server.Session()
        session.owner = ('issuer', 'verified-owner')
        session.job.expires_at = 1
        original_id = session.job.id
        restored = server.Session.restore(json.loads(json.dumps(session.serialize())))
        self.assertIsNone(restored.job.expires_at)
        self.assertEqual(restored.owner, session.owner)
        self.assertEqual(restored.job.id, original_id)

    def test_restore_does_not_extend_started_job(self):
        session = server.Session()
        session.job.start()
        session.job.expires_at = 1
        restored = server.Session.restore(json.loads(json.dumps(session.serialize())))
        self.assertEqual(restored.job.expires_at, 1)

    def test_parallel_requests_rejected_and_stale_commit_fenced(self):
        old, _ = self.store.acquire('session')
        with self.assertRaises(SessionBusy):
            self.store.acquire('session')
        self.backend.locks.clear()  # Simulate TTL expiry while the first process stalls.
        new, _ = self.store.acquire('session')
        with self.assertRaises(SessionBusy):
            self.store.commit('session', old, {'value': 'stale'})
        self.store.release('session', old)
        self.assertTrue(self.backend.locks)
        self.store.commit('session', new, {'value': 'new'})
        _, data = self.store.acquire('session')
        self.assertEqual(data['value'], 'new')

    def test_tampered_ciphertext_fails_closed(self):
        lease, _ = self.store.acquire('session')
        self.store.commit('session', lease, {'private': 'data'})
        self.backend.values[self.store.keys('session')[0]] = 'not-authentic'
        with self.assertRaises(StorageError):
            self.store.acquire('session')
        self.assertEqual(self.backend.locks, {})

    def test_rate_limit(self):
        for _ in range(8):
            self.store.limit('a-client')
        with self.assertRaises(RateLimited):
            self.store.limit('a-client')

    def test_missing_production_storage_fails_closed(self):
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(StorageError):
            RedisStore.from_env()

    def test_http_cloud_session_cookie_and_persistence(self):
        import threading
        from http.client import HTTPConnection
        from http.server import HTTPServer
        server.sessions.clear()
        http = HTTPServer(('127.0.0.1', 0), server.Handler)
        thread = threading.Thread(target=http.serve_forever, daemon=True)
        thread.start()
        try:
            with patch.dict(os.environ, {'VERCEL': '1', 'APP_ORIGIN': 'https://continuity.example'}), patch.object(RedisStore, 'from_env', return_value=self.store):
                def request(cookie=None):
                    connection = HTTPConnection('127.0.0.1', http.server_port)
                    headers = {'Host': 'continuity.example'}
                    if cookie:
                        headers['Cookie'] = cookie
                    connection.request('GET', '/api/job', headers=headers)
                    response = connection.getresponse()
                    status, body, cookie = response.status, json.loads(response.read()), response.getheader('Set-Cookie')
                    connection.close()
                    return status, body, cookie
                status, first, cookie = request()
                self.assertEqual(status, 200)
                self.assertIn('Secure', cookie)
                self.assertIn('HttpOnly', cookie)
                self.assertEqual(server.sessions, {})
                status, second, _ = request(cookie.split(';')[0])
                self.assertEqual(status, 200)
                self.assertEqual(first['id'], second['id'])
                self.assertEqual(server.sessions, {})
        finally:
            http.shutdown()
            http.server_close()
            thread.join()


if __name__ == '__main__':
    unittest.main()
