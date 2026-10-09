#!/usr/bin/env python3
"""The result.json summary field must not keep a redacted secret."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_result.py"
SECRET = "token-should-not-leak"


def run_publisher(root: Path, summary: str, metadata: Optional[str]) -> dict:
    summary_path = root / "summary.md"
    summary_path.write_text(summary, encoding="utf-8")
    metadata_path = ""
    if metadata is not None:
        path = root / "meta.json"
        path.write_text(metadata, encoding="utf-8")
        metadata_path = str(path)
    env = os.environ.copy()
    env.update(
        {
            "INPUT_ARTIFACT_NAME": "evidence",
            "INPUT_STATUS": "success",
            "INPUT_PATHS": "out.txt\n",
            "INPUT_METADATA_FILE": metadata_path,
            "INPUT_SUMMARY_FILE": str(summary_path),
            "INPUT_REDACT": SECRET,
            "RUNNER_TEMP": str(root),
            "GITHUB_OUTPUT": str(root / "github-output"),
            "GITHUB_REPOSITORY": "ahojukka5/example",
            "GITHUB_SHA": "0123456789abcdef",
            "GITHUB_RUN_ID": "9",
            "GITHUB_RUN_ATTEMPT": "1",
            "GITHUB_JOB": "publish",
            "GITHUB_STEP_SUMMARY": "",
        }
    )
    completed = subprocess.run(
        [sys.executable, str(SCRIPT)],
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    result_path = root / "ci-result-publisher" / "result.json"
    raw = result_path.read_text(encoding="utf-8")
    assert SECRET not in raw
    return json.loads(raw)


def test_copied_summary_is_redacted() -> None:
    with tempfile.TemporaryDirectory() as directory:
        result = run_publisher(
            Path(directory),
            f"build used {SECRET} and finished\n",
            None,
        )
        assert result["summary"] == "build used ***REDACTED*** and finished"
        assert SECRET not in result["summary"]


def test_metadata_summary_is_redacted() -> None:
    with tempfile.TemporaryDirectory() as directory:
        result = run_publisher(
            Path(directory),
            "plain summary\n",
            json.dumps({"summary": f"kept {SECRET} in metadata"}),
        )
        assert result["summary"] == "kept ***REDACTED*** in metadata"


def main() -> None:
    test_copied_summary_is_redacted()
    test_metadata_summary_is_redacted()
    print("ok")


if __name__ == "__main__":
    main()
