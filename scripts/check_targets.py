#!/usr/bin/env python3
import json
import os
import re
import sys

import gspread
import requests

TARGET_RE = re.compile(
    r"^https://github\.com/([^/]+)/([^/]+)/(issues|pull|discussions)/(\d+)/?$"
)
PATH_KIND_TO_KIND = {"issues": "issue", "pull": "pr", "discussions": "discussion"}

DISCUSSION_QUERY = """
query($owner: String!, $repo: String!, $number: Int!) {
  repository(owner: $owner, name: $repo) {
    discussion(number: $number) {
      title
      url
      updatedAt
      comments { totalCount }
    }
  }
}
"""


def parse_target(url):
    """Returns (owner, repo, kind, number), or None if url isn't a recognized target."""
    match = TARGET_RE.match(url)
    if not match:
        return None
    owner, repo, path_kind, number = match.groups()
    return owner, repo, PATH_KIND_TO_KIND[path_kind], number


def fetch_target(session, owner, repo, kind, number):
    """Returns {title, url, updated_at, comments}, or None if not found."""
    if kind == "discussion":
        resp = session.post(
            "https://api.github.com/graphql",
            json={
                "query": DISCUSSION_QUERY,
                "variables": {"owner": owner, "repo": repo, "number": int(number)},
            },
            timeout=30,
        )
        resp.raise_for_status()
        discussion = resp.json()["data"]["repository"]["discussion"]
        if discussion is None:
            return None
        return {
            "title": discussion["title"],
            "url": discussion["url"],
            "updated_at": discussion["updatedAt"],
            "comments": discussion["comments"]["totalCount"],
        }

    endpoint = "pulls" if kind == "pr" else "issues"
    resp = session.get(
        f"https://api.github.com/repos/{owner}/{repo}/{endpoint}/{number}",
        timeout=30,
    )
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    body = resp.json()
    return {
        "title": body["title"],
        "url": body["html_url"],
        "updated_at": body["updated_at"],
        "comments": body["comments"],
    }


def notify_slack(webhook_url, kind, current):
    kind_label = "PR" if kind == "pr" else kind
    text = (
        f"*{current['title']}* ({kind_label}) was updated\n"
        f"{current['url']}\n"
        f"Comments: {current['comments']}"
    )
    resp = requests.post(webhook_url, json={"text": text}, timeout=30)
    resp.raise_for_status()


def check_row(session, webhook_url, row):
    """Fetches one target and notifies Slack if it changed.

    Returns the (title, updated_at, comments) tuple to write back to the
    sheet, or None if the row was skipped or nothing changed.
    """
    url = str(row.get("url", "")).strip()
    if not url:
        return None

    parsed = parse_target(url)
    if parsed is None:
        print(f"::warning::Skipping unrecognized target URL: {url}", file=sys.stderr)
        return None
    owner, repo, kind, number = parsed

    try:
        current = fetch_target(session, owner, repo, kind, number)
    except requests.RequestException as exc:
        print(f"::warning::Failed to fetch {url}, skipping this run: {exc}", file=sys.stderr)
        return None

    if current is None:
        print(f"::warning::{kind.title()} not found (deleted/moved?), skipping this run: {url}", file=sys.stderr)
        return None

    old_updated_at = str(row.get("updated_at", ""))
    if current["updated_at"] == old_updated_at:
        return None

    notify_slack(webhook_url, kind, current)
    print(f"Posted update for {url}")
    return current["title"], current["updated_at"], current["comments"]


def main():
    github_token = os.environ["GITHUB_TOKEN"]
    slack_webhook_url = os.environ["SLACK_WEBHOOK_URL"]
    sheet_id = os.environ["SHEET_ID"]
    google_service_account_json = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]

    session = requests.Session()
    session.headers["Authorization"] = f"Bearer {github_token}"
    session.headers["Accept"] = "application/vnd.github+json"

    gc = gspread.service_account_from_dict(json.loads(google_service_account_json))
    worksheet = gc.open_by_key(sheet_id).sheet1

    for i, row in enumerate(worksheet.get_all_records()):
        new_values = check_row(session, slack_webhook_url, row)
        if new_values is not None:
            sheet_row = i + 2  # header is row 1
            worksheet.update(f"B{sheet_row}:D{sheet_row}", [list(new_values)])


if __name__ == "__main__":
    main()
