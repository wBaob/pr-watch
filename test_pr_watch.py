import unittest
from unittest.mock import patch
from pr_watch import APIError, GitHub, ci_summary, inspect_pr, review_summary


class MonitorTests(unittest.TestCase):
    def test_no_status_is_not_pending_when_checks_pass(self):
        self.assertEqual(ci_summary([{'status': 'completed', 'conclusion': 'success'}],
                                    {'state': 'pending', 'total_count': 0}), 'PASSING')

    def test_no_checks_is_not_success(self):
        self.assertEqual(ci_summary([], {'state': 'pending', 'total_count': 0}), 'NO_CHECKS')

    def test_failure_overrides_pending(self):
        self.assertEqual(ci_summary([{'status': 'completed', 'conclusion': 'failure'},
                                     {'status': 'queued'}], {'state': 'pending', 'total_count': 1}), 'FAILING')

    def test_pending_and_unknown(self):
        self.assertEqual(ci_summary([{'status': 'queued'}], {'state': 'pending', 'total_count': 0}), 'PENDING')
        self.assertEqual(ci_summary([{'status': 'completed', 'conclusion': None}],
                                    {'state': 'pending', 'total_count': 0}), 'UNKNOWN')

    def test_comments_preserve_decision_but_later_approval_replaces_changes(self):
        reviews = [{'user': {'login': 'a'}, 'state': state}
                   for state in ['CHANGES_REQUESTED', 'COMMENTED', 'APPROVED', 'COMMENTED']]
        self.assertEqual(review_summary(reviews), {'approvals': 1, 'changes_requested': 0})
        reviews.append({'user': {'login': 'a'}, 'state': 'DISMISSED'})
        self.assertEqual(review_summary(reviews), {'approvals': 0, 'changes_requested': 0})

    def test_pagination(self):
        api = GitHub()
        with patch.object(api, 'get', side_effect=[{'check_runs': [1] * 100}, {'check_runs': [2]}]) as get:
            self.assertEqual(len(api.pages('/checks', key='check_runs')), 101)
            self.assertEqual(get.call_args.kwargs['page'], 2)

    def test_ci_denied_does_not_hide_reviews_or_claim_success(self):
        api = GitHub()
        pr = {'title': 'Test', 'html_url': 'https://github.com/o/r/pull/1',
              'draft': False, 'state': 'open', 'head': {'sha': 'abc'}}
        with patch.object(api, 'get', return_value=pr), patch.object(
                api, 'pages', side_effect=[APIError('GitHub HTTP 403'), []]):
            row = inspect_pr(api, 'o/r', 1)
        self.assertEqual(row['ci'], 'UNKNOWN')
        self.assertIsNotNone(row['reviews'])
        self.assertTrue(row['warnings'])


if __name__ == '__main__':
    unittest.main()
