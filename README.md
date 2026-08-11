# issue-watcher

Watches a list of GitHub issues, pull requests, and discussions. Posts to Slack when one changes. Does nothing on runs with no changes.

<!-- START doctoc generated TOC please keep comment here to allow auto update -->
<!-- DON'T EDIT THIS SECTION, INSTEAD RE-RUN doctoc TO UPDATE -->
**Contents**  *generated with [DocToc](https://github.com/thlorenz/doctoc)*

- [Setup](#setup)
- [How it works](#how-it-works)
- [Development](#development)

<!-- END doctoc generated TOC please keep comment here to allow auto update -->

## Setup

1. Create a Google Sheet with these headers in row 1: `url | title | updated_at | comments`. Add one row per target under it, filling in only the `url` column (any mix of issue/PR/discussion, any repo) — the rest gets filled in by the script:

   | url | title | updated_at | comments |
   |---|---|---|---|
   | `https://github.com/zensical/backlog/issues/83` | | | |
   | `https://github.com/owner/repo/pull/123` | | | |
   | `https://github.com/owner/repo/discussions/45` | | | |

2. In [Google Cloud Console](https://console.cloud.google.com/), enable the Google Sheets API and create a service account. Download its JSON key, and share the Sheet with the service account's `client_email` (Editor access).
3. On this repo: add secret `SLACK_WEBHOOK_URL`, add secret `GOOGLE_SERVICE_ACCOUNT_JSON` (the full contents of the downloaded JSON key), and add repo variable `SHEET_ID` (the long ID in the sheet's URL, between `/d/` and `/edit`). Settings → Secrets and variables → Actions.
4. Trigger the `Watch targets` workflow manually (Actions tab → Run workflow) to confirm it posts once per target and fills in the sheet, then run it again to confirm it goes quiet.

Runs every 6h on its own after that (`.github/workflows/watch.yml`).

To add or remove a target later, just add/delete a row in the sheet — no code change, no redeploy.

## How it works

- `scripts/check_targets.py` reads every row of the sheet, fetches each target (REST for issues/PRs, GraphQL for discussions), and compares the fetched `updated_at` against the sheet's `updated_at` column.
- Changed targets get a Slack message, and the sheet row is updated with the new title/`updated_at`/comment count. Unchanged targets are left untouched — no Slack message, no sheet write.
- A target that fails to fetch (404, deleted, moved) is logged as a warning and skipped for that run — its row is left as-is, so it won't falsely "change" once it's reachable again.
- A blank `url` cell or one that isn't a recognized GitHub issue/PR/discussion link is skipped with a warning, not a crash.

## Development

- `python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt` (or `uv venv && uv pip install -r requirements.txt`) to get `gspread`/`requests` locally.
- `python -m unittest discover -s tests` runs the test suite (mocks Google Sheets, GitHub, and Slack — no network, no real credentials needed).
- Run `lefthook install` once after cloning — it wires up a pre-commit hook that runs `ruff check` and the test suite against any changed `.py` file (config in `lefthook.yml`). Needs `ruff` on `PATH` (`uv tool install ruff`, or add it to your venv).
