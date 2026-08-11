# issue-watcher

![Python](https://img.shields.io/badge/python-%233670A0.svg?style=for-the-badge&logo=python&logoColor=ffdd54)
![Google Sheets](https://img.shields.io/badge/Google%20Sheets-%2334A853.svg?style=for-the-badge&logo=googlesheets&logoColor=white)
![Slack](https://img.shields.io/badge/Slack-4A154B.svg?style=for-the-badge&logo=slack&logoColor=white)

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

`scripts/check_targets.py` reads every row of the sheet, fetches each target (REST for issues/PRs, GraphQL for discussions), and compares what comes back against the sheet's `updated_at` column. Something changed? It posts to Slack and updates the row with the new title, `updated_at`, and comment count. Nothing changed? The row is left alone — no message, no write.

Anything that doesn't fetch cleanly — a 404, a blank `url`, a link that isn't a GitHub issue/PR/discussion — gets a warning and a skip rather than a crash, and its row is left exactly as it was. That last part matters: it's what stops a target coming back online from looking like it "changed" the moment it's reachable again.

## Development

- `python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt` (or `uv venv && uv pip install -r requirements.txt`) to get `gspread`/`requests` locally.
- `python -m unittest discover -s tests` runs the test suite (mocks Google Sheets, GitHub, and Slack — no network, no real credentials needed).
- Run `lefthook install` once after cloning — it wires up a pre-commit hook that runs `ruff check` and the test suite against any changed `.py` file (config in `lefthook.yml`). Needs `ruff` on `PATH` (`uv tool install ruff`, or add it to your venv).
