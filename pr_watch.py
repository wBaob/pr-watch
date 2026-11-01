import argparse
import datetime
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request


class APIError(Exception):
    pass


class GitHub:
    def __init__(self, token=None):
        self.token = token

    def get(self, path, **params):
        url = 'https://api.github.com' + path
        if params:
            url += '?' + urllib.parse.urlencode(params)
        headers = {'Accept': 'application/vnd.github+json',
                   'User-Agent': 'pr-watch', 'X-GitHub-Api-Version': '2022-11-28'}
        if self.token:
            headers['Authorization'] = 'Bearer ' + self.token
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            hint = ''
            if exc.code in (403, 429):
                hint = '; check permissions or API rate limits (try later or use GITHUB_TOKEN)'
            raise APIError(f'GitHub HTTP {exc.code}{hint}') from None
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            raise APIError('GitHub connection or response error') from exc

    def pages(self, path, key=None, **params):
        result = []
        for page in range(1, 101):
            data = self.get(path, per_page=100, page=page, **params)
            items = data[key] if key else data
            result.extend(items)
            if len(items) < 100:
                return result
        raise APIError('Pagination safety limit reached; result is incomplete')


def ci_summary(checks, statuses):

    failed = {'failure', 'cancelled', 'timed_out', 'action_required', 'stale', 'startup_failure'}
    if any(c.get('conclusion') in failed for c in checks) or statuses['state'] == 'failure':
        return 'FAILING'
    if any(c['status'] != 'completed' for c in checks):
        return 'PENDING'
    if statuses['total_count'] and statuses['state'] == 'pending':
        return 'PENDING'
    if any(c.get('conclusion') not in {'success', 'neutral', 'skipped'} for c in checks):
        return 'UNKNOWN'
    if not checks and not statuses['total_count']:
        return 'NO_CHECKS'
    return 'PASSING'


def review_summary(reviews):

    latest = {}
    for review in reviews:
        state = review['state']
        if state in {'APPROVED', 'CHANGES_REQUESTED', 'DISMISSED'}:
            user = (review.get('user') or {}).get('login')
            if user:
                latest[user] = state
    return {'approvals': sum(s == 'APPROVED' for s in latest.values()),
            'changes_requested': sum(s == 'CHANGES_REQUESTED' for s in latest.values())}


def inspect_pr(api, repo, number):
    root = f'/repos/{repo}'
    pr = api.get(f'{root}/pulls/{number}')
    row = {'repository': repo, 'number': number, 'title': pr['title'],
           'url': pr['html_url'], 'draft': pr['draft'], 'state': pr['state'],
           'head_sha': pr['head']['sha'], 'ci': 'UNKNOWN', 'reviews': None, 'warnings': []}
    sha = pr['head']['sha']
    try:
        checks = api.pages(f'{root}/commits/{sha}/check-runs', key='check_runs', filter='latest')
        statuses = api.get(f'{root}/commits/{sha}/status')
        row['ci'] = ci_summary(checks, statuses)
    except APIError as exc:
        row['warnings'].append('CI: ' + str(exc))
    try:
        row['reviews'] = review_summary(api.pages(f'{root}/pulls/{number}/reviews'))
    except APIError as exc:
        row['warnings'].append('Reviews: ' + str(exc))
    return row


def positive(value):
    n = int(value)
    if not 1 <= n <= 100:
        raise argparse.ArgumentTypeError('must be between 1 and 100')
    return n


def main(argv=None):
    parser = argparse.ArgumentParser(description='Contributor Inbox: local GitHub activity monitor')
    parser.add_argument('username', help='GitHub author to monitor')
    parser.add_argument('--limit', type=positive, default=10, help='maximum PRs, 1-100 (default: 10)')
    parser.add_argument('--json', action='store_true', help='emit a JSON report')
    args = parser.parse_args(argv)
    if not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})', args.username):
        parser.error('invalid GitHub username')
    api = GitHub(os.environ.get('GITHUB_TOKEN'))
    try:
        api.get('/users/' + args.username)
        search = api.get('/search/issues', q=f'is:pr is:open author:{args.username}',
                         sort='updated', order='desc', per_page=args.limit)
        report = {'author': args.username, 'observed_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  'total_open': search['total_count'], 'pull_requests': [], 'warnings': []}
        if search.get('incomplete_results'):
            report['warnings'].append('GitHub returned incomplete search results')
        if search['total_count'] > len(search['items']):
            report['warnings'].append(f'Showing the {len(search["items"])} most recently updated PRs; use --limit up to 100')
        for item in search['items']:
            repo = item['repository_url'].removeprefix('https://api.github.com/repos/')
            if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo):
                raise APIError('Unexpected repository identifier')
            try:
                report['pull_requests'].append(inspect_pr(api, repo, item['number']))
            except APIError as exc:
                report['warnings'].append(f'{repo}#{item["number"]}: {exc}')
    except APIError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=True))
    else:
        print(f'PR Watch | {args.username} | {report["observed_at"]}')
        print(f'Open PRs: {report["total_open"]}')
        for row in report['pull_requests']:
            reviews = row['reviews']
            review = ('reviews unavailable' if reviews is None else
                      f'{reviews["approvals"]} approval(s), {reviews["changes_requested"]} change request(s)')
            title = ''.join(c if c.isprintable() else ' ' for c in row['title'])
            print(f'\n{row["repository"]}#{row["number"]}: {title}')
            print(f'  CI: {row["ci"]} | {review}' + (' | DRAFT' if row['draft'] else ''))
            print('  ' + row['url'])
            for warning in row['warnings']:
                print('  Warning: ' + warning)
        for warning in report['warnings']:
            print('Warning: ' + warning)
    return 2 if report['warnings'] or any(r['warnings'] for r in report['pull_requests']) else 0


if __name__ == '__main__':
    sys.exit(main())
