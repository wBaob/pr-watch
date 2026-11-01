# Contributor Inbox architecture

## A deliberately local application

The original dependency-free CLI remains `pr_watch.py`. The new application is `python -m inbox.server`: Python's threaded loopback HTTP service, SQLite, and a TypeScript UI compiled to a committed ES module. Users need only Python 3.10+ to run; Node/TypeScript are development tools. There are no runtime package downloads, third-party fonts, telemetry, cloud services or GitHub write requests.

The service serializes synchronization and local actions with one lock. GET state can read committed per-source results while an update runs. The UI prevents duplicate refreshes, the service returns 409 to competing writes, and SQLite transactions protect individual updates. Run one server per database. Refresh is synchronous and manual; a very large cap can take minutes. The default discovers at most 20 PRs per refresh, with explicit warnings for truncation. Previously tracked open PRs are rechecked individually even if absent from search. A source failure keeps its last successful data and baseline. Closed PRs stay in history.

## Why REST

REST supports unauthenticated public data, including pull requests, check runs, combined legacy statuses, reviews, conversation comments and inline comments. Review-thread resolution is not provided by these REST collections. The application consistently labels that limitation; it does not infer resolved threads, author responsibility or merge eligibility. The optional GraphQL adapter supplies review threads as an independent source.

API calls are serial, with 20-second per-request timeouts, pagination capped at 100 pages, at most 1000 search results, and no automatic retries. Check histories that reach the pagination cap fail explicitly. HTTP 403/429 establishes an API-wide cooldown using Retry-After and exhausted primary-limit reset headers, with a minimum 60 seconds. The next permitted attempt appears in the UI. A user can refresh later; repeated clicks do not bypass cooldown. Conditional GETs use a bounded, process-local ETag cache (500 entries). Restart clears that optimization but preserves snapshots. Redirects are restricted to HTTPS api.github.com to avoid credential forwarding elsewhere.

## Durable model and baseline semantics

SQLite `user_version=1` has two tables: `prs(owner,key,body)` and `settings(key,value)`. A PR key is `owner/repository#number`; usernames are case-normalized. Each body holds independent `pr`, `ci`, `reviews`, `comments` and `inline` source snapshots, observation timestamps, errors, monotonic event sequence, seen marker and snooze deadline. CI is tied to a head SHA. New head + failed CI retrieval leaves CI UNKNOWN rather than reusing green data from the old head.

First success for each source establishes its baseline. Later successful snapshots generate diffs: new source event IDs, review decision transitions, head SHA/state/merge changes and CI state changes. A failed fetch never advances that source. Repeat sync is idempotent. Feedback keys include source + GitHub event ID; observed transitions carry a local timestamp so repeated transitions remain distinct. Source time is distinct from local observation time. New feedback is newly observed feedback, not a claim that GitHub indexed it immediately.

This version retains latest source snapshots plus the event journal, not all historical raw API responses. Timeline includes current source feedback and transition history. Deleted GitHub comments can disappear from the context timeline, but their previously observed events remain in the journal. Event history is not auto-pruned; a long-running installation may need future retention controls. Comment bodies are truncated to 1500 characters; check output/logs are never stored. There is no full-text copy of commit diffs.

Future schema changes must migrate transactionally and increment user_version; unknown versions are rejected, never silently reset. To reset today, stop the server and move the database to a backup location or start with a fresh `--db` path. Live and demo default to separate databases. Database files may contain private metadata when a token is used; they are gitignored, not encrypted by the application. Do not run demo with a live database path.

## Explainable ordering and local actions

Rules in `inbox/rules.py` return stable code, text, evidence URL, timestamp and facts. Order: CI_FAILED, CHANGES_REQUESTED, NEW_FEEDBACK, HEAD_CHANGED, AUTHOR_ACTIVITY, INSUFFICIENT_DATA, NO_ACTION. Ties put unread changes first and then newer observations. No numerical confidence score is invented. Multiple reasons remain visible in details. Review decisions are latest per reviewer; COMMENTED is not a decision revocation. These are reviewer activity facts, not branch-policy approval.

Mark seen advances a local sequence marker; new events make the row unread again. Persistent failures/change requests stay visible until the upstream condition changes. Snooze excludes a PR from active views until its UTC deadline; new events are retained and do not silently cancel snooze. Cancel is immediate. Times render in the browser's local timezone. Closed/merged rows have their own view.

## Browser/service boundary

Loopback bind, exact Host allowlist, exact Origin, per-process random CSRF token and application/json are required for writes. Unknown routes cannot read arbitrary files. No arbitrary API URL can be supplied. CSP disallows inline scripts and frames; the UI escapes text, restricts evidence links to HTTPS github.com and uses noopener/noreferrer. Only theme preference is in localStorage. Tokens are read from server environment and excluded from responses, SQLite and logs. No access logs are emitted. This protects against unrelated websites; the application is not an isolation boundary against software already executing as the local user. No public-network mode is provided.

## Verification

Offline Python tests exercise rules, storage, partial failures, cooldown, pagination, ETag behavior and HTTP boundaries. Frontend CI type-checks/builds and verifies committed JavaScript matches TypeScript. Browser QA is performed separately using the deterministic demo. A live public-data smoke test is a dated observation, not a dependency of CI. Official API references are linked in README.

## Version 1.1

An optional read-only GraphQL adapter fetches paginated review threads when GITHUB_TOKEN is configured. Each thread includes resolution, outdated-diff state, file/line and first-comment evidence. Partial/error responses never advance the thread baseline. REST remains the unauthenticated fallback. GraphQL has no mutations. Thread resolution does not establish merge readiness.

The event journal now records individual check transitions, newly observed commits and thread resolution changes. Previously observed feedback remains accessible after disappearing from current source snapshots. Local preferences persist ignored bot logins, a preferred repository and change-request priority; they affect display only.

The installable Python package includes static assets and provides contributor-inbox and pr-watch commands. Default databases live in the user application-data directory. SQLite backup uses the database backup API; JSON export is a separate inspection format. Frontend/browser CI uses local deterministic fixtures.
