#!/usr/bin/env python3
"""The pull-request comment body and the update-vs-create choice."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import urllib.error
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "upsert_comment.py"


def load_module():
    spec = importlib.util.spec_from_file_location("upsert_comment", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_comment_body_matches_the_previous_text() -> None:
    module = load_module()
    body = module.comment_body(
        "<!-- private-ci-result -->",
        "failure",
        "selftest",
        "dogfood",
        "0123456789abcdef",
        "https://github.com/ahojukka5/example/actions/runs/9",
        "evidence",
        "  build failed  \n",
    )
    assert body == "\n".join(
        [
            "<!-- private-ci-result -->",
            "### Private CI result: `failure`",
            "",
            "- Workflow: `selftest` / job `dogfood`",
            "- Commit: `0123456789ab`",
            "- Run: https://github.com/ahojukka5/example/actions/runs/9",
            "- Artifact: `evidence`",
            "",
            "build failed",
        ]
    )


def test_empty_summary_uses_the_fallback() -> None:
    module = load_module()
    body = module.comment_body("", "success", "ci", "test", "", "http://run", "art", "   ")
    assert body.endswith("_(no project-provided summary)_")


def test_existing_comment_is_the_one_with_the_marker() -> None:
    module = load_module()
    comments = [
        {"id": 1, "body": "unrelated"},
        {"id": 2, "body": None},
        {"id": 3, "body": "prefix <!-- private-ci-result --> suffix"},
    ]
    assert module.existing_comment_id(comments, "<!-- private-ci-result -->") == 3
    assert module.existing_comment_id(comments, "missing") is None
    assert module.existing_comment_id(comments, "") is None
    comments.append({"id": 4, "body": "<!-- private-ci-result --> later"})
    assert module.existing_comment_id(comments, "<!-- private-ci-result -->") == 3


def test_backticks_in_the_summary_are_preserved() -> None:
    module = load_module()
    body = module.comment_body(
        "<!-- private-ci-result -->",
        "failure",
        "selftest",
        "dogfood",
        "0123456789abcdef",
        "https://github.com/ahojukka5/example/actions/runs/9",
        "evidence",
        "see `code` and a `status` token\n",
    )
    assert "see `code` and a `status` token" in body
    assert "### Private CI result: `failure`" in body
    assert "- Artifact: `evidence`" in body


class _Response:
    def __init__(self, payload):
        self._raw = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _comment_env(token: str) -> dict:
    return {
        "PR_NUMBER": "12",
        "GITHUB_TOKEN": token,
        "GITHUB_REPOSITORY": "ahojukka5/example",
        "GITHUB_SERVER_URL": "https://github.com",
        "GITHUB_API_URL": "https://api.github.com",
        "GITHUB_RUN_ID": "9",
        "GITHUB_WORKFLOW": "selftest",
        "GITHUB_JOB": "dogfood",
        "GITHUB_SHA": "0123456789abcdef",
        "COMMENT_MARKER": "<!-- private-ci-result -->",
        "RESULT_STATUS": "failure",
        "ARTIFACT_NAME": "evidence",
        "SUMMARY_PATH": "",
        "GH_TOKEN": "ghp_not-the-action-token",
        "INPUT_TOKEN": "ghp_not-the-action-token",
    }


def test_marked_comment_is_updated_not_duplicated() -> None:
    module = load_module()
    token = "ghp_test-token-must-not-be-logged"
    calls = []

    def fake(request, timeout=None):
        calls.append((request.method, request.full_url, request.data))
        auth = request.get_header("Authorization")
        assert auth == f"Bearer {token}"
        if request.method == "GET":
            return _Response(
                [{"id": 9, "body": "<!-- private-ci-result --> old"}, {"id": 10, "body": "other"}]
            )
        return _Response({"id": 9})

    stderr = io.StringIO()
    with patch.dict(os.environ, _comment_env(token), clear=False):
        with patch.object(module.urllib.request, "urlopen", fake):
            with contextlib.redirect_stderr(stderr):
                assert module.main() == 0
    assert [call[0] for call in calls] == ["GET", "PATCH"]
    assert calls[1][1].endswith("/issues/comments/9")
    assert "?" not in calls[1][1]
    posted = json.loads(calls[1][2].decode("utf-8"))
    assert posted["body"].startswith("<!-- private-ci-result -->")
    assert "`failure`" in posted["body"]
    assert token not in stderr.getvalue()
    assert token not in posted["body"]


def test_missing_marker_creates_one_comment() -> None:
    module = load_module()
    token = "ghp_test-token-must-not-be-logged"
    calls = []

    def fake(request, timeout=None):
        calls.append((request.method, request.full_url))
        if request.method == "GET":
            return _Response([{"id": 1, "body": "unrelated"}])
        return _Response({"id": 2})

    with patch.dict(os.environ, _comment_env(token), clear=False):
        with patch.object(module.urllib.request, "urlopen", fake):
            assert module.main() == 0
    assert [call[0] for call in calls] == ["GET", "POST"]
    assert calls[1][1].endswith("/issues/12/comments")
    assert "?" not in calls[1][1]


def test_api_error_exits_nonzero_without_logging_the_token() -> None:
    module = load_module()
    token = "ghp_test-token-must-not-be-logged"

    def boom(request, timeout=None):
        raise urllib.error.HTTPError(
            request.full_url,
            403,
            "forbidden",
            hdrs=None,
            fp=io.BytesIO(b'{"message":"nope"}'),
        )

    stderr = io.StringIO()
    with patch.object(module.urllib.request, "urlopen", boom):
        with contextlib.redirect_stderr(stderr):
            try:
                module.api(
                    "GET",
                    "https://api.github.com/repos/ahojukka5/example/issues/12/comments",
                    token,
                )
            except SystemExit as exc:
                assert exc.code == 1
            else:
                raise AssertionError("API error did not exit")
    logged = stderr.getvalue()
    assert "403" in logged
    assert token not in logged


def test_token_is_read_only_from_github_token() -> None:
    module = load_module()
    calls = []

    def fake(request, timeout=None):
        calls.append(request.full_url)
        raise AssertionError("API called without GITHUB_TOKEN")

    env = _comment_env("ghp_should-not-be-used")
    env.pop("GITHUB_TOKEN")
    with patch.dict(os.environ, env, clear=False):
        os.environ.pop("GITHUB_TOKEN", None)
        with patch.object(module.urllib.request, "urlopen", fake):
            assert module.main() == 64
    assert calls == []


def main() -> None:
    test_comment_body_matches_the_previous_text()
    test_empty_summary_uses_the_fallback()
    test_existing_comment_is_the_one_with_the_marker()
    test_backticks_in_the_summary_are_preserved()
    test_marked_comment_is_updated_not_duplicated()
    test_missing_marker_creates_one_comment()
    test_api_error_exits_nonzero_without_logging_the_token()
    test_token_is_read_only_from_github_token()
    print("ok")


if __name__ == "__main__":
    main()
