"""Loopback demo with per-browser jobs and backend-validated World OIDC."""
import csv
import io
import json
import os
import re
import secrets
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse

from continuity.engine import Job, Rejected, digest
from continuity.world import Config, WorldClient, WorldFlow, WorldError, load_env
from continuity.storage import RedisStore, StorageError, SessionBusy, RateLimited

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / 'static'
load_env(ROOT / '.env')
world_client = WorldClient(Config.from_env())
sessions = {}


class Session:
    def __init__(self):
        self.job = Job()
        self.owner = None
        self.world = WorldFlow(world_client)
        self.touched = time.time()

    def new_job(self):
        self.world.cancel()
        self.job = Job()
        self.world = WorldFlow(world_client)
        if self.owner is not None:
            self.job.record('owner_retained', 'New job belongs to the verified owner of this browser session. Handoffs still require fresh verification.')

    def snapshot(self):
        data = self.job.snapshot()
        data['world'] = self.world.public()
        data['world']['owner_connected'] = self.owner is not None
        data['world']['can_approve'] = bool(data['world']['can_approve'] and self.world.attempt['purpose'] == 'handoff')
        return data

    def binding(self):
        if self.world.attempt and self.world.attempt['purpose'] == 'handoff':
            if self.job.state != 'awaiting_approval':
                return None
            return digest(self.job.approval)
        return self.job.id if self.job.state == 'ready' else None

    def serialize(self):
        return {'version': 1, 'job': {k: v for k, v in vars(self.job).items() if k != 'clock'},
                'owner': self.owner, 'touched': self.touched, 'world': {
                    'attempt': self.world.attempt, 'evidence': self.world.evidence, 'error': self.world.error}}

    @classmethod
    def restore(cls, data):
        if data.get('version') != 1:
            raise StorageError('Unsupported saved session version.')
        session = cls()
        session.job.__dict__.update(data['job'])
        # Migrate already-saved, unstarted jobs without discarding verified owners.
        if session.job.state == 'ready':
            session.job.expires_at = None
        session.owner = tuple(data['owner']) if data['owner'] else None
        for key in ('attempt', 'evidence', 'error'):
            setattr(session.world, key, data['world'][key])
        if session.world.attempt and session.world.attempt['owner']:
            session.world.attempt['owner'] = tuple(session.world.attempt['owner'])
        session.touched = time.time()
        return session


class Handler(BaseHTTPRequestHandler):
    @property
    def deployed(self):
        return os.getenv('VERCEL') == '1'

    def dispatch(self, method):
        self.new_cookie = None
        self.loaded_session = None
        self.store = None
        self.lease = None
        try:
            method()
        except StorageError as error:
            self.send(429 if isinstance(error, RateLimited) else 409 if isinstance(error, SessionBusy) else 503,
                      {'error': str(error)})
        finally:
            if self.lease:
                try:
                    self.store.release(self.sid, self.lease)
                except StorageError:
                    pass  # Lease expires; no unfenced commit is possible.
                self.lease = None

    def log_message(self, format, *args):
        # Avoid logging OAuth codes or callback query strings if routes change later.
        pass

    def get_session(self):
        now = time.time()
        for key in list(sessions):
            if now - sessions[key].touched > 3600:
                del sessions[key]
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get('Cookie', ''))
            sid = cookie['continuity_session'].value if 'continuity_session' in cookie else None
        except Exception:
            sid = None
        if self.deployed:
            self.store = RedisStore.from_env()
            if not sid or not re.fullmatch(r'[A-Za-z0-9_-]{43}', sid):
                sid = secrets.token_urlsafe(32)
                self.new_cookie = sid
            self.sid = sid
            self.lease, data = self.store.acquire(sid)
            self.loaded_session = Session.restore(data) if data else Session()
            # Refresh the browser cookie alongside the Redis TTL.
            self.new_cookie = sid
            return self.loaded_session
        if sid not in sessions:
            sid = secrets.token_urlsafe(32)
            sessions[sid] = Session()
            self.new_cookie = sid
        sessions[sid].touched = now
        return sessions[sid]

    def send(self, status, data, content_type='application/json'):
        if getattr(self, 'lease', None):
            lease, self.lease = self.lease, None
            self.store.commit(self.sid, lease, self.loaded_session.serialize())
        body = json.dumps(data).encode() if content_type == 'application/json' else data
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        if getattr(self, 'new_cookie', None):
            self.send_header('Set-Cookie', 'continuity_session=%s; HttpOnly; SameSite=Strict; Path=/; Max-Age=3600%s' % (self.new_cookie, '; Secure' if self.deployed else ''))
        self.end_headers()
        self.wfile.write(body)

    def valid_origin(self):
        if self.deployed:
            host = self.headers.get('Host', '')
            allowed = {os.getenv('APP_ORIGIN', '').removeprefix('https://'),
                       os.getenv('VERCEL_URL', ''), os.getenv('VERCEL_PROJECT_PRODUCTION_URL', '')}
            return bool(host and host in allowed and self.headers.get('Origin', 'https://' + host) == 'https://' + host)
        expected = '127.0.0.1:%d' % self.server.server_port
        return self.headers.get('Host') == expected and self.headers.get('Origin', 'http://' + expected) == 'http://' + expected

    def do_GET(self):
        self.dispatch(self.get)

    def get(self):
        if not self.valid_origin():
            return self.send(403, {'error': 'Use the configured application origin.'})
        path = urlparse(self.path).path
        if path == '/api/health':
            storage = 'memory'
            if self.deployed:
                store = RedisStore.from_env()
                if store.command('PING') != 'PONG':
                    raise StorageError('Shared session storage is unavailable.')
                storage = 'redis'
            return self.send(200, {'status': 'ok', 'runtime': 'python', 'storage': storage,
                                   'world_configured': world_client.config.configured})
        if path == '/auth/world/callback':
            return self.send(200, b'<!doctype html><html lang="en"><title>Continuity World ID</title><h1>Continuity</h1><p>This app uses World ID device verification. Return to the app to connect your identity.</p><a href="/">Open Continuity</a></html>', 'text/html; charset=utf-8')
        files = {'/': ('index.html', 'text/html; charset=utf-8'),
                 '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                 '/style.css': ('style.css', 'text/css; charset=utf-8')}
        if path in files:
            name, mime = files[path]
            return self.send(200, (STATIC / name).read_bytes(), mime)
        if path not in ('/api/job', '/api/receipt', '/api/result.csv'):
            return self.send(404, {'error': 'Not found'})
        session = self.get_session()
        job = session.job
        if path in ('/api/job', '/api/receipt'):
            data = session.snapshot() if path == '/api/job' else job.snapshot()
            if self.deployed:
                data['limitations'] = [x for x in data['limitations'] if not x.startswith('In-memory')]
                data['storage'] = 'Encrypted Redis session, one-hour idle expiry'
            return self.send(200, data)
        if path == '/api/result.csv':
            if job.state != 'completed':
                return self.send(409, {'error': 'Complete the job before exporting.'})
            buffer = io.StringIO()
            writer = csv.DictWriter(buffer, fieldnames=['record_id', 'source', 'description', 'worker'])
            writer.writeheader()
            writer.writerows(job.rows)
            return self.send(200, buffer.getvalue().encode(), 'text/csv; charset=utf-8')
        self.send(404, {'error': 'Not found'})

    def do_POST(self):
        self.dispatch(self.post)

    def post(self):
        if not self.valid_origin():
            return self.send(403, {'error': 'Use the configured application origin.'})
        if self.headers.get('Content-Type') != 'application/json':
            return self.send(415, {'error': 'JSON required'})
        session = self.get_session()
        job = session.job
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 4096:
                raise ValueError('Expected a small JSON object')
            data = json.loads(self.rfile.read(size))
            if not isinstance(data, dict):
                raise ValueError('Expected a JSON object')
            if self.path == '/api/reset':
                session.new_job()
            elif self.path == '/api/world/start':
                if self.deployed:
                    ip = self.headers.get('x-vercel-forwarded-for', self.client_address[0])
                    self.store.limit('world:' + ip)
                purpose = data.get('purpose')
                if purpose == 'owner':
                    job.require('ready')
                    if session.owner is not None:
                        raise Rejected('This job already has an owner.')
                    session.world.start('owner', job.id)
                elif purpose == 'handoff':
                    job.require('awaiting_approval')
                    if session.owner is None:
                        raise Rejected('Connect the job owner first.')
                    if data.get('approval_hash') != digest(job.approval):
                        raise Rejected('Approval intent mismatch.')
                    if time.time() >= job.approval['expires_at']:
                        raise Rejected('Approval expired. Reset to create a new job.')
                    session.world.start('handoff', digest(job.approval), session.owner, job.approval['expires_at'])
                    job.record('world_requested', 'Fresh World sandbox verification requested for this handoff.')
                else:
                    raise ValueError('Unknown verification purpose')
            elif self.path == '/api/world/poll':
                identity = session.world.poll(session.binding())
                if identity is not None:
                    if session.world.attempt['purpose'] == 'owner':
                        session.owner = identity
                        session.world.consume(job.id)
                        job.record('owner_connected', 'Job owner established by backend-validated World sandbox identity.')
                    else:
                        job.record('world_verified', 'Same owner freshly verified by World sandbox. Explicit handoff consent still required.')
                elif session.world.error and session.world.attempt['purpose'] == 'handoff' and job.state == 'awaiting_approval':
                    job.decide(False, digest(job.approval))
                    job.record('world_rejected', session.world.error['message'])
            elif self.path == '/api/world/cancel':
                session.world.cancel()
                if job.state == 'awaiting_approval':
                    job.decide(False, digest(job.approval))
            elif self.path == '/api/start':
                if session.owner is None:
                    raise Rejected('Connect the job owner with World ID first.')
                job.start()
            elif self.path == '/api/fail':
                job.fail()
            elif self.path == '/api/evaluate':
                job.evaluate(data.get('scenario'))
            elif self.path == '/api/decide':
                if type(data.get('approved')) is not bool:
                    raise ValueError('approved must be a boolean')
                job.require('awaiting_approval')
                if data.get('approval_hash') != digest(job.approval):
                    raise Rejected('Approval intent mismatch.')
                if data['approved']:
                    evidence = session.world.consume(digest(job.approval))
                    job.decide(True, data['approval_hash'], evidence)
                else:
                    session.world.cancel()
                    job.decide(False, data['approval_hash'])
            elif self.path == '/api/resume':
                job.resume()
            else:
                return self.send(404, {'error': 'Unknown action'})
            self.send(200, session.snapshot())
        except WorldError as error:
            self.send(503 if error.code in ('not_configured', 'unavailable') else 409,
                      {'error': str(error), 'code': error.code})
        except Rejected as error:
            self.send(409, {'error': str(error)})
        except (ValueError, TypeError) as error:
            self.send(400, {'error': str(error)})


def main():
    server = HTTPServer(('127.0.0.1', 8000), Handler)
    print('Continuity: http://127.0.0.1:8000', flush=True)
    print('World sandbox: ' + ('configured' if world_client.config.configured else 'add credentials to .env'), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
