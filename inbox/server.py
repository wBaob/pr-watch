"""Loopback-only HTTP service. Run with python -m inbox.server [--demo]."""
import argparse
import json
import mimetypes
import os
import secrets
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from .demo import seed, USERNAME
from .store import Store
from .sync import Client, synchronize

WEB = Path(__file__).resolve().parent.parent / 'web'


class Application:
    def __init__(self, store, demo=False, limit=20):
        self.store, self.demo, self.limit = store, demo, limit
        self.client = Client(os.environ.get('GITHUB_TOKEN'))
        self.csrf = secrets.token_urlsafe(32)
        self.lock = threading.Lock()
        if demo and store.setting('demo_step') is None:
            seed(store)

    def state(self):
        username = self.store.setting('username') or ''
        return {'username': username, 'demo': self.demo, 'demo_scenario': self.store.setting('demo_scenario'), 'csrf': self.csrf, 'busy': self.lock.locked(),
                'rows': self.store.view(username), 'sync': self.store.setting('sync:' + username)}


def handler_for(app):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass  # Do not log GitHub metadata or query strings.

        def send(self, code, data, content_type='application/json; charset=utf-8'):
            payload = json.dumps(data).encode() if content_type.startswith('application/json') else data
            self.send_response(code)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(payload)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            self.end_headers()
            self.wfile.write(payload)

        def trusted_host(self):
            return self.headers.get('Host') in {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}

        def do_GET(self):
            if not self.trusted_host():
                return self.send(403, {'error': 'Untrusted host'})
            path = urllib.parse.urlsplit(self.path).path
            if path == '/api/state':
                return self.send(200, app.state())
            assets = {'/': 'index.html', '/app.js': 'app.js', '/style.css': 'style.css', '/favicon.svg': 'favicon.svg'}
            if path not in assets:
                return self.send(404, {'error': 'Not found'})
            file = WEB / assets[path]
            self.send(200, file.read_bytes(), mimetypes.guess_type(file)[0] or 'application/octet-stream')

        def do_POST(self):
            origin = self.headers.get('Origin')
            if (not self.trusted_host() or origin != 'http://' + self.headers.get('Host', '') or
                    self.headers.get('X-Inbox-CSRF') != app.csrf):
                return self.send(403, {'error': 'Same-origin request with session token required'})
            if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                return self.send(415, {'error': 'JSON required'})
            try:
                size = int(self.headers.get('Content-Length', 0))
                if not 0 < size <= 4096:
                    return self.send(413, {'error': 'Invalid request size'})
                body = json.loads(self.rfile.read(size))
                if not isinstance(body, dict):
                    raise ValueError('Expected an object')
                if self.path == '/api/sync':
                    if not app.lock.acquire(blocking=False):
                        return self.send(409, {'error': 'An update is already running'})
                    try:
                        result = seed(app.store, body.get('scenario')) if app.demo else synchronize(app.store, app.client, body.get('username', ''), app.limit)
                    finally:
                        app.lock.release()
                    return self.send(200, result)
                if self.path == '/api/action':
                    # Serialize local actions with sync so a seen marker cannot race with a snapshot.
                    if not app.lock.acquire(blocking=False):
                        return self.send(409, {'error': 'Wait for the update to finish'})
                    try:
                        owner = app.store.setting('username') or ''
                        app.store.action(owner, body['key'], body['action'], body.get('until'))
                    finally:
                        app.lock.release()
                    return self.send(200, {'ok': True})
                return self.send(404, {'error': 'Not found'})
            except (ValueError, TypeError, KeyError):
                self.send(400, {'error': 'Invalid input: check username, action or future snooze date'})

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--demo', action='store_true', help='synthetic data; no network')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--db', type=Path, help='SQLite database path')
    parser.add_argument('--limit', type=int, choices=range(1, 1001), default=20, metavar='1..1000')
    args = parser.parse_args()
    default_db = Path(__file__).resolve().parent.parent / '.data' / ('demo.sqlite3' if args.demo else 'inbox.sqlite3')
    app = Application(Store(args.db or default_db), args.demo, args.limit)
    server = ThreadingHTTPServer(('127.0.0.1', args.port), handler_for(app))
    server.daemon_threads = True
    print(f'Contributor Inbox: http://127.0.0.1:{server.server_port}' + (' (synthetic demo)' if args.demo else ''), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
