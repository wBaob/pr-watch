"""SQLite v1 storage; atomic per-source observations and local state."""
import contextlib
import datetime as dt
import json
import sqlite3
from pathlib import Path
from .rules import feedback, reasons, ci_state


def utcnow():
    return dt.datetime.now(dt.timezone.utc).isoformat()


class Store:
    def __init__(self, path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            version = db.execute('PRAGMA user_version').fetchone()[0]
            if version not in (0, 1):
                raise RuntimeError('Unsupported database schema; use a compatible version or a new database')
            db.executescript('''
                CREATE TABLE IF NOT EXISTS prs (
                    owner TEXT NOT NULL, key TEXT NOT NULL, body TEXT NOT NULL,
                    PRIMARY KEY(owner,key));
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                PRAGMA user_version=1;
            ''')

    @contextlib.contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        try:
            with db:
                yield db
        finally:
            db.close()

    def setting(self, key, value=None):
        with self.connect() as db:
            if value is not None:
                db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)', (key, json.dumps(value)))
                return value
            row = db.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
            return json.loads(row[0]) if row else None

    def rows(self, owner):
        with self.connect() as db:
            return [json.loads(r[0]) for r in db.execute('SELECT body FROM prs WHERE owner=?', (owner.lower(),))]

    def save_source(self, owner, key, source, data=None, error=None, head_sha=None):
        now = utcnow()
        with self.connect() as db:
            found = db.execute('SELECT body FROM prs WHERE owner=? AND key=?', (owner.lower(), key)).fetchone()
            row = json.loads(found[0]) if found else {'key': key, 'sources': {}, 'errors': {}, 'events': [],
                         'seen_seq': 0, 'seq': 0, 'snoozed_until': None, 'observed_at': now}
            if error:
                row['errors'][source] = {'message': str(error), 'at': now}
            else:
                previous = row['sources'].get(source)
                new = {'data': data, 'observed_at': now}
                if head_sha:
                    new['head_sha'] = head_sha
                row['sources'][source] = new
                row['errors'].pop(source, None)
                row['observed_at'] = now
                changes = []
                if previous and source in {'comments', 'inline', 'reviews'}:
                    old_ids = {x['id'] for x in previous['data']}
                    changes = [e for e in feedback({source: new}) if int(e['id'].split(':')[1]) not in old_ids]
                    if source == 'reviews':
                        old = {x['id']: x for x in previous['data']}
                        for x in data:
                            if x['id'] in old and x.get('state') != old[x['id']].get('state'):
                                changes.append({'id': f'review-state:{x["id"]}:{x["state"]}', 'kind': 'review_state',
                                                'at': now, 'url': x['html_url'], 'text': 'Review decision changed to ' + x['state']})
                elif previous and source == 'pr':
                    for field, kind in [('head', 'head'), ('state', 'state'), ('merged', 'merged')]:
                        old = previous['data'][field]
                        val = data[field]
                        if field == 'head':
                            old, val = old['sha'], val['sha']
                        if old != val:
                            changes.append({'id': f'{kind}:{val}:{now}', 'kind': kind, 'at': data.get('updated_at') or now,
                                            'url': 'https://github.com/' + key.split('#')[0] + f'/commit/{val}' if kind == 'head' else data['html_url'],
                                            'text': f'{kind} changed: {old} → {val}'})
                elif previous and source == 'ci' and (previous.get('head_sha') != head_sha or ci_state(previous['data']) != ci_state(data)):
                    changes.append({'id': f'ci:{head_sha}:{now}', 'kind': 'ci', 'at': now,
                                    'url': key_url(key) + '/checks', 'text': f'CI observed: {ci_state(data)}'})
                known = {e['id'] for e in row['events']}
                for event in changes:
                    if event['id'] not in known:
                        row['seq'] += 1
                        event.update(seq=row['seq'], observed_at=now)
                        row['events'].append(event)
                        known.add(event['id'])
                # First success for each source is its baseline; never emits historical feedback.
            db.execute('INSERT OR REPLACE INTO prs VALUES (?,?,?)', (owner.lower(), key, json.dumps(row)))

    def action(self, owner, key, action, until=None):
        with self.connect() as db:
            found = db.execute('SELECT body FROM prs WHERE owner=? AND key=?', (owner.lower(), key)).fetchone()
            if not found:
                raise ValueError('PR not found')
            row = json.loads(found[0])
            if action == 'seen':
                row['seen_seq'] = row['seq']
            elif action == 'snooze':
                end = dt.datetime.fromisoformat(until)
                if end.tzinfo is None or not dt.datetime.now(dt.timezone.utc) < end <= dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=366):
                    raise ValueError('Choose a future timezone-aware snooze time within one year')
                row['snoozed_until'] = end.astimezone(dt.timezone.utc).isoformat()
            elif action == 'unsnooze':
                row['snoozed_until'] = None
            else:
                raise ValueError('Unknown action')
            db.execute('UPDATE prs SET body=? WHERE owner=? AND key=?', (json.dumps(row), owner.lower(), key))

    def view(self, owner):
        now = utcnow()
        rows = self.rows(owner)
        for row in rows:
            row['reasons'] = reasons(row, now)
            row['unread'] = row['seq'] > row['seen_seq']
            row['snoozed'] = bool(row['snoozed_until'] and row['snoozed_until'] > now)
            ci = row['sources'].get('ci')
            pr = row['sources'].get('pr', {}).get('data')
            row['ci'] = ci_state(ci['data']) if ci and pr and ci.get('head_sha') == pr['head']['sha'] and 'ci' not in row['errors'] else 'UNKNOWN'
            row['timeline'] = sorted(feedback(row['sources']) + [e for e in row['events'] if e['kind'] not in {'comments', 'inline', 'reviews'}],
                                     key=lambda e: e['at'] or '', reverse=True)
        return rows


def key_url(key):
    repo, number = key.rsplit('#', 1)
    return f'https://github.com/{repo}/pull/{number}'
