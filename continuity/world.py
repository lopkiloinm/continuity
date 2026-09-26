"""World sandbox OIDC device grant. No mock provider or client-supplied proofs.

Contract: https://sandbox.auth.world.org/mcp, public `oidc` and `step-up` guides.
Only the sandbox issuer is supported. Device codes, tokens and subjects stay here.
"""
import base64
import hashlib
import json
import math
import os
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus, urlencode, urlparse
from urllib.request import Request, HTTPRedirectHandler, build_opener

import jwt

ISSUER = 'https://sandbox.auth.world.org'
ACR = 'https://world.org/oidc/acr/orb-v3'


class WorldError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class OAuthError(WorldError):
    pass


def load_env(path):
    """Read literal KEY=value settings; never execute or print .env contents."""
    if not Path(path).exists():
        return
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        key, separator, value = line.partition('=')
        if separator and key.strip().startswith('WORLD_'):
            os.environ.setdefault(key.strip(), value.strip().strip('\"\''))


@dataclass(frozen=True)
class Config:
    client_id: str = ''
    client_secret: str = ''
    auth_method: str = 'client_secret_basic'

    @classmethod
    def from_env(cls):
        return cls(os.getenv('WORLD_CLIENT_ID', ''), os.getenv('WORLD_CLIENT_SECRET', ''),
                   os.getenv('WORLD_AUTH_METHOD', 'client_secret_basic'))

    @property
    def configured(self):
        return bool(self.client_id and self.client_secret and
                    self.auth_method in ('client_secret_basic', 'client_secret_post'))


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def read_json(url, form=None, headers=None):
    request = Request(url, urlencode(form).encode() if form is not None else None,
                      headers or {'Accept': 'application/json'})
    try:
        with build_opener(NoRedirect).open(request, timeout=10) as response:
            raw = response.read(262145)
            if len(raw) > 262144:
                raise WorldError('invalid_response', 'World returned an oversized response.')
            result = json.loads(raw)
            if not isinstance(result, dict):
                raise ValueError()
            return result
    except HTTPError as error:
        try:
            code = json.loads(error.read(4096)).get('error', 'provider_error')
        except (ValueError, AttributeError):
            code = 'provider_error'
        # Never forward provider descriptions, credentials, or raw response bodies.
        known = ('authorization_pending', 'slow_down', 'access_denied', 'expired_token',
                 'invalid_grant', 'invalid_client', 'invalid_scope')
        code = code if code in known else 'provider_error'
        raise OAuthError(code, 'World could not complete verification (%s).' % code) from None
    except (URLError, TimeoutError, OSError):
        raise WorldError('unavailable', 'World is unavailable. No authority was granted; retry explicitly.') from None
    except (ValueError, UnicodeError):
        raise WorldError('invalid_response', 'World returned an invalid response.') from None


class WorldClient:
    def __init__(self, config, transport=read_json, clock=time.time):
        self.config, self.transport, self.clock = config, transport, clock
        self.metadata = None
        self.jwks = None
        self.jwks_at = 0

    def discovery(self):
        if not self.config.configured:
            raise WorldError('not_configured', 'Register a sandbox OIDC client and add its credentials to .env first.')
        if self.metadata is None:
            data = self.transport(ISSUER + '/.well-known/openid-configuration')
            if data.get('issuer') != ISSUER:
                raise WorldError('invalid_discovery', 'World issuer mismatch.')
            for key in ('device_authorization_endpoint', 'token_endpoint', 'jwks_uri'):
                url = urlparse(data.get(key, ''))
                if url.scheme != 'https' or url.netloc != 'sandbox.auth.world.org' or url.fragment:
                    raise WorldError('invalid_discovery', 'Unexpected World endpoint.')
            if self.config.auth_method not in data.get('token_endpoint_auth_methods_supported', []):
                raise WorldError('invalid_discovery', 'Configured client authentication is not supported.')
            self.metadata = data
        return self.metadata

    def post(self, endpoint, fields):
        headers = {'Content-Type': 'application/x-www-form-urlencoded', 'Accept': 'application/json'}
        if self.config.auth_method == 'client_secret_basic':
            credentials = quote_plus(self.config.client_id) + ':' + quote_plus(self.config.client_secret)
            headers['Authorization'] = 'Basic ' + base64.b64encode(credentials.encode()).decode()
        else:
            fields = dict(fields, client_id=self.config.client_id, client_secret=self.config.client_secret)
        return self.transport(endpoint, fields, headers)

    def start(self):
        return self.post(self.discovery()['device_authorization_endpoint'], {'scope': 'openid'})

    def poll(self, device_code):
        return self.post(self.discovery()['token_endpoint'], {
            'grant_type': 'urn:ietf:params:oauth:grant-type:device_code', 'device_code': device_code})

    def validate(self, token, started_at):
        """Validate signature and claims before any identity reaches the app."""
        try:
            header = jwt.get_unverified_header(token)
            if header.get('alg') != 'RS256' or not isinstance(header.get('kid'), str):
                raise ValueError()
            if self.jwks is None or self.clock() - self.jwks_at >= 300:
                self.jwks = self.transport(self.discovery()['jwks_uri'])
                self.jwks_at = self.clock()
            keys = [key for key in self.jwks.get('keys', []) if key.get('kid') == header['kid']]
            # At most one bounded refresh per validation when keys rotate.
            if not keys:
                self.jwks = self.transport(self.discovery()['jwks_uri'])
                self.jwks_at = self.clock()
                keys = [key for key in self.jwks.get('keys', []) if key.get('kid') == header['kid']]
            if len(keys) != 1 or keys[0].get('kty') != 'RSA' or keys[0].get('use', 'sig') != 'sig':
                raise ValueError()
            key = jwt.PyJWK.from_dict(keys[0], algorithm='RS256').key
            if key.key_size < 2048:
                raise ValueError()
            claims = jwt.decode(token, key, algorithms=['RS256'], issuer=ISSUER,
                                audience=self.config.client_id, options={'require': [
                                    'iss', 'sub', 'aud', 'exp', 'iat', 'jti', 'auth_time', 'acr', 'amr']})
            now = self.clock()
            for name in ('exp', 'iat', 'auth_time'):
                if type(claims[name]) not in (int, float) or not math.isfinite(claims[name]):
                    raise ValueError()
            if claims['acr'] != ACR or claims['amr'] != ['pop']:
                raise ValueError()
            if not started_at - 5 <= claims['auth_time'] <= now + 5 or now - claims['auth_time'] > 300:
                raise ValueError()
            if not isinstance(claims['sub'], str) or not claims['sub'] or not isinstance(claims['jti'], str) or not claims['jti']:
                raise ValueError()
            aud = claims['aud']
            if (isinstance(aud, list) and len(aud) > 1 and claims.get('azp') != self.config.client_id) or (
                    'azp' in claims and claims['azp'] != self.config.client_id):
                raise ValueError()
            return claims
        except (jwt.PyJWTError, ValueError, TypeError, KeyError, AttributeError):
            raise WorldError('invalid_identity', 'World identity signature, claims, or freshness could not be validated.') from None


class WorldFlow:
    """One browser session's private, single-use device attempt."""
    def __init__(self, client, clock=time.time):
        self.client, self.clock = client, clock
        self.attempt = None
        self.evidence = None
        self.error = None

    def start(self, purpose, binding, owner=None, deadline=None):
        if self.attempt and self.attempt['status'] == 'pending' and self.clock() < self.attempt['expires_at']:
            raise WorldError('already_pending', 'Finish or cancel the current World verification first.')
        self.attempt = self.evidence = self.error = None
        started = self.clock()
        result = self.client.start()
        try:
            for key in ('device_code', 'user_code', 'verification_uri_complete'):
                if not isinstance(result[key], str) or not result[key]:
                    raise ValueError()
            uri = urlparse(result['verification_uri_complete'])
            if uri.scheme != 'https' or uri.netloc != 'sandbox.auth.world.org':
                raise ValueError()
            interval, lifetime = result.get('interval', 5), result['expires_in']
            if type(interval) is not int or type(lifetime) is not int or not 1 <= interval <= 300 or not 1 <= lifetime <= 1200:
                raise ValueError()
        except (KeyError, TypeError, ValueError):
            raise WorldError('invalid_response', 'World returned an invalid device request.') from None
        self.attempt = {'id': secrets.token_urlsafe(24), 'purpose': purpose, 'binding': binding,
                        'owner': owner, 'device_code': result['device_code'], 'user_code': result['user_code'],
                        'verification_url': result['verification_uri_complete'], 'started_at': started,
                        'expires_at': min(started + lifetime, deadline or started + lifetime),
                        'interval': interval, 'next_poll': self.clock() + interval, 'status': 'pending'}

    def cancel(self):
        if self.attempt:
            self.attempt['status'] = 'cancelled'
            self.attempt.pop('device_code', None)
        self.evidence = None

    def fail(self, error):
        self.attempt['status'] = 'failed'
        self.attempt.pop('device_code', None)
        self.evidence = None
        self.error = {'code': error.code, 'message': str(error)}

    def poll(self, binding):
        attempt = self.attempt
        if not attempt or attempt['status'] != 'pending':
            return None
        if binding != attempt['binding']:
            self.fail(WorldError('intent_changed', 'The pending job or approval changed. Start verification again.'))
            return None
        if self.clock() >= attempt['expires_at']:
            self.fail(WorldError('expired', 'Verification expired. No authority was granted.'))
            return None
        if self.clock() < attempt['next_poll']:
            return None
        attempt['next_poll'] = self.clock() + attempt['interval']
        try:
            result = self.client.poll(attempt['device_code'])
            claims = self.client.validate(result.get('id_token'), attempt['started_at'])
            if self.clock() >= attempt['expires_at']:
                raise WorldError('expired', 'Verification expired before completion.')
            identity = (claims['iss'], claims['sub'])
            if attempt['owner'] is not None and identity != attempt['owner']:
                raise WorldError('wrong_owner', 'Verify with the same World identity that owns this job.')
            attempt['status'] = 'verified'
            attempt.pop('device_code', None)
            self.evidence = {'binding': binding, 'auth_time': claims['auth_time'],
                             'expires_at': min(attempt['expires_at'], claims['exp'], claims['auth_time'] + 300),
                             'issuer': claims['iss'], 'acr': claims['acr'],
                             'token_hash': hashlib.sha256(result['id_token'].encode()).hexdigest()}
            return identity
        except OAuthError as error:
            if error.code == 'authorization_pending':
                return None
            if error.code == 'slow_down':
                attempt['interval'] += 5
                attempt['next_poll'] = self.clock() + attempt['interval']
                return None
            self.fail(error)
        except WorldError as error:
            self.fail(error)
        return None

    def consume(self, binding):
        if not self.evidence or self.evidence['binding'] != binding or self.clock() >= self.evidence['expires_at']:
            raise WorldError('verification_required', 'Fresh verification of this exact handoff is required.')
        evidence, self.evidence = self.evidence, None
        self.attempt['status'] = 'consumed'
        return evidence

    def public(self):
        attempt = self.attempt
        if attempt and attempt['status'] == 'pending' and self.clock() >= attempt['expires_at']:
            self.fail(WorldError('expired', 'Verification expired. No authority was granted.'))
        result = {'configured': self.client.config.configured, 'environment': 'World sandbox (test identities)',
                  'status': attempt['status'] if attempt else 'idle', 'error': self.error,
                  'can_approve': bool(self.evidence and self.clock() < self.evidence['expires_at'])}
        if attempt:
            result.update({key: attempt[key] for key in ('purpose', 'user_code', 'verification_url', 'expires_at')})
            result['poll_after'] = max(1, math.ceil(attempt['next_poll'] - self.clock()))
        return result
