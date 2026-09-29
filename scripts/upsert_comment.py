#!/usr/bin/env python3
"""Create or update this action's stable pull-request comment.

The comment text matches the previous github-script step. Only the first
100 comments on the PR are searched. A PR that already has more than that
before this action's first run can get a duplicate on that first run.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def comment_body(
    marker: str,
    status: str,
    workflow: str,
    job: str,
    sha: str,
    run_url: str,
    artifact: str,
    summary: str,
) -> str:
    shown = summary.strip() if summary and summary.strip() else "_(no project-provided summary)_"
    return "\n".join(
        [
            marker,
            f"### Private CI result: `{status}`",
            "",
            f"- Workflow: `{workflow}` / job `{job}`",
            f"- Commit: `{sha[:12]}`",
            f"- Run: {run_url}",
            f"- Artifact: `{artifact}`",
            "",
            shown,
        ]
    )


def existing_comment_id(comments: list, marker: str):
    if not marker:
        return None
    for comment in comments:
        body = comment.get("body") or ""
        if marker in body:
            return comment.get("id")
    return None


def read_summary(path: str) -> str:
    if not path:
        return ""
    candidate = Path(path)
    if not candidate.is_file():
        return ""
    return candidate.read_text(encoding="utf-8")


def api(method: str, url: str, token: str, payload=None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Authorization", f"Bearer {token}")
    request.add_header("Accept", "application/vnd.github+json")
    request.add_header("X-GitHub-Api-Version", "2022-11-28")
    if payload is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        print(f"::error::GitHub API {method} {url} failed: {exc.code} {detail}", file=sys.stderr)
        raise SystemExit(1) from exc
    return json.loads(raw) if raw else None


def main() -> int:
    pr_number = env("PR_NUMBER")
    if not pr_number:
        return 0
    token = env("GITHUB_TOKEN")
    if not token:
        print("::error::GITHUB_TOKEN is required to upsert a pull request comment", file=sys.stderr)
        return 64
    repository = env("GITHUB_REPOSITORY")
    owner, _, name = repository.partition("/")
    if not owner or not name:
        print("::error::GITHUB_REPOSITORY must be owner/name", file=sys.stderr)
        return 64

    server = env("GITHUB_SERVER_URL", "https://github.com").rstrip("/")
    run_url = f"{server}/{owner}/{name}/actions/runs/{env('GITHUB_RUN_ID')}"
    body = comment_body(
        env("COMMENT_MARKER"),
        env("RESULT_STATUS"),
        env("GITHUB_WORKFLOW"),
        env("GITHUB_JOB"),
        env("GITHUB_SHA"),
        run_url,
        env("ARTIFACT_NAME"),
        read_summary(env("SUMMARY_PATH")),
    )

    api_root = env("GITHUB_API_URL", "https://api.github.com").rstrip("/")
    quoted_owner = urllib.parse.quote(owner)
    quoted_name = urllib.parse.quote(name)
    comments_url = (
        f"{api_root}/repos/{quoted_owner}/{quoted_name}/issues/{pr_number}/comments"
        "?per_page=100"
    )
    comments = api("GET", comments_url, token)
    if not isinstance(comments, list):
        print("::error::GitHub comment list was not a JSON array", file=sys.stderr)
        return 1
    found = existing_comment_id(comments, env("COMMENT_MARKER"))
    if found:
        api(
            "PATCH",
            f"{api_root}/repos/{quoted_owner}/{quoted_name}/issues/comments/{found}",
            token,
            {"body": body},
        )
    else:
        api("POST", comments_url.split("?", 1)[0], token, {"body": body})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
