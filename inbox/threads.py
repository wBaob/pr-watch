import datetime as dt
import json
import time
import urllib.error
import urllib.request
from pr_watch import APIError

QUERY = '''query($owner:String!,$name:String!,$number:Int!,$cursor:String){
repository(owner:$owner,name:$name){pullRequest(number:$number){
reviewThreads(first:100,after:$cursor){pageInfo{hasNextPage endCursor}
nodes{id isResolved isOutdated path line comments(first:1){nodes{url body createdAt author{login}}}}}}}}'''


def fetch_threads(api, repo, number):
    if not api.token:
        raise APIError('Review threads require a server-side GITHUB_TOKEN')
    owner, name = repo.split('/')
    cursor, result = None, []
    for _ in range(100):
        if time.time() < api.retry_at:
            raise APIError('GraphQL paused until ' + dt.datetime.fromtimestamp(api.retry_at, dt.timezone.utc).isoformat())
        request = urllib.request.Request('https://api.github.com/graphql',
            data=json.dumps({'query': QUERY, 'variables': {'owner': owner, 'name': name, 'number': int(number), 'cursor': cursor}}).encode(),
            headers={'Authorization': 'Bearer ' + api.token, 'Content-Type': 'application/json', 'User-Agent': 'contributor-inbox'})
        try:
            with api.opener.open(request, timeout=20) as response:
                payload = json.load(response)
            if payload.get('errors'):
                if any(e.get('type') == 'RATE_LIMITED' for e in payload['errors']):
                    api.retry_at = time.time() + 3600
                raise APIError('GraphQL returned incomplete data or denied access; previous threads retained')
            connection = payload['data']['repository']['pullRequest']['reviewThreads']
            for node in connection['nodes']:
                comment = next(iter(node['comments']['nodes']), {})
                result.append({'id': node['id'], 'resolved': node['isResolved'], 'outdated': node['isOutdated'],
                               'path': node['path'], 'line': node['line'], 'url': comment.get('url', ''),
                               'body': comment.get('body', '')[:1500], 'at': comment.get('createdAt'),
                               'actor': (comment.get('author') or {}).get('login', 'deleted-user')})
            page = connection['pageInfo']
            if not page['hasNextPage']:
                return result
            if not page['endCursor'] or page['endCursor'] == cursor:
                raise APIError('Invalid review-thread cursor')
            cursor = page['endCursor']
        except urllib.error.HTTPError as exc:
            if exc.code in (403, 429):
                try:
                    wait = float(exc.headers.get('Retry-After', '60'))
                except ValueError:
                    wait = 3600
                try:
                    reset = float(exc.headers.get('X-RateLimit-Reset', 0)) if exc.headers.get('X-RateLimit-Remaining') == '0' else 0
                except ValueError:
                    reset = 0
                api.retry_at = max(time.time() + max(60, wait), reset)
            raise APIError(f'GraphQL HTTP {exc.code}; previous threads retained') from None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError, TypeError):
            raise APIError('Review threads unavailable; previous threads retained') from None
    raise APIError('Review-thread pagination limit reached')
