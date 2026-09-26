"""Offline contract/security tests. Test keys/tokens never enter runtime code."""
import json
import time
import unittest
from cryptography.hazmat.primitives.asymmetric import rsa
import jwt

from continuity.world import ACR, ISSUER, Config, OAuthError, WorldClient, WorldError, WorldFlow


class Provider:
    def __init__(self):
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self.key.public_key()))
        self.jwk.update(kid='test-key', use='sig', alg='RS256')
        self.calls = []
        self.now = int(time.time())
        self.error = None
        self.subject = 'owner-a'

    def token(self, **overrides):
        claims = dict(iss=ISSUER, sub=self.subject, aud='test-client', iat=self.now, exp=self.now + 300,
                      jti='test-token', auth_time=self.now, acr=ACR, amr=['pop'])
        claims.update(overrides)
        return jwt.encode(claims, self.key, algorithm='RS256', headers={'kid': 'test-key'})

    def __call__(self, url, form=None, headers=None):
        self.calls.append((url, form, headers))
        if url.endswith('openid-configuration'):
            return dict(issuer=ISSUER, device_authorization_endpoint=ISSUER+'/device',
                        token_endpoint=ISSUER+'/token', jwks_uri=ISSUER+'/keys',
                        token_endpoint_auth_methods_supported=['client_secret_basic', 'client_secret_post'])
        if url.endswith('/keys'):
            return {'keys': [self.jwk]}
        if url.endswith('/device'):
            return dict(device_code='private-device-code', user_code='USER-CODE',
                        verification_uri_complete=ISSUER+'/device?user_code=USER-CODE', expires_in=1200, interval=5)
        if url.endswith('/token'):
            if self.error:
                raise self.error
            return {'id_token': self.token()}
        raise AssertionError('Unexpected URL')


class WorldTests(unittest.TestCase):
    def setUp(self):
        self.provider = Provider()
        self.now = self.provider.now
        self.client = WorldClient(Config('test-client', 'test-secret'), self.provider, lambda: self.now)
        self.flow = WorldFlow(self.client, lambda: self.now)

    def start(self, **kwargs):
        self.flow.start('handoff', 'intent-hash', owner=(ISSUER, 'owner-a'), **kwargs)
        self.now += 5

    def test_real_crypto_validation_and_single_use_evidence(self):
        self.start()
        identity = self.flow.poll('intent-hash')
        self.assertEqual(identity, (ISSUER, 'owner-a'))
        evidence = self.flow.consume('intent-hash')
        self.assertEqual(evidence['issuer'], ISSUER)
        self.assertEqual(len(evidence['token_hash']), 64)
        with self.assertRaises(WorldError):
            self.flow.consume('intent-hash')
        self.assertNotIn('device_code', self.flow.attempt)
        public = json.dumps(self.flow.public())
        for private in ('test-secret', 'private-device-code', 'owner-a', 'id_token'):
            self.assertNotIn(private, public)

    def test_request_authentication_and_no_extra_scopes(self):
        self.client.start()
        _, form, headers = self.provider.calls[-1]
        self.assertEqual(form, {'scope': 'openid'})
        self.assertTrue(headers['Authorization'].startswith('Basic '))
        self.assertNotIn('client_secret', form)
        self.client = WorldClient(Config('test-client', 'test-secret', 'client_secret_post'), self.provider)
        self.client.start()
        _, form, headers = self.provider.calls[-1]
        self.assertNotIn('Authorization', headers)
        self.assertEqual(form['client_secret'], 'test-secret')

    def test_missing_credentials(self):
        with self.assertRaises(WorldError):
            WorldClient(Config(), self.provider).start()
        self.assertEqual(self.provider.calls, [])

    def test_wrong_owner_denied_without_evidence(self):
        self.start()
        self.provider.subject = 'other-person'
        self.assertIsNone(self.flow.poll('intent-hash'))
        self.assertEqual(self.flow.error['code'], 'wrong_owner')
        self.assertIsNone(self.flow.evidence)

    def test_bad_token_claims(self):
        for override in ({'iss': 'https://wrong.example'}, {'aud': 'wrong-client'},
                         {'exp': self.now-1}, {'auth_time': self.now-60}, {'auth_time': self.now+60},
                         {'acr': 'wrong'}, {'amr': ['password']}, {'sub': ''}, {'jti': ''},
                         {'aud': ['test-client', 'other']}, {'azp': 'other'}):
            with self.subTest(override=override), self.assertRaises(WorldError):
                self.client.validate(self.provider.token(**override), self.now)

    def test_signature_and_algorithm_rejected(self):
        claims = dict(iss=ISSUER, sub='owner-a', aud='test-client', exp=self.now+300)
        for token in (jwt.encode(claims, 'not-a-real-secret-at-least-32-bytes', algorithm='HS256', headers={'kid': 'test-key'}),
                      jwt.encode(claims, rsa.generate_private_key(public_exponent=65537, key_size=2048),
                                 algorithm='RS256', headers={'kid': 'test-key'}), 'garbage'):
            with self.assertRaises(WorldError):
                self.client.validate(token, self.now)

    def test_provider_denial_expiry_and_unavailability(self):
        for code in ('access_denied', 'expired_token', 'invalid_grant', 'provider_error', 'unavailable'):
            with self.subTest(code=code):
                self.setUp()
                self.start()
                self.provider.error = OAuthError(code, 'Provider refused')
                self.flow.poll('intent-hash')
                self.assertEqual(self.flow.public()['status'], 'failed')
                self.assertIsNone(self.flow.evidence)
                self.assertNotIn('device_code', self.flow.attempt)

    def test_poll_interval_pending_and_slow_down(self):
        self.flow.start('handoff', 'intent-hash')
        count = len(self.provider.calls)
        self.flow.poll('intent-hash')
        self.assertEqual(len(self.provider.calls), count)
        self.now += 5
        self.provider.error = OAuthError('authorization_pending', 'Waiting')
        self.flow.poll('intent-hash')
        self.assertEqual(self.flow.public()['status'], 'pending')
        self.now += 5
        self.provider.error = OAuthError('slow_down', 'Wait longer')
        self.flow.poll('intent-hash')
        self.assertEqual(self.flow.attempt['interval'], 10)
        count = len(self.provider.calls)
        self.now += 5
        self.flow.poll('intent-hash')
        self.assertEqual(len(self.provider.calls), count)

    def test_cancellation_and_expiry_prevent_late_poll(self):
        self.start()
        self.flow.cancel()
        count = len(self.provider.calls)
        self.flow.poll('intent-hash')
        self.assertEqual(len(self.provider.calls), count)
        self.assertIsNone(self.flow.evidence)
        self.flow.start('handoff', 'intent-hash', deadline=self.now + 10)
        self.now += 10
        self.flow.poll('intent-hash')
        self.assertEqual(self.flow.error['code'], 'expired')

    def test_intent_change_and_evidence_expiry(self):
        self.start()
        self.flow.poll('changed-intent')
        self.assertEqual(self.flow.error['code'], 'intent_changed')
        self.flow.start('handoff', 'intent-hash', deadline=self.now + 10)
        self.now += 5
        self.flow.poll('intent-hash')
        self.now += 5
        with self.assertRaises(WorldError):
            self.flow.consume('intent-hash')

    def test_discovery_cannot_redirect_secrets(self):
        def malicious(*args):
            return dict(issuer=ISSUER, device_authorization_endpoint='https://evil.example/device')
        with self.assertRaises(WorldError):
            WorldClient(Config('test-client', 'test-secret'), malicious).start()


if __name__ == '__main__':
    unittest.main()
