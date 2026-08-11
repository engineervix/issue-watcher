#!/usr/bin/env python3
"""Checks every target row in the tracking sheet and notifies Slack on change."""
import json
import os
import re
import sys
from collections.abc import Mapping
from typing import Literal, TypedDict

import gspread
import requests

Kind = Literal["issue", "pr", "discussion"]


class TargetInfo(TypedDict):
    """A target's fetched state, as returned by fetch_target."""

    title: str
    url: str
    updated_at: str
    comments: int


TARGET_RE = re.compile(
    r"^https://github\.com/([^/]+)/([^/]+)/(issues|pull|discussions)/(\d+)/?$"
)
PATH_KIND_TO_KIND: dict[str, Kind] = {
    "issues": "issue",
    "pull": "pr",
    "discussions": "discussion",
}

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


def parse_target(url: str) -> tuple[str, str, Kind, str] | None:
    """Parses a GitHub URL into the parts needed to fetch it.

    Args:
        url: A full GitHub URL, e.g. "https://github.com/owner/repo/issues/1".

    Returns:
        The parsed (owner, repo, kind, number), or None if url isn't a
        recognised issue, PR, or discussion link.
    """
    match = TARGET_RE.match(url)
    if not match:
        return None
    owner, repo, path_kind, number = match.groups()
    return owner, repo, PATH_KIND_TO_KIND[path_kind], number


def fetch_target(
    session: requests.Session, owner: str, repo: str, kind: Kind, number: str
) -> TargetInfo | None:
    """Fetches a target's current state from the GitHub API.

    Uses the REST API for issues and PRs, and GraphQL for discussions,
    which have no REST endpoint.

    Args:
        session: An authenticated requests.Session for api.github.com.
        owner: Repository owner.
        repo: Repository name.
        kind: Which endpoint (or query, for a discussion) to use.
        number: The issue/PR/discussion number.

    Returns:
        The target's current state, or None if it doesn't exist (deleted,
        moved, or a 404).

    Raises:
        requests.HTTPError: If the request fails for any reason other than
            a 404, e.g. rate limiting or a bad token.
    """
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


def notify_slack(webhook_url: str, kind: Kind, current: TargetInfo) -> None:
    """Posts a "this target changed" message to a Slack incoming webhook.

    Args:
        webhook_url: The Slack incoming webhook URL.
        kind: Used to label the message, e.g. "(PR)" vs "(issue)".
        current: The target's current state, as returned by fetch_target.

    Raises:
        requests.HTTPError: If the webhook POST fails.
    """
    kind_label = "PR" if kind == "pr" else kind
    text = (
        f"*{current['title']}* ({kind_label}) was updated\n"
        f"{current['url']}\n"
        f"Comments: {current['comments']}"
    )
    resp = requests.post(webhook_url, json={"text": text}, timeout=30)
    resp.raise_for_status()


def check_row(
    session: requests.Session,
    webhook_url: str,
    row: Mapping[str, int | float | str],
) -> tuple[str, str, int] | None:
    """Fetches one target and notifies Slack if it changed.

    Skips (without raising) a blank or unrecognised url, a target that
    fails to fetch, or one whose fetched state matches the row already.

    Args:
        session: An authenticated requests.Session for api.github.com.
        webhook_url: The Slack incoming webhook URL to notify on change.
        row: One sheet row; only the "url" and "updated_at" keys are read.

    Returns:
        The (title, updated_at, comments) tuple to write back to the
        sheet, or None if the row was skipped or nothing changed.
    """
    url = str(row.get("url", "")).strip()
    if not url:
        return None

    parsed = parse_target(url)
    if parsed is None:
        print(f"::warning::Skipping unrecognised target URL: {url}", file=sys.stderr)
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


def main() -> None:
    """Entry point: checks every target in the sheet and updates it in place.

    Reads GITHUB_TOKEN, SLACK_WEBHOOK_URL, SHEET_ID, and
    GOOGLE_SERVICE_ACCOUNT_JSON from the environment.

    Raises:
        KeyError: If a required environment variable isn't set.
    """
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
            worksheet.update([list(new_values)], f"B{sheet_row}:D{sheet_row}")


if __name__ == "__main__":
    main()
