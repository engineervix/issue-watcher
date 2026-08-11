import json
import sys
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import check_targets


class FakeResponse:
    def __init__(self, payload: Any, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> Any:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


ISSUE_BODY = {
    "title": "Fake issue",
    "html_url": "https://github.com/o/r/issues/1",
    "updated_at": "2026-08-01T00:00:00Z",
    "comments": 1,
}

PR_BODY = {
    "title": "Fake PR",
    "html_url": "https://github.com/o/r/pull/123",
    "updated_at": "2026-08-01T00:00:00Z",
    "comments": 3,
}

DISCUSSION_RESPONSE = {
    "data": {
        "repository": {
            "discussion": {
                "title": "Fake discussion",
                "url": "https://github.com/o/r/discussions/45",
                "updatedAt": "2026-08-01T00:00:00Z",
                "comments": {"totalCount": 2},
            }
        }
    }
}

DISCUSSION_NOT_FOUND_RESPONSE = {"data": {"repository": {"discussion": None}}}


class TestParseTarget(unittest.TestCase):
    def test_issue_url(self):
        self.assertEqual(
            check_targets.parse_target("https://github.com/o/r/issues/1"),
            ("o", "r", "issue", "1"),
        )

    def test_pull_url(self):
        self.assertEqual(
            check_targets.parse_target("https://github.com/o/r/pull/123"),
            ("o", "r", "pr", "123"),
        )

    def test_discussion_url(self):
        self.assertEqual(
            check_targets.parse_target("https://github.com/o/r/discussions/45"),
            ("o", "r", "discussion", "45"),
        )

    def test_trailing_slash_is_allowed(self):
        self.assertEqual(
            check_targets.parse_target("https://github.com/o/r/issues/1/"),
            ("o", "r", "issue", "1"),
        )

    def test_non_github_url_is_rejected(self):
        self.assertIsNone(check_targets.parse_target("https://gitlab.com/o/r/issues/1"))

    def test_unrecognized_path_is_rejected(self):
        self.assertIsNone(check_targets.parse_target("https://github.com/o/r/commits/abc"))

    def test_garbage_is_rejected(self):
        self.assertIsNone(check_targets.parse_target("not a url"))


class TestFetchTarget(unittest.TestCase):
    def test_issue_hits_issues_endpoint(self):
        session = mock.Mock()
        session.get.return_value = FakeResponse(ISSUE_BODY)

        result = check_targets.fetch_target(session, "o", "r", "issue", "1")

        session.get.assert_called_once_with(
            "https://api.github.com/repos/o/r/issues/1", timeout=30
        )
        self.assertEqual(
            result,
            {
                "title": "Fake issue",
                "url": "https://github.com/o/r/issues/1",
                "updated_at": "2026-08-01T00:00:00Z",
                "comments": 1,
            },
        )

    def test_pr_hits_pulls_endpoint(self):
        session = mock.Mock()
        session.get.return_value = FakeResponse(PR_BODY)

        check_targets.fetch_target(session, "o", "r", "pr", "123")

        session.get.assert_called_once_with(
            "https://api.github.com/repos/o/r/pulls/123", timeout=30
        )

    def test_issue_404_returns_none(self):
        session = mock.Mock()
        session.get.return_value = FakeResponse({}, status_code=404)

        self.assertIsNone(check_targets.fetch_target(session, "o", "r", "issue", "999"))

    def test_issue_server_error_raises(self):
        session = mock.Mock()
        session.get.return_value = FakeResponse({}, status_code=500)

        with self.assertRaises(requests.HTTPError):
            check_targets.fetch_target(session, "o", "r", "issue", "1")

    def test_discussion_uses_graphql(self):
        session = mock.Mock()
        session.post.return_value = FakeResponse(DISCUSSION_RESPONSE)

        result = check_targets.fetch_target(session, "o", "r", "discussion", "45")

        session.post.assert_called_once()
        args, kwargs = session.post.call_args
        self.assertEqual(args[0], "https://api.github.com/graphql")
        self.assertEqual(
            kwargs["json"]["variables"], {"owner": "o", "repo": "r", "number": 45}
        )
        self.assertEqual(
            result,
            {
                "title": "Fake discussion",
                "url": "https://github.com/o/r/discussions/45",
                "updated_at": "2026-08-01T00:00:00Z",
                "comments": 2,
            },
        )

    def test_discussion_not_found_returns_none(self):
        session = mock.Mock()
        session.post.return_value = FakeResponse(DISCUSSION_NOT_FOUND_RESPONSE)

        self.assertIsNone(check_targets.fetch_target(session, "o", "r", "discussion", "999"))


class TestNotifySlack(unittest.TestCase):
    @mock.patch("check_targets.requests.post")
    def test_posts_expected_payload(self, mock_post):
        mock_post.return_value = FakeResponse({})
        current = {
            "title": "Fake issue",
            "url": "https://github.com/o/r/issues/1",
            "updated_at": "2026-08-01T00:00:00Z",
            "comments": 1,
        }

        check_targets.notify_slack("https://example.invalid/webhook", "issue", current)

        mock_post.assert_called_once_with(
            "https://example.invalid/webhook",
            json={"text": "*Fake issue* (issue) was updated\nhttps://github.com/o/r/issues/1\nComments: 1"},
            timeout=30,
        )

    @mock.patch("check_targets.requests.post")
    def test_pr_label_is_uppercase(self, mock_post):
        mock_post.return_value = FakeResponse({})
        current = {"title": "T", "url": "https://github.com/o/r/pull/1", "updated_at": "x", "comments": 0}

        check_targets.notify_slack("https://example.invalid/webhook", "pr", current)

        sent_text = mock_post.call_args.kwargs["json"]["text"]
        self.assertIn("(PR)", sent_text)


class TestCheckRow(unittest.TestCase):
    def setUp(self):
        self.session = mock.Mock()

    def test_blank_url_is_skipped(self):
        result = check_targets.check_row(self.session, "webhook", {"url": ""})
        self.assertIsNone(result)
        self.session.get.assert_not_called()
        self.session.post.assert_not_called()

    def test_unrecognized_url_is_skipped(self):
        result = check_targets.check_row(self.session, "webhook", {"url": "not a url"})
        self.assertIsNone(result)

    def test_fetch_failure_is_skipped_not_raised(self):
        self.session.get.side_effect = requests.ConnectionError("boom")
        result = check_targets.check_row(
            self.session, "webhook", {"url": "https://github.com/o/r/issues/1"}
        )
        self.assertIsNone(result)

    def test_404_target_is_skipped(self):
        self.session.get.return_value = FakeResponse({}, status_code=404)
        result = check_targets.check_row(
            self.session, "webhook", {"url": "https://github.com/o/r/issues/999"}
        )
        self.assertIsNone(result)

    @mock.patch("check_targets.notify_slack")
    def test_unchanged_target_does_not_notify(self, mock_notify):
        self.session.get.return_value = FakeResponse(ISSUE_BODY)
        row = {
            "url": "https://github.com/o/r/issues/1",
            "updated_at": "2026-08-01T00:00:00Z",
        }

        result = check_targets.check_row(self.session, "webhook", row)

        self.assertIsNone(result)
        mock_notify.assert_not_called()

    @mock.patch("check_targets.notify_slack")
    def test_changed_target_notifies_and_returns_new_values(self, mock_notify):
        self.session.get.return_value = FakeResponse(ISSUE_BODY)
        row = {"url": "https://github.com/o/r/issues/1", "updated_at": ""}

        result = check_targets.check_row(self.session, "webhook", row)

        mock_notify.assert_called_once_with("webhook", "issue", mock.ANY)
        self.assertEqual(result, ("Fake issue", "2026-08-01T00:00:00Z", 1))


class TestMain(unittest.TestCase):
    def _fake_session(self) -> mock.MagicMock:
        session = mock.MagicMock()

        def fake_get(url: str, timeout: int = 30) -> FakeResponse:
            if url == "https://api.github.com/repos/o/r/issues/1":
                return FakeResponse(ISSUE_BODY)
            if url == "https://api.github.com/repos/o/r/pulls/123":
                return FakeResponse(PR_BODY)
            return FakeResponse({}, status_code=404)

        def fake_post(
            url: str, json: dict[str, Any] | None = None, timeout: int = 30
        ) -> FakeResponse:
            assert url == "https://api.github.com/graphql"
            return FakeResponse(DISCUSSION_RESPONSE)

        session.get.side_effect = fake_get
        session.post.side_effect = fake_post
        return session

    def _run_main(self, rows: list[dict[str, Any]]) -> tuple[mock.Mock, mock.Mock]:
        worksheet = mock.Mock()
        worksheet.get_all_records.return_value = rows
        gc = mock.Mock()
        gc.open_by_key.return_value.sheet1 = worksheet

        env = {
            "GITHUB_TOKEN": "fake-token",
            "SLACK_WEBHOOK_URL": "https://example.invalid/webhook",
            "SHEET_ID": "fake-sheet-id",
            "GOOGLE_SERVICE_ACCOUNT_JSON": json.dumps({"type": "service_account"}),
        }

        with mock.patch.dict("os.environ", env), \
             mock.patch("check_targets.requests.Session", return_value=self._fake_session()), \
             mock.patch("check_targets.gspread.service_account_from_dict", return_value=gc), \
             mock.patch("check_targets.requests.post", return_value=FakeResponse({})) as mock_slack:
            check_targets.main()

        return worksheet, mock_slack

    def test_first_run_notifies_and_writes_back_every_target(self):
        rows = [
            {"url": "https://github.com/o/r/issues/1", "title": "", "updated_at": "", "comments": ""},
            {"url": "https://github.com/o/r/pull/123", "title": "", "updated_at": "", "comments": ""},
            {"url": "https://github.com/o/r/discussions/45", "title": "", "updated_at": "", "comments": ""},
        ]

        worksheet, mock_slack = self._run_main(rows)

        self.assertEqual(mock_slack.call_count, 3)
        self.assertEqual(worksheet.update.call_count, 3)
        worksheet.update.assert_any_call(
            [["Fake issue", "2026-08-01T00:00:00Z", 1]], "B2:D2"
        )
        worksheet.update.assert_any_call(
            [["Fake discussion", "2026-08-01T00:00:00Z", 2]], "B4:D4"
        )

    def test_unchanged_targets_are_silent(self):
        rows = [
            {"url": "https://github.com/o/r/issues/1", "title": "Fake issue", "updated_at": "2026-08-01T00:00:00Z", "comments": 1},
            {"url": "https://github.com/o/r/pull/123", "title": "Fake PR", "updated_at": "2026-08-01T00:00:00Z", "comments": 3},
        ]

        worksheet, mock_slack = self._run_main(rows)

        mock_slack.assert_not_called()
        worksheet.update.assert_not_called()

    def test_blank_and_bad_rows_do_not_crash_the_run(self):
        rows = [
            {"url": "", "title": "", "updated_at": "", "comments": ""},
            {"url": "not a github url", "title": "", "updated_at": "", "comments": ""},
            {"url": "https://github.com/o/r/issues/999", "title": "", "updated_at": "", "comments": ""},
        ]

        worksheet, mock_slack = self._run_main(rows)

        mock_slack.assert_not_called()
        worksheet.update.assert_not_called()


if __name__ == "__main__":
    unittest.main()
