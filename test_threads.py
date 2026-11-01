import io
import json
import unittest
from unittest.mock import patch
from inbox.sync import Client
from inbox.threads import fetch_threads
from pr_watch import APIError


class Response(io.BytesIO):
    def __init__(self, payload):
        super().__init__(json.dumps(payload).encode())


class ThreadsTests(unittest.TestCase):
    def test_pagination_keeps_resolved_and_unresolved_threads(self):
        def payload(next_page, resolved):
            return {'data': {'repository': {'pullRequest': {'reviewThreads': {
                'pageInfo': {'hasNextPage': next_page, 'endCursor': 'next'},
                'nodes': [{'id': str(resolved), 'isResolved': resolved, 'isOutdated': False,
                           'path': 'a.py', 'line': 1, 'comments': {'nodes': [{'url': 'https://github.com/o/r/pull/1', 'body': 'Review', 'createdAt': '2026-01-01T00:00:00Z', 'author': None}]}}]}}}}}
        api = Client('placeholder')
        with patch.object(api.opener, 'open', side_effect=[Response(payload(True, False)), Response(payload(False, True))]) as call:
            result = fetch_threads(api, 'o/r', 1)
        self.assertEqual([r['resolved'] for r in result], [False, True])
        self.assertEqual(json.loads(call.call_args.args[0].data)['variables']['cursor'], 'next')

    def test_partial_graphql_data_is_not_accepted(self):
        api = Client('placeholder')
        with patch.object(api.opener, 'open', return_value=Response({'errors': [{'type': 'RATE_LIMITED'}], 'data': {}})):
            with self.assertRaises(APIError):
                fetch_threads(api, 'o/r', 1)
        self.assertGreater(api.retry_at, 0)

    def test_no_token_never_makes_request(self):
        api = Client()
        with patch.object(api.opener, 'open') as call:
            with self.assertRaises(APIError):
                fetch_threads(api, 'o/r', 1)
            call.assert_not_called()
