"""Serial REST synchronization with conditional requests and explicit cooldowns."""
import copy
import datetime as dt
import email.utils
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pr_watch import APIError, GitHub
from .store import utcnow


class TrustedRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urllib.parse.urlsplit(newurl)
        if parsed.scheme != 'https' or parsed.netloc != 'api.github.com':
            raise APIError('Refused redirect outside the GitHub API')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class Client(GitHub):
    def __init__(self, token=None):
        super().__init__(token)
        self.cache = {}
        self.retry_at = 0
        self.opener = urllib.request.build_opener(TrustedRedirect())

    def get(self, path, **params):
        if time.time() < self.retry_at:
            raise APIError('API cooldown; next attempt ' + dt.datetime.fromtimestamp(self.retry_at, dt.timezone.utc).isoformat())
        if not path.startswith('/') or path.startswith('//'):
            raise APIError('Invalid API path')
        url = 'https://api.github.com' + path + ('?' + urllib.parse.urlencode(params) if params else '')
        headers = {'Accept': 'application/vnd.github+json', 'User-Agent': 'contributor-inbox',
                   'X-GitHub-Api-Version': '2022-11-28'}
        if self.token:
            headers['Authorization'] = 'Bearer ' + self.token
        if url in self.cache:
            headers['If-None-Match'] = self.cache[url][0]
        try:
            with self.opener.open(urllib.request.Request(url, headers=headers), timeout=20) as response:
                data = json.load(response)
                if response.headers.get('ETag'):
                    if len(self.cache) >= 500:
                        self.cache.pop(next(iter(self.cache)))
                    self.cache[url] = (response.headers['ETag'], data)
                return copy.deepcopy(data)
        except urllib.error.HTTPError as exc:
            if exc.code == 304 and url in self.cache:
                return copy.deepcopy(self.cache[url][1])
            if exc.code in (403, 429):
                retry = exc.headers.get('Retry-After', '')
                try:
                    wait = float(retry)
                except ValueError:
                    try:
                        wait = email.utils.parsedate_to_datetime(retry).timestamp() - time.time()
                    except (ValueError, TypeError):
                        wait = 60
                try:
                    reset = float(exc.headers.get('X-RateLimit-Reset', 0)) if exc.headers.get('X-RateLimit-Remaining') == '0' else 0
                except ValueError:
                    reset = 0
                self.retry_at = max(time.time() + max(wait, 60), reset)
                raise APIError(f'GitHub HTTP {exc.code}; permissions or rate limit. Next attempt after ' +
                               dt.datetime.fromtimestamp(self.retry_at, dt.timezone.utc).isoformat()) from None
            raise APIError(f'GitHub HTTP {exc.code}') from None
        except (urllib.error.URLError, TimeoutError, ValueError, OSError):
            raise APIError('GitHub unavailable or returned an invalid response; last successful data retained') from None


def compact(items):
    # Store only the event fields the application needs.
    return [{k: x.get(k) for k in ['id', 'state', 'submitted_at', 'created_at', 'updated_at',
                                  'html_url', 'commit_id']} |
            {'body': (x.get('body') or '')[:1500],
             'user': {k: (x.get('user') or {}).get(k) for k in ['login', 'type']}}
            for x in items]


def fetch_ci(api, root, sha):
    checks = api.pages(f'{root}/commits/{sha}/check-runs', key='check_runs', filter='latest')
    # Exclude check output/logs and provider payloads from persistent state.
    checks = [{k: c.get(k) for k in ['id', 'name', 'status', 'conclusion', 'html_url']} |
              {'app': {'id': (c.get('app') or {}).get('id')}} for c in checks]
    statuses = api.get(f'{root}/commits/{sha}/status')
    return {'checks': checks, 'statuses': {k: statuses[k] for k in ['state', 'total_count']}}


def synchronize(store, api, username, limit=20):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]{0,38}', username):
        raise ValueError('Enter a valid GitHub username')
    username = username.lower()
    status = {'started_at': utcnow(), 'finished_at': None, 'warnings': [], 'first_sync': not bool(store.rows(username))}
    refreshed_prs = set()
    store.setting('username', username)
    try:
        api.get('/users/' + username)
        search = api.get('/search/issues', q=f'is:pr is:open author:{username}',
                         sort='updated', order='desc', per_page=100)
        items = search['items']
        # Additional search pages are fetched only if the configured cap needs them.
        for page in range(2, min(10, (min(search['total_count'], limit) + 99) // 100) + 1):
            result = api.get('/search/issues', q=f'is:pr is:open author:{username}',
                             sort='updated', order='desc', per_page=100, page=page)
            items.extend(result['items'])
            if result.get('incomplete_results'):
                status['warnings'].append('Search results are incomplete')
        if search.get('incomplete_results') or search['total_count'] > limit:
            status['warnings'].append(f'Search is incomplete or limited to {limit} PRs; previously tracked PRs are checked individually')
        keys = []
        for item in items[:limit]:
            repo = item['repository_url'].removeprefix('https://api.github.com/repos/')
            if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo):
                raise APIError('Unexpected repository identifier')
            keys.append(f'{repo}#{int(item["number"])}')
        for row in store.rows(username):
            pr = row['sources'].get('pr', {}).get('data', {})
            if pr.get('state') == 'open' and row['key'] not in keys:
                keys.append(row['key'])
        for key in keys:
            repo, number = key.rsplit('#', 1)
            root = f'/repos/{repo}'
            try:
                raw = api.get(f'{root}/pulls/{number}')
                pr = {k: raw[k] for k in ['title', 'html_url', 'draft', 'state', 'merged', 'updated_at', 'number']}
                pr['user'] = {'login': raw['user']['login']}
                pr['head'] = {'sha': raw['head']['sha']}
                store.save_source(username, key, 'pr', pr)
                refreshed_prs.add(key)
            except APIError as exc:
                store.save_source(username, key, 'pr', error=exc)
                status['warnings'].append(key + ': ' + str(exc))
                if getattr(api, 'retry_at', 0) > time.time():
                    break
                continue
            sha = pr['head']['sha']
            sources = [
                ('ci', lambda: fetch_ci(api, root, sha)),
                ('reviews', lambda: compact(api.pages(f'{root}/pulls/{number}/reviews'))),
                ('comments', lambda: compact(api.pages(f'{root}/issues/{number}/comments'))),
                ('inline', lambda: compact(api.pages(f'{root}/pulls/{number}/comments')))]
            for source, fetch in sources:
                try:
                    store.save_source(username, key, source, fetch(), head_sha=sha if source == 'ci' else None)
                except APIError as exc:
                    store.save_source(username, key, source, error=exc)
                    status['warnings'].append(key + ' ' + source + ': ' + str(exc))
            if getattr(api, 'retry_at', 0) > time.time():
                break
    except APIError as exc:
        status['warnings'].append(str(exc))
    if status['warnings']:
        for row in store.rows(username):
            pr = row['sources'].get('pr', {}).get('data', {})
            if pr.get('state') == 'open' and row['key'] not in refreshed_prs and 'pr' not in row['errors']:
                store.save_source(username, row['key'], 'pr', error='Not refreshed in this update; last successful snapshot retained')
    status['finished_at'] = utcnow()
    status['retry_at'] = dt.datetime.fromtimestamp(api.retry_at, dt.timezone.utc).isoformat() if getattr(api, 'retry_at', 0) > time.time() else None
    store.setting('sync:' + username, status)
    return status
