"""Encrypted shared sessions and fenced request leases over Upstash Redis REST."""
import hashlib
import json
import os
import secrets
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import Request, build_opener

from cryptography.fernet import Fernet, InvalidToken
from continuity.world import NoRedirect


class StorageError(Exception):
    pass


class SessionBusy(StorageError):
    pass


class RateLimited(StorageError):
    pass


# Lua is atomic. A request that outlives its lease cannot overwrite newer state.
ACQUIRE = """
if not redis.call('SET', KEYS[2], ARGV[1], 'NX', 'EX', 90) then return {0} end
return {1, redis.call('GET', KEYS[1]) or ''}
"""
COMMIT = """
if redis.call('GET', KEYS[2]) ~= ARGV[1] then return 0 end
redis.call('SET', KEYS[1], ARGV[2], 'EX', 3600)
redis.call('DEL', KEYS[2])
return 1
"""
RELEASE = """
if redis.call('GET', KEYS[1]) == ARGV[1] then return redis.call('DEL', KEYS[1]) end
return 0
"""
RATE = """
local n = redis.call('INCR', KEYS[1])
if n == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
return n
"""


class RedisStore:
    def __init__(self, url, token, encryption_key, command=None):
        parsed = urlparse(url)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or not token or not encryption_key:
            raise StorageError('Shared session storage is not configured.')
        self.url, self.token = url.rstrip('/'), token
        try:
            self.cipher = Fernet(encryption_key.encode())
        except (ValueError, TypeError):
            raise StorageError('Session encryption key is invalid.') from None
        self.command = command or self._command

    @classmethod
    def from_env(cls):
        return cls(os.getenv('UPSTASH_REDIS_REST_URL') or os.getenv('KV_REST_API_URL', ''),
                   os.getenv('UPSTASH_REDIS_REST_TOKEN') or os.getenv('KV_REST_API_TOKEN', ''),
                   os.getenv('SESSION_ENCRYPTION_KEY', ''))

    def _command(self, *args):
        req = Request(self.url, json.dumps(args).encode(), {
            'Authorization': 'Bearer ' + self.token, 'Content-Type': 'application/json'})
        try:
            with build_opener(NoRedirect).open(req, timeout=8) as response:
                result = json.loads(response.read(262144))
            if not isinstance(result, dict) or 'error' in result or 'result' not in result:
                raise ValueError()
            return result['result']
        except (URLError, OSError, ValueError):
            raise StorageError('Shared session storage is unavailable. No action was confirmed.') from None

    def keys(self, sid):
        key = 'continuity:session:' + hashlib.sha256(sid.encode()).hexdigest()
        return key, key + ':lease'

    def acquire(self, sid):
        key, lock = self.keys(sid)
        lease = secrets.token_urlsafe(24)
        result = self.command('EVAL', ACQUIRE, 2, key, lock, lease)
        if not result or result[0] != 1:
            raise SessionBusy('Another request is updating this session. Try again shortly.')
        try:
            payload = json.loads(self.cipher.decrypt(result[1].encode())) if result[1] else None
            return lease, payload
        except (InvalidToken, ValueError, TypeError):
            self.release(sid, lease)
            raise StorageError('Session cannot be recovered. Clear this site’s cookie and reconnect.') from None

    def commit(self, sid, lease, payload):
        key, lock = self.keys(sid)
        encrypted = self.cipher.encrypt(json.dumps(payload, separators=(',', ':')).encode()).decode()
        if self.command('EVAL', COMMIT, 2, key, lock, lease, encrypted) != 1:
            raise SessionBusy('The request lease expired. Reload before trying again.')

    def release(self, sid, lease):
        self.command('EVAL', RELEASE, 1, self.keys(sid)[1], lease)

    def limit(self, fingerprint, limit=8, seconds=600):
        key = 'continuity:limit:' + hashlib.sha256(fingerprint.encode()).hexdigest()
        if self.command('EVAL', RATE, 1, key, seconds) > limit:
            raise RateLimited('Too many verification starts. Wait ten minutes before trying again.')
