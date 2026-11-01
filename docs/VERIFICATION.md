# Verification — 2026-11-01

## Automated, offline

- Python 3.12.10 on Windows: `python -m unittest -v` — 26 tests.
- `npm run check` and `npm run build` — TypeScript strict checking and compilation.
- CI runs Python 3.10/3.12/3.13 and separately rebuilds TypeScript to detect drift in committed JavaScript. Current run status is available in [GitHub Actions](https://github.com/wBaob/pr-watch/actions).

Coverage includes CI reruns and legacy statuses, review decision transitions, deduplicated baselines, new feedback after seen, author/bot/deleted-user handling, source failure preservation, new-head CI invalidation, missing-search direct verification, global offline state, cooldown, ETag 304, redirect restrictions, snooze persistence/expiry, merged/closed events, demo isolation, same-origin/CSRF enforcement, duplicate sync and static path boundaries. Tests never contact GitHub.

## Browser QA

Chromium browser checks, against the local Python service:

- Live setup: enter wBaob → Refresh → two real public PRs, initial baseline, no historical feedback marked new.
- Demo: Refresh → filter NEW_FEEDBACK → open details → Mark seen → feedback reason disappears → Snooze → reload/restart → Snoozed view retains deadline → Cancel snooze.
- Switching synthetic scenarios: rate-limit shows next permitted attempt and UNKNOWN CI, empty scenario shows an empty queue. Other fixtures cover closed/merged and long titles.
- Desktop light theme at 1440×1000 and mobile dark theme at 390×844, visually inspected. Mobile document width did not exceed viewport width. Screenshots use fictional data only.
- Adversarial synthetic title containing an img/onerror string and comment containing script markup rendered as text. No injected image or script executed. A javascript: evidence link was replaced with “link unavailable”. Long title/detail panel had no horizontal overflow.
- Tab moved keyboard focus inside the native dialog; Escape closed it. Reduced-motion CSS suppresses animation. Final reload reported zero browser console errors after fixing a favicon CSP issue and the browser's Unicode-regex username pattern.

This is focused QA, not a claim of exhaustive accessibility or browser compatibility certification.

## Live read-only snapshot

At approximately 14:19 UTC (19:19 Asia/Qyzylorda) on 2026-11-01, the public-data UI retrieved:

- `amnezia-vpn/amnezia-client#3321`: CI PASSING.
- `reconurge/flowsint#242`: CI NO_CHECKS.

All required REST source collections were retrieved for this baseline. No GitHub data was mutated, no real notifications were sent, and live snapshots were not committed. These statuses are dated observations, not merge-readiness findings. Review-thread resolution remains unavailable in REST mode.

## Scope

Developer Program registration, acceptance and badge issuance have not been performed or verified. This delivers the working integration and its source code, not a guarantee of program membership.

## Version 1.1 validation

29 Python tests include GraphQL pagination, null authors, rate-limited partial responses and token-free request prevention. Browser regression tests cover refresh/filter/details/seen/snooze/reload/preferences, mobile layout, untrusted text and unsafe URLs. The suite is part of GitHub Actions. The live token-enabled GraphQL path requires a user-configured token; fixture tests do not establish that a particular account has repository access.

The packaged contributor-inbox command and SQLite backup were verified in an isolated virtual environment. Both automated Chromium browser tests passed using the installed Chrome channel. A live authorized GraphQL query for Amnezia PR #3321 returned successfully with zero review threads; nonempty and paginated responses are covered by fixtures.
