#!/usr/bin/env python3
"""Build the generic result.json envelope and a redacted summary copy.

Deliberately in Python, not jq: jq is not preinstalled on every self-hosted
runner image this action targets (confirmed absent on at least one), while
python3 is close to universal on both GitHub-hosted and self-hosted runners.

Reads its configuration from environment variables (set by action.yml) and
writes two files, then appends their paths to $GITHUB_OUTPUT:

  result-json-path       the merged/generated result.json
  redacted-summary-path   a redacted copy of the project's summary-file
                          (or a generic fallback if none was given)

This script must not fail merely because the project's task failed, or
because the project omitted optional inputs -- the whole point of this
action is to still publish whatever evidence exists. It only exits non-zero
for genuine misconfiguration (a required input missing).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def require(name: str) -> str:
    value = env(name)
    if not value:
        print(f"::error::{name} is required", file=sys.stderr)
        sys.exit(64)
    return value


def load_project_json(path: str) -> dict:
    if not path:
        return {}
    candidate = Path(path)
    if not candidate.is_file():
        print(
            f"::warning::metadata-file '{path}' was configured but does not "
            "exist; generating a default result.json instead",
            file=sys.stderr,
        )
        return {}
    try:
        loaded = json.loads(candidate.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(
            f"::warning::metadata-file '{path}' is not valid JSON ({exc}); "
            "generating a default result.json instead",
            file=sys.stderr,
        )
        return {}
    if not isinstance(loaded, dict):
        print(
            f"::warning::metadata-file '{path}' is JSON but not an object; "
            "generating a default result.json instead",
            file=sys.stderr,
        )
        return {}
    return loaded


def redact(text: str, redact_spec: str) -> str:
    """Replace configured secret values with a fixed marker. Each line in
    redact_spec is either a literal value to redact, or the NAME of an
    environment variable whose value should be redacted -- this lets a
    workflow pass `${{ secrets.X }}` by reference (as an env var name) it
    would otherwise have to inline as ciphertext into the action's inputs."""
    for entry in redact_spec.splitlines():
        entry = entry.strip()
        if not entry:
            continue
        value = os.environ.get(entry, entry)
        if value:
            text = text.replace(value, "***REDACTED***")
    return text


def default_summary(status: str) -> str:
    return f"_(no project-provided summary; final status: `{status}`)_"


def result_json_destination(metadata_file: str, paths_raw: str) -> Path:
    """Keep the generated envelope inside GITHUB_WORKSPACE, including when
    paths use absolute names, traversal or symlinks. Do not write to
    RUNNER_TEMP or outside the workspace just because an input names it."""
    workspace = Path(env("GITHUB_WORKSPACE") or os.getcwd()).resolve()
    if metadata_file:
        candidate = Path(metadata_file)
    else:
        paths = [entry.strip() for entry in paths_raw.splitlines() if entry.strip()]
        if not paths:
            candidate = Path("result.json")
        else:
            first = Path(paths[0])
            candidate = first / "result.json" if first.is_dir() else first.parent / "result.json"

    destination = (workspace / candidate).resolve()
    if not destination.is_relative_to(workspace):
        raise ValueError(
            f"result.json destination '{destination}' escapes "
            f"GITHUB_WORKSPACE '{workspace}'"
        )
    return destination


def main() -> int:
    artifact_name = require("INPUT_ARTIFACT_NAME")
    status = require("INPUT_STATUS")
    paths_raw = env("INPUT_PATHS")
    metadata_file = env("INPUT_METADATA_FILE")
    summary_file = env("INPUT_SUMMARY_FILE")
    redact_spec = env("INPUT_REDACT")

    repository = env("GITHUB_REPOSITORY")
    sha = env("GITHUB_SHA")
    run_id = env("GITHUB_RUN_ID")
    run_attempt = env("GITHUB_RUN_ATTEMPT")
    job = env("GITHUB_JOB")
    server_url = env("GITHUB_SERVER_URL", "https://github.com")

    project = load_project_json(metadata_file)

    # These fields are authoritative from the actual run, not the project's
    # own metadata-file -- overwritten unconditionally so an automated
    # consumer can trust them regardless of what the project script wrote.
    project.update(
        {
            "schema": "private-ci-result-v1",
            "status": status,
            "source_repository": repository,
            "source_sha": sha,
            "workflow_run_id": int(run_id) if run_id.isdigit() else run_id,
            "workflow_run_attempt": int(run_attempt) if run_attempt.isdigit() else run_attempt,
            "job": job,
            "artifact_name": artifact_name,
            "run_url": f"{server_url}/{repository}/actions/runs/{run_id}",
        }
    )

    configured_paths = [p for p in paths_raw.splitlines() if p.strip()]
    if "outputs" not in project or project["outputs"] is None:
        project["outputs"] = [
            {"path": p.strip(), "kind": "unspecified"} for p in configured_paths
        ]
    project.setdefault("details", {})

    summary_text = ""
    if summary_file:
        summary_path = Path(summary_file)
        if summary_path.is_file():
            summary_text = summary_path.read_text(encoding="utf-8")
        else:
            print(
                f"::warning::summary-file '{summary_file}' was configured "
                "but does not exist",
                file=sys.stderr,
            )
    if not summary_text.strip():
        summary_text = default_summary(status)
    project.setdefault("summary", summary_text.strip().splitlines()[0] if summary_text.strip() else "")

    redacted_summary = redact(summary_text, redact_spec)

    result_json_path = result_json_destination(metadata_file, paths_raw)
    result_json_path.parent.mkdir(parents=True, exist_ok=True)
    summary_dir = Path(env("RUNNER_TEMP", ".")) / "ci-result-publisher"
    summary_dir.mkdir(parents=True, exist_ok=True)
    redacted_summary_path = summary_dir / "summary.redacted.md"

    result_json_path.write_text(json.dumps(project, indent=2) + "\n", encoding="utf-8")
    redacted_summary_path.write_text(redacted_summary, encoding="utf-8")

    step_summary_path = env("GITHUB_STEP_SUMMARY")
    step_summary = "\n".join(
        [
            f"## Private CI result: `{status}`",
            "",
            f"- Job: `{job}`",
            f"- Source: `{repository}@{sha[:12]}`",
            f"- Run: {project['run_url']}",
            f"- Artifact: `{artifact_name}`",
            "",
            "### Project summary",
            "",
            redacted_summary.strip() or "_(empty)_",
            "",
        ]
    )
    if step_summary_path:
        with open(step_summary_path, "a", encoding="utf-8") as handle:
            handle.write(step_summary + "\n")

    github_output = env("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as handle:
            handle.write(f"result-json-path={result_json_path}\n")
            handle.write(f"redacted-summary-path={redacted_summary_path}\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
