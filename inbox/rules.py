from pr_watch import ci_summary

ORDER = ['CI_FAILED', 'OPEN_THREADS', 'CHANGES_REQUESTED', 'NEW_FEEDBACK', 'HEAD_CHANGED',
         'AUTHOR_ACTIVITY', 'INSUFFICIENT_DATA', 'NO_ACTION']
THREAD_LIMIT = 'Thread resolution is unavailable in REST mode; comments do not establish resolved threads.'


def ci_state(data):
    return ci_summary(latest_checks(data['checks']), data['statuses'])


def latest_checks(checks):

    latest = {}
    for c in checks:
        key = (c.get('app', {}).get('id'), c['name'])
        if key not in latest or c['id'] > latest[key]['id']:
            latest[key] = c
    return list(latest.values())


def decisions(reviews):
    latest = {}
    for r in sorted(reviews, key=lambda r: r['id']):
        if r['state'] in {'APPROVED', 'CHANGES_REQUESTED', 'DISMISSED'}:
            actor = (r.get('user') or {}).get('login')
            if actor:
                latest[actor] = r
    return list(latest.values())


def feedback(sources):
    events = []
    for source in ['comments', 'inline', 'reviews']:
        for x in sources.get(source, {}).get('data', []):
            if source == 'reviews' and x.get('state') == 'PENDING':
                continue
            user = x.get('user') or {}
            events.append({'id': f'{source}:{x["id"]}', 'kind': source,
                           'actor': user.get('login') or 'deleted-user',
                           'bot': user.get('type') == 'Bot',
                           'at': x.get('submitted_at') or x.get('created_at'),
                           'url': x.get('html_url'), 'text': (x.get('body') or '')[:1500],
                           'state': x.get('state')})
    return sorted(events, key=lambda e: (e['at'] or '', e['id']))


def reasons(row, now):
    sources = row['sources']
    pr = sources.get('pr', {}).get('data')
    if not pr:
        return []
    out = []

    def add(code, text, url=pr['html_url'], at=None, facts=None):
        out.append({'code': code, 'text': text, 'url': url,
                    'at': at or row['observed_at'], 'facts': facts or {}})

    ci = sources.get('ci')
    if ci and ci.get('head_sha') == pr['head']['sha'] and ci_state(ci['data']) == 'FAILING':
        bad = [c for c in latest_checks(ci['data']['checks']) if c.get('conclusion') in
               {'failure', 'cancelled', 'timed_out', 'action_required', 'stale', 'startup_failure'}]

        add('CI_FAILED', 'Head-commit checks have an unsuccessful result.',
            (bad[0].get('html_url') if bad else None) or pr['html_url'] + '/checks', facts={'head_sha': pr['head']['sha'],
                                            'observed_unsuccessful_runs': len(bad)})
    for thread in sources.get('threads', {}).get('data', []):
        if not thread['resolved']:
            add('OPEN_THREADS', f'Unresolved discussion in {thread["path"]}' + (f':{thread["line"]}' if thread.get('line') else '') + (' (outdated diff)' if thread.get('outdated') else ''), thread['url'], thread.get('at'), {'thread_id': thread['id']})
    reviews = sources.get('reviews', {}).get('data', [])
    for review in decisions(reviews):
        if review['state'] == 'CHANGES_REQUESTED':
            add('CHANGES_REQUESTED', f'{review["user"]["login"]} requested changes; this is their latest decision.',
                review['html_url'], review.get('submitted_at'), {'review_id': review['id']})
    for event in row['events']:
        if event['seq'] <= row['seen_seq']:
            continue
        if event['kind'] in {'comments', 'inline', 'reviews'}:
            if event['actor'].casefold() != pr['user']['login'].casefold():
                add('NEW_FEEDBACK', f'New {"bot " if event.get("bot") else ""}feedback from {event["actor"]}. A response may be useful.',
                    event['url'], event['at'], {'event_id': event['id'], 'bot': event.get('bot', False), 'actor': event['actor']})
            else:
                add('AUTHOR_ACTIVITY', 'New activity by the PR author; this does not prove feedback is addressed.',
                    event['url'], event['at'], {'event_id': event['id']})
        elif event['kind'] == 'head':
            add('HEAD_CHANGED', 'New head commit since the last successful PR observation. Recheck earlier review feedback.',
                event['url'], event['at'], {'head_sha': pr['head']['sha']})
    missing = [s for s in ['pr', 'ci', 'reviews', 'comments', 'inline'] if s not in sources or s in row['errors']]
    if ci and ci.get('head_sha') != pr['head']['sha'] and 'ci' not in missing:
        missing.append('ci for current head')
    for extra in ['threads', 'commits']:
        if extra in row['errors']:
            missing.append(extra)
    if missing:
        add('INSUFFICIENT_DATA', 'Some sources are missing or stale: ' + ', '.join(missing), facts={'sources': missing})
    if not out:
        add('NO_ACTION', 'No attention signal in the observed sources. ' + (THREAD_LIMIT if 'threads' not in sources else 'Review threads were retrieved; no merge-readiness decision is implied.'))
    return sorted(out, key=lambda r: ORDER.index(r['code']))
