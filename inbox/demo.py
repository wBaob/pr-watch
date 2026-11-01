"""Deterministic fictional data. Separate database, no network requests."""
from .store import utcnow

USERNAME = 'demo-contributor'


SCENARIOS = {'standard', 'empty', 'offline', 'rate-limit', 'closed', 'long-title'}


def seed(store, scenario=None):
    scenario = scenario or store.setting('demo_scenario') or 'standard'
    if scenario not in SCENARIOS:
        raise ValueError('Unknown demo scenario')
    store.setting('demo_scenario', scenario)
    username = USERNAME if scenario == 'standard' else 'demo-' + scenario
    step = store.setting('demo_step:' + scenario) or 0
    store.setting('username', username)
    now = utcnow()
    titles = ['Preserve focus when the command palette closes',
              'Handle expired sessions in the upload queue',
              'Document the migration to the new config format',
              'Improve keyboard navigation in nested menus',
              'Keep the last successful cache on network failure']
    for i, title in enumerate(titles if scenario != 'empty' else [], 1):
        key = f'example-workspace/{"interface" if i % 2 else "toolkit"}#{100+i}'
        repo, number = key.split('#')
        url = f'https://github.com/{repo}/pull/{number}'
        sha = f'demo{i}-' + ('new' if step and i == 4 else 'baseline')
        if scenario == 'long-title' and i == 1:
            title = 'Preserve backwards compatibility for deeply nested configuration values: ' + 'extended-context-' * 15
        pr = {'title': title, 'html_url': url, 'number': int(number), 'draft': i == 3,
              'state': 'closed' if scenario == 'closed' else 'open', 'merged': scenario == 'closed' and i % 2 == 0, 'updated_at': now,
              'head': {'sha': sha}, 'user': {'login': username}}
        store.save_source(username, key, 'pr', pr)
        checks = [{'id': i, 'name': 'unit-tests', 'app': {'id': 1}, 'html_url': url + '/checks',
                   'status': 'in_progress' if i == 3 else 'completed',
                   'conclusion': 'failure' if i == 1 else ('success' if i != 3 else None)}]
        store.save_source(username, key, 'ci', {'checks': checks, 'statuses': {'state': 'pending', 'total_count': 0}}, head_sha=sha)
        review = {'id': i, 'state': 'CHANGES_REQUESTED' if i == 2 else 'APPROVED',
                  'submitted_at': now, 'html_url': url + '#pullrequestreview-1',
                  'user': {'login': 'sample-maintainer', 'type': 'User'}, 'body': 'Please keep the existing public behavior covered by a regression test.'}
        store.save_source(username, key, 'reviews', [review] if i == 2 else [])
        comments = []
        if step and i in (3, 5):
            comments = [{'id': 900 + step, 'html_url': url + '#issuecomment-demo', 'created_at': now,
                         'user': {'login': 'review-helper[bot]' if i == 3 else 'sample-reviewer', 'type': 'Bot' if i == 3 else 'User'},
                         'body': 'Could you include an example for the offline case?'}]
        store.save_source(username, key, 'comments', comments)
        store.save_source(username, key, 'inline', [])
        if i == 5:
            store.save_source(username, key, 'inline', error='Synthetic permission denial: HTTP 403')
        if scenario in {'offline', 'rate-limit'}:
            for source in ['pr', 'ci', 'reviews', 'comments', 'inline']:
                store.save_source(username, key, source, error='Synthetic ' + scenario + ': last snapshot retained')
    store.setting('demo_step:' + scenario, step + 1)
    store.setting('demo_step', step + 1)
    status = {'started_at': now, 'finished_at': utcnow(), 'first_sync': step == 0,
              'warnings': ['Synthetic partial-data example: one inline-comment source is unavailable.'], 'retry_at': None}
    if scenario in {'offline', 'rate-limit'}:
        status['warnings'] = ['Synthetic ' + scenario + '. Saved example data is stale.']
        if scenario == 'rate-limit':
            import datetime as dt
            status['retry_at'] = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=2)).isoformat()
    elif scenario == 'empty':
        status['warnings'] = []
    store.setting('sync:' + username, status)
    return status
