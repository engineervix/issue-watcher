# Contributing to issue-watcher

This is a small enough project that there isn't much process to it: set up
your environment, keep tests and lint green, open a PR. The rest of this
document is just the specifics.

## Development setup

Prerequisites: Python 3.11 or newer (CI runs 3.13).

```bash
git clone <repository-url>
cd issue-watcher
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
lefthook install
```

No real Slack webhook, Google service account, or sheet is needed to run the
test suite — everything is mocked. You only need real credentials to run
`scripts/check_targets.py` against a live sheet.

## Common tasks

Day to day you'll mostly reach for `python -m unittest discover -s tests` (tests) and `ruff check .` (lint). `lefthook run pre-commit` runs both at once — the same thing that happens automatically on commit once you've run `lefthook install`.

## Conventions

**Code stays small and testable.** `requirements.txt` has exactly two entries, `gspread` and `requests` — reach for the standard library (`unittest`, not `pytest`) before adding a package for something minor. Functions take their dependencies as arguments — a `session`, a `webhook_url` — rather than reading environment variables or building clients themselves; only `main()` touches `os.environ`. That's the whole reason `tests/test_check_targets.py` can mock everything without env-var or import gymnastics, so keep new code in that shape.

**New behaviour needs a test.** Add it to `tests/test_check_targets.py` using `unittest.mock` — no real network calls, no real credentials, ever.

**`README.md` is the only documentation that ships** — `CLAUDE.md` is local build notes and isn't committed, so don't rely on it existing for anyone else, and don't put anything load-bearing only there. If behaviour changes, update `README.md` in the same commit, and keep it short rather than exhaustive: delete stale sections instead of leaving them roughly right, and don't restate in one place what's already said in another (or in the code itself).

**`ruff check .` has to pass.** Run `lefthook install` once and this happens automatically alongside the test suite on every commit.

## Pull requests

1. Create a branch from `main`.
2. Make your change with tests and, if behaviour changed, a `README.md` update.
3. Ensure `ruff check .` and `python -m unittest discover -s tests` pass
   (automatic on commit if you've run `lefthook install`).
4. Open a PR — say what changed and why.

## Reporting issues

Open an issue describing which target (issue/PR/discussion) or behaviour is
affected, and include the relevant `Watch targets` workflow run log if you
have one — most failures show up there as a `::warning::` or `::error::`
line. Don't include real webhook URLs or service account keys in issues or
pull requests.

## Licence

BSD-3-Clause. See [LICENSE](LICENSE).
