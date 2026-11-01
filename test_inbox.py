import copy
import datetime as dt
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from inbox.demo import seed, USERNAME
from inbox.rules import ci_state, reasons
from inbox.server import Application, handler_for
from inbox.store import Store
from inbox.sync import Client, synchronize, TrustedRedirect
from pr_watch import APIError


class InboxTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / 'test.sqlite3')
        seed(self.store)
        self.key = self.store.rows(USERNAME)[0]['key']

    def row(self):
        return next(r for r in self.store.view(USERNAME) if r['key'] == self.key)

    def test_baseline_repeat_and_restart_do_not_generate_changes(self):
        first = self.row()
        self.assertEqual(first['events'], [])
        for source, value in first['sources'].items():
            self.store.save_source(USERNAME, self.key, source, value['data'], head_sha=value.get('head_sha'))
        again = Store(self.store.path).view(USERNAME)
        self.assertFalse(next(r for r in again if r['key'] == self.key)['unread'])

    def test_new_feedback_seen_and_future_feedback(self):
        comment = {'id': 1, 'created_at': '2026-01-01T00:00:00Z', 'body': 'Review this',
                   'html_url': 'https://github.com/example/repo/issues/1#issuecomment-1',
                   'user': {'login': 'reviewer', 'type': 'User'}}
        self.store.save_source(USERNAME, self.key, 'comments', [comment])
        self.assertIn('NEW_FEEDBACK', [r['code'] for r in self.row()['reasons']])
        self.store.action(USERNAME, self.key, 'seen')
        self.assertNotIn('NEW_FEEDBACK', [r['code'] for r in self.row()['reasons']])
        second = dict(comment, id=2)
        self.store.save_source(USERNAME, self.key, 'comments', [comment, second])
        self.assertTrue(self.row()['unread'])
        self.assertEqual(len(self.row()['events']), 2)

    def test_own_comment_is_not_external_feedback(self):
        self.store.save_source(USERNAME, self.key, 'comments', [{'id': 1, 'created_at': '2026-01-01T00:00:00Z',
            'html_url': 'https://github.com/example/repo/pull/1', 'body': 'Done', 'user': {'login': USERNAME}}])
        codes = [r['code'] for r in self.row()['reasons']]
        self.assertNotIn('NEW_FEEDBACK', codes)
        self.assertIn('AUTHOR_ACTIVITY', codes)

    def test_failure_keeps_baseline_and_stale_is_explicit(self):
        original = self.row()['sources']['comments']
        self.store.save_source(USERNAME, self.key, 'comments', error='offline')
        self.assertEqual(self.row()['sources']['comments'], original)
        self.assertIn('INSUFFICIENT_DATA', [r['code'] for r in self.row()['reasons']])
        self.store.save_source(USERNAME, self.key, 'comments', [])
        self.assertFalse(self.row()['unread'])

    def test_failed_first_source_success_is_baseline(self):
        self.store.save_source(USERNAME, self.key, 'extra', error='offline')
        self.assertNotIn('extra', self.row()['sources'])

    def test_snooze_persists_and_cancels(self):
        future = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)).isoformat()
        self.store.action(USERNAME, self.key, 'snooze', future)
        row = next(r for r in Store(self.store.path).view(USERNAME) if r['key'] == self.key)
        self.assertTrue(row['snoozed'])
        self.store.action(USERNAME, self.key, 'unsnooze')
        self.assertFalse(self.row()['snoozed'])
        with self.assertRaises(ValueError):
            self.store.action(USERNAME, self.key, 'snooze', '2020-01-01T00:00:00+00:00')

    def test_head_change_makes_old_ci_unknown(self):
        pr = copy.deepcopy(self.row()['sources']['pr']['data'])
        pr['head']['sha'] = 'newhead'
        self.store.save_source(USERNAME, self.key, 'pr', pr)
        self.assertEqual(self.row()['ci'], 'UNKNOWN')
        self.assertIn('HEAD_CHANGED', [r['code'] for r in self.row()['reasons']])
        self.assertIn('INSUFFICIENT_DATA', [r['code'] for r in self.row()['reasons']])

    def test_ci_rerun_supersedes_failure(self):
        data = {'checks': [{'id': 1, 'name': 'test', 'app': {'id': 5}, 'status': 'completed', 'conclusion': 'failure'},
                           {'id': 2, 'name': 'test', 'app': {'id': 5}, 'status': 'completed', 'conclusion': 'success'}],
                'statuses': {'state': 'pending', 'total_count': 0}}
        self.assertEqual(ci_state(data), 'PASSING')
        data['statuses'] = {'state': 'failure', 'total_count': 1}
        self.assertEqual(ci_state(data), 'FAILING')

    def test_missing_search_result_is_checked_directly(self):
        api = Client()
        paths = []
        def get(path, **params):
            paths.append(path)
            if path.startswith('/users/'):
                return {}
            if path == '/search/issues':
                return {'items': [], 'total_count': 0}
            raise APIError('GitHub HTTP 404')
        with patch.object(api, 'get', side_effect=get):
            synchronize(self.store, api, USERNAME)
        self.assertIn('/repos/' + self.key.split('#')[0] + '/pulls/' + self.key.split('#')[1], paths)
        self.assertEqual(self.row()['sources']['pr']['data']['state'], 'open')
        self.assertIn('pr', self.row()['errors'])

    def test_rate_limit_no_request_during_cooldown(self):
        api = Client()
        error = urllib.error.HTTPError('https://api.github.com/user', 429, 'rate limited', {'Retry-After': '120'}, None)
        with patch.object(api.opener, 'open', side_effect=error) as opener:
            for _ in range(2):
                with self.assertRaises(APIError):
                    api.get('/users/example')
            self.assertEqual(opener.call_count, 1)
        self.assertGreater(api.retry_at, dt.datetime.now().timestamp() + 100)

    def test_conditional_cache(self):
        api = Client()
        url = 'https://api.github.com/users/example'
        api.cache[url] = ('etag', {'login': 'example'})
        with patch.object(api.opener, 'open', side_effect=urllib.error.HTTPError(url, 304, 'unchanged', {}, None)) as opener:
            self.assertEqual(api.get('/users/example'), {'login': 'example'})
            self.assertEqual(opener.call_args.args[0].get_header('If-none-match'), 'etag')

    def test_redirect_does_not_leak_authorization(self):
        with self.assertRaises(APIError):
            TrustedRedirect().redirect_request(urllib.request.Request('https://api.github.com/user'), None, 302, '', {}, 'https://evil.example')

    def test_global_offline_marks_saved_open_rows_as_stale(self):
        api = Client()
        with patch.object(api, 'get', side_effect=APIError('offline')):
            status = synchronize(self.store, api, USERNAME)
        self.assertTrue(status['warnings'])
        self.assertIn('INSUFFICIENT_DATA', [r['code'] for r in self.row()['reasons']])

    def test_snooze_expiry_and_merge_journal(self):
        future = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)).isoformat()
        self.store.action(USERNAME, self.key, 'snooze', future)
        with patch('inbox.store.utcnow', return_value='2099-01-01T00:00:00+00:00'):
            self.assertFalse(self.row()['snoozed'])
        pr = copy.deepcopy(self.row()['sources']['pr']['data'])
        pr.update(state='closed', merged=True)
        self.store.save_source(USERNAME, self.key, 'pr', pr)
        self.assertEqual({e['kind'] for e in self.row()['events']}, {'state', 'merged'})

    def test_bot_and_deleted_user_feedback_are_explicit(self):
        self.store.save_source(USERNAME, self.key, 'comments', [
            {'id': 1, 'html_url': 'https://github.com/example/repo/pull/1', 'created_at': '2026-01-01T00:00:00Z',
             'user': {'login': 'helper[bot]', 'type': 'Bot'}, 'body': 'Suggestion'},
            {'id': 2, 'html_url': 'https://github.com/example/repo/pull/1', 'created_at': '2026-01-01T00:00:00Z',
             'user': {'login': None}, 'body': 'Suggestion'}])
        feedback = [r for r in self.row()['reasons'] if r['code'] == 'NEW_FEEDBACK']
        self.assertEqual(len(feedback), 2)
        self.assertTrue(feedback[0]['facts']['bot'])
        self.assertIn('deleted-user', feedback[1]['text'])

    def test_demo_scenarios_are_separate_and_cover_missing_data(self):
        original = len(self.store.rows(USERNAME))
        seed(self.store, 'empty')
        self.assertEqual(self.store.rows('demo-empty'), [])
        seed(self.store, 'rate-limit')
        self.assertTrue(self.store.setting('sync:demo-rate-limit')['retry_at'])
        self.assertTrue(all(r['ci'] == 'UNKNOWN' for r in self.store.view('demo-rate-limit')))
        seed(self.store, 'closed')
        self.assertTrue(all(r['sources']['pr']['data']['state'] == 'closed' for r in self.store.view('demo-closed')))
        self.assertEqual(len(self.store.rows(USERNAME)), original)


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = Application(Store(Path(self.temp.name) / 'demo.sqlite3'), demo=True)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), handler_for(self.app))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def post(self, path, body, headers=None):
        headers = headers or {'Origin': self.base, 'X-Inbox-CSRF': self.app.csrf, 'Content-Type': 'application/json'}
        return urllib.request.urlopen(urllib.request.Request(self.base + path, data=json.dumps(body).encode(), headers=headers))

    def test_cross_origin_and_untrusted_host_rejected(self):
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.post('/api/sync', {}, {'Origin': 'https://evil.example', 'Content-Type': 'application/json'})
        self.assertEqual(error.exception.code, 403)
        with self.assertRaises(urllib.error.HTTPError):
            urllib.request.urlopen(urllib.request.Request(self.base + '/api/state', headers={'Host': 'evil.example'}))

    def test_live_demo_flow_and_duplicate_sync(self):
        with urllib.request.urlopen(self.base + '/api/state') as response:
            state = json.load(response)
        self.assertTrue(state['demo'])
        key = state['rows'][0]['key']
        with self.post('/api/action', {'key': key, 'action': 'seen'}) as response:
            self.assertEqual(response.status, 200)
        self.app.lock.acquire()
        try:
            with self.assertRaises(urllib.error.HTTPError) as error:
                self.post('/api/sync', {})
            self.assertEqual(error.exception.code, 409)
        finally:
            self.app.lock.release()
        with self.post('/api/sync', {}) as response:
            self.assertEqual(response.status, 200)

    def test_security_headers_and_static_paths(self):
        with urllib.request.urlopen(self.base) as response:
            self.assertIn("script-src 'self'", response.headers['Content-Security-Policy'])
            self.assertIn(b'Contributor Inbox', response.read())
        with self.assertRaises(urllib.error.HTTPError):
            urllib.request.urlopen(self.base + '/../../.git/config')


if __name__ == '__main__':
    unittest.main()
