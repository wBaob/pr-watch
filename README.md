# PR Watch

A small, read-only GitHub API integration for contributors who want to check their open pull requests across repositories from one terminal.

PR Watch shows head-commit CI results, draft status, review approvals and change requests. It uses Python's standard library; no packages or GitHub account connection are needed for public data.

## Run

Requires Python 3.10 or newer.

```sh
git clone https://github.com/wBaob/pr-watch.git
cd pr-watch
python pr_watch.py wBaob
python pr_watch.py octocat --limit 5 --json
```

On Windows, `py` can be used instead of `python`.

Public requests work without a token, subject to GitHub's unauthenticated API limits. Each PR needs several API requests. If needed, set `GITHUB_TOKEN` in your environment; never put it in source code, command arguments or an issue. Only grant read access to the repositories and metadata you need (pull requests, checks and commit statuses). The tool never writes to GitHub. A token can expose private PR metadata in the report, so review reports before sharing them.

## Output

Each entry includes a clickable PR URL, CI summary and review counts. `--json` emits a timestamped report for use by other tools. Default: the 10 most recently updated open PRs; `--limit` accepts 1–100. A warning identifies truncated or incomplete results. Exit code `0` means the report was retrieved, `1` means a fatal API error, and `2` means a partial report or a result limit was reached. Failing CI is report data, not a CLI error.

CI states: `PASSING`, `FAILING`, `PENDING`, `NO_CHECKS` or `UNKNOWN`. Both check runs and legacy commit statuses are included. Neutral/skipped checks are treated as non-failing. Missing or inaccessible results are never presented as passing.

## Scope and limitations

- This is a one-shot snapshot. Run it again to refresh; there is no background service or notification delivery.
- CI is for the PR head commit in the base repository. Synthetic merge-commit checks, required-check policies and merge queues may differ. This is not a merge-readiness decision.
- Review counts use each reviewer's latest approval/change-request decision; comments do not overwrite decisions. These counts are not GitHub's branch-protection review decision and do not establish reviewer authority or approval freshness after new commits.
- Search indexing can lag; a PR may close between discovery and inspection. JSON includes its observed state.
- Large review/check histories are paginated, with a 100-page safety limit. Errors and rate limits are explicit; there are no automatic retries.
- Supports github.com only. No affiliation with or endorsement by GitHub.

## Development

```sh
python -m unittest -v
```

Tests cover CI aggregation, review state changes, pagination and partial API failures. Live verification is separate from these offline tests.

## GitHub API references

- [Search issues and pull requests](https://docs.github.com/en/rest/search#search-issues-and-pull-requests)
- [Pull requests](https://docs.github.com/en/rest/pulls/pulls)
- [Check runs](https://docs.github.com/en/rest/checks/runs)
- [Commit statuses](https://docs.github.com/en/rest/commits/statuses)
- [Pull request reviews](https://docs.github.com/en/rest/pulls/reviews)

## Support

Use [repository issues](https://github.com/wBaob/pr-watch/issues) for bugs and feature requests. Do not include tokens or private repository information.

## License

MIT. See [LICENSE](LICENSE).
