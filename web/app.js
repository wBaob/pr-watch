"use strict";
const $ = (id) => document.getElementById(id);
const input = (id) => $(id);
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const date = (v) => v ? new Date(v).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }) : 'Not observed';
const safeURL = (raw) => { try {
    const u = new URL(raw);
    return u.protocol === 'https:' && u.hostname === 'github.com' && !u.username && !u.password && !u.port ? u.href : '';
}
catch {
    return '';
} };
const link = (url, label) => safeURL(url) ? `<a href="${esc(safeURL(url))}" target="_blank" rel="noopener noreferrer">${esc(label)} ↗</a>` : `<span>${esc(label)} (link unavailable)</span>`;
const labels = { CI_FAILED: '× Checks unsuccessful', CHANGES_REQUESTED: '↺ Changes requested', NEW_FEEDBACK: '↳ New feedback', HEAD_CHANGED: '↑ New commits', AUTHOR_ACTIVITY: '↗ Author activity', INSUFFICIENT_DATA: '? Insufficient data', NO_ACTION: '✓ No attention signal' };
const order = Object.keys(labels);
let state, tab = 'active', busy = false, selected = null;
const dialog = $('detail');
async function request(path, body) {
    const response = await fetch(path, body ? { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Inbox-CSRF': state.csrf }, body: JSON.stringify(body) } : {});
    const data = await response.json();
    if (!response.ok)
        throw new Error(data.error || `Request failed (${response.status})`);
    return data;
}
function notice(message, warn = false) { $('notice').innerHTML = message ? `<div class="notice ${warn ? 'warn' : ''}">${esc(message)}</div>` : ''; }
async function load() {
    state = await request('/api/state');
    if (document.activeElement !== input('username'))
        input('username').value = state.username;
    input('username').readOnly = state.demo;
    $('demo-options').hidden = !state.demo;
    if (state.demo)
        input('scenario').value = state.demo_scenario || 'standard';
    $('mode').textContent = state.demo ? 'SYNTHETIC DEMO · NO NETWORK' : 'LOCAL · READ ONLY';
    const current = $('repo').value;
    const repos = [...new Set(state.rows.map(r => r.key.split('#')[0]))].sort();
    $('repo').innerHTML = '<option value="">All repositories</option>' + repos.map(r => `<option value="${esc(r)}">${esc(r)}</option>`).join('');
    $('repo').value = repos.includes(current) ? current : '';
    let warnings = state.sync?.warnings || [];
    const messages = [];
    if (state.demo)
        messages.push('Demo workspace · all names and pull requests below are fictional. Refresh introduces synthetic changes.');
    if (state.sync?.first_sync)
        messages.push('Baseline saved. Historical comments are not counted as new feedback.');
    messages.push(...warnings);
    if (state.sync?.retry_at)
        messages.push('Next API attempt: ' + date(state.sync.retry_at));
    notice(messages.join(' '), warnings.length > 0);
    $('updated').textContent = state.sync ? `Last update attempt: ${date(state.sync.finished_at)} · times shown in your local timezone` : 'Connect a username to get started.';
    render();
}
function prOf(row) { return row.sources.pr?.data; }
function badge(code) { return `<span class="badge ${code === 'CI_FAILED' ? 'bad' : code === 'INSUFFICIENT_DATA' || code === 'CHANGES_REQUESTED' ? 'warn' : ''}">${esc(labels[code] || code)}</span>`; }
function render() {
    const search = input('search').value.trim().toLowerCase(), repo = input('repo').value, reason = input('reason').value, draft = input('draft').value;
    const rows = state.rows.filter(row => {
        const pr = prOf(row);
        if (!pr)
            return false;
        if (tab === 'closed' ? pr.state === 'open' : pr.state !== 'open')
            return false;
        if (tab === 'snoozed' ? !row.snoozed : tab !== 'closed' && row.snoozed)
            return false;
        if (tab === 'unread' && !row.unread)
            return false;
        return (!search || (`${pr.title} ${row.key}`).toLowerCase().includes(search)) && (!repo || row.key.split('#')[0] === repo) && (!reason || row.reasons.some(r => r.code === reason)) && (!draft || (draft === 'draft') === pr.draft);
    }).sort((a, b) => order.indexOf(a.reasons[0]?.code) - order.indexOf(b.reasons[0]?.code) || Number(b.unread) - Number(a.unread) || b.observed_at.localeCompare(a.observed_at));
    $('count').textContent = String(rows.length);
    $('list').innerHTML = rows.length ? rows.map(row => {
        const pr = prOf(row), reason = row.reasons[0];
        return `<article class="pr"><span class="pr-symbol ${row.ci === 'FAILING' ? 'bad' : ''}" aria-hidden="true">⑂</span><div><div class="pr-meta"><span>${esc(row.key)}</span>${row.unread ? '<span class="unread" title="Changes since marked seen"></span>' : ''}${pr.draft ? '<span>Draft</span>' : ''}<span>by ${esc(pr.user.login)}</span><span>· ${esc(pr.state === 'closed' ? (pr.merged ? 'Merged' : 'Closed') : 'Open')}</span></div><button class="pr-title" data-detail="${esc(row.key)}">${esc(pr.title)}</button><div>${reason ? badge(reason.code) : ''} <span class="badge">CI: ${esc(row.ci)}</span></div><p class="pr-reason">${esc(reason?.text || 'No successful observation yet.')}</p><small>Observed ${esc(date(row.observed_at))}${row.snoozed ? ' · Snoozed until ' + esc(date(row.snoozed_until)) : ''}</small></div><div class="pr-side"><button data-detail="${esc(row.key)}">Details →</button><button data-action="seen" data-key="${esc(row.key)}" ${busy ? 'disabled' : ''}>Mark seen</button></div></article>`;
    }).join('') : `<div class="empty"><span class="empty-icon" aria-hidden="true">${tab === 'snoozed' ? '◷' : '↳'}</span><h3>${!state.username ? 'Make room for your next contribution' : tab === 'unread' ? 'You’re caught up' : 'Nothing in this view'}</h3><p>${!state.username ? 'Enter your GitHub username and refresh to build your first local snapshot.' : 'Try another view or clear your filters. Refresh to check for changes; no data updates in the background.'}</p></div>`;
    $('list').querySelectorAll('button[data-detail]').forEach(b => b.onclick = () => showDetail(b.dataset.detail));
    $('list').querySelectorAll('button[data-action]').forEach(b => b.onclick = () => action(b.dataset.key, 'seen'));
}
function showDetail(key) {
    selected = key;
    const row = state.rows.find(r => r.key === key), pr = row && prOf(row);
    if (!row || !pr)
        return;
    const localFuture = new Date(Date.now() + 86400000);
    localFuture.setMinutes(localFuture.getMinutes() - localFuture.getTimezoneOffset());
    $('detail-body').innerHTML = `<p class="pr-meta">${esc(row.key)} · ${esc(pr.user.login)} · ${esc(pr.state)}</p><h2 id="detail-title">${esc(pr.title)}</h2>${link(pr.html_url, 'Open on GitHub')}<p>Head <code>${esc(pr.head.sha.slice(0, 12))}</code> · CI ${esc(row.ci)}. Head-commit signals do not establish merge readiness.</p><div class="detail-actions"><button id="seen">Mark seen</button><label><span class="sr">Snooze until local date and time</span><input id="snooze-time" type="datetime-local" value="${esc(localFuture.toISOString().slice(0, 16))}"></label><button id="snooze">Snooze until…</button>${row.snoozed ? '<button id="unsnooze">Cancel snooze</button>' : ''}</div>${row.snoozed ? `<p>Snoozed until ${esc(date(row.snoozed_until))}. New events are retained while snoozed.</p>` : ''}<h3>Why this PR is here</h3>${row.reasons.map(r => `<div class="reason">${badge(r.code)}<p>${esc(r.text)}</p>${link(r.url, 'View evidence')}<small>${esc(date(r.at))} · ${esc(r.code)}</small></div>`).join('')}<h3>Source freshness</h3><ul class="source-status">${['pr', 'ci', 'reviews', 'comments', 'inline'].map(s => `<li>${esc(s)}: ${row.errors[s] ? 'unavailable · ' + esc(row.errors[s].message) : row.sources[s] ? 'observed ' + esc(date(row.sources[s].observed_at)) : 'not observed'}</li>`).join('')}</ul><p>Review-thread resolution is unavailable in REST mode. Comment order does not tell us whether a thread is resolved. Review counts do not establish reviewer authority or approval freshness.</p><h3>Activity & observed changes</h3><p>Historical activity is included for context. Changes since your local baseline are tracked separately; source time and observation time may differ.</p><ul class="timeline">${row.timeline.length ? row.timeline.map(e => `<li><time>${esc(date(e.at))}</time><p><strong>${esc(e.actor || e.kind)}${e.bot ? ' · bot' : ''}</strong>${e.seq ? ' · observed change' : ''}</p><p>${esc(e.text || e.kind)}</p>${link(e.url, 'View source')}</li>`).join('') : '<li>No recorded activity. The first successful observation is the baseline.</li>'}</ul>`;
    $('seen').onclick = () => action(key, 'seen');
    $('snooze').onclick = () => { const raw = input('snooze-time').value; const end = new Date(raw); if (!raw || !Number.isFinite(end.getTime()) || end.getTime() <= Date.now()) {
        notice('Choose a future snooze date.', true);
        return;
    } void action(key, 'snooze', end.toISOString()); };
    if ($('unsnooze'))
        $('unsnooze').onclick = () => action(key, 'unsnooze');
    if (!dialog.open)
        dialog.showModal();
    else
        $('seen').focus();
}
async function action(key, action, until) {
    if (busy)
        return;
    busy = true;
    try {
        await request('/api/action', { key, action, until });
        await load();
        if (dialog.open)
            showDetail(key);
    }
    catch (e) {
        notice(String(e), true);
    }
    finally {
        busy = false;
        render();
    }
}
$('setup').onsubmit = async (e) => {
    e.preventDefault();
    if (busy)
        return;
    busy = true;
    const b = $('refresh');
    b.disabled = true;
    b.textContent = 'Updating…';
    input('username').disabled = true;
    notice('Reading GitHub sources. Your previous snapshot stays available until each source succeeds.');
    try {
        await request('/api/sync', { username: input('username').value.trim(), scenario: input('scenario').value });
        await load();
        if (dialog.open && selected)
            showDetail(selected);
    }
    catch (e) {
        notice(String(e), true);
    }
    finally {
        busy = false;
        b.disabled = false;
        b.textContent = '↻ Refresh inbox';
        input('username').disabled = false;
        render();
    }
};
for (const id of ['search', 'repo', 'reason', 'draft'])
    $(id).addEventListener(id === 'search' ? 'input' : 'change', render);
document.querySelectorAll('[data-tab]').forEach(b => b.onclick = () => { tab = b.dataset.tab; document.querySelectorAll('[data-tab]').forEach(x => x.setAttribute('aria-pressed', String(x === b))); render(); });
$('close').onclick = () => dialog.close();
dialog.addEventListener('click', e => { if (e.target === dialog) {
    const r = dialog.getBoundingClientRect();
    if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom)
        dialog.close();
} });
const theme = localStorage.getItem('inbox-theme') || (matchMedia('(prefers-color-scheme:dark)').matches ? 'dark' : 'light');
document.documentElement.dataset.theme = theme;
$('theme').onclick = () => { const value = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark'; document.documentElement.dataset.theme = value; localStorage.setItem('inbox-theme', value); };
void load().catch(() => notice('Could not reach the local server. Start python -m inbox.server and reload.', true));
