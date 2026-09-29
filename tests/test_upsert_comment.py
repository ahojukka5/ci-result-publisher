#!/usr/bin/env python3
"""The pull-request comment body and the update-vs-create choice."""

from __future__ import annotations

import importlib.util
from pathlib import Path

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


def main() -> None:
    test_comment_body_matches_the_previous_text()
    test_empty_summary_uses_the_fallback()
    test_existing_comment_is_the_one_with_the_marker()
    print("ok")


if __name__ == "__main__":
    main()
