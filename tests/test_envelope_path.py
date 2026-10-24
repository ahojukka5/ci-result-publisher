#!/usr/bin/env python3
"""The uploaded envelope must stay inside the workspace, not RUNNER_TEMP."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_result.py"


def run(workspace: Path, metadata: str, paths: str) -> Path:
    runner_temp = workspace / "runner-temp"
    runner_temp.mkdir()
    output = workspace / "github-output"
    env = os.environ.copy()
    env.update(
        {
            "INPUT_ARTIFACT_NAME": "evidence",
            "INPUT_STATUS": "success",
            "INPUT_PATHS": paths,
            "INPUT_METADATA_FILE": metadata,
            "INPUT_SUMMARY_FILE": "",
            "INPUT_REDACT": "",
            "RUNNER_TEMP": str(runner_temp),
            "GITHUB_WORKSPACE": str(workspace),
            "GITHUB_OUTPUT": str(output),
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
        cwd=workspace,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    recorded = ""
    for line in output.read_text(encoding="utf-8").splitlines():
        if line.startswith("result-json-path="):
            recorded = line.split("=", 1)[1]
    result_path = Path(recorded)
    if not result_path.is_absolute():
        result_path = workspace / result_path
    assert result_path.is_file()
    assert runner_temp not in result_path.parents
    envelope = json.loads(result_path.read_text(encoding="utf-8"))
    assert envelope["schema"] == "private-ci-result-v1"
    summary = runner_temp / "ci-result-publisher" / "summary.redacted.md"
    assert summary.is_file()
    return result_path


def test_metadata_file_is_overwritten_in_place() -> None:
    with tempfile.TemporaryDirectory() as directory:
        workspace = Path(directory)
        meta_dir = workspace / "ci-result"
        meta_dir.mkdir()
        meta = meta_dir / "result.json"
        meta.write_text('{"details": {"kept": true}}\n', encoding="utf-8")
        written = run(workspace, "ci-result/result.json", "ci-result/\n")
        assert written == meta.resolve()
        envelope = json.loads(meta.read_text(encoding="utf-8"))
        assert envelope["details"] == {"kept": True}
        assert envelope["status"] == "success"


def test_omitted_metadata_lands_next_to_the_paths() -> None:
    with tempfile.TemporaryDirectory() as directory:
        workspace = Path(directory)
        reports = workspace / "reports"
        reports.mkdir()
        (reports / "note.txt").write_text("hello", encoding="utf-8")
        written = run(workspace, "", "reports/\n")
        assert written == (reports / "result.json").resolve()


def test_workspace_escapes_are_rejected() -> None:
    spec = importlib.util.spec_from_file_location("publisher_build_result", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        workspace = root / "workspace"
        outside = root / "outside"
        workspace.mkdir()
        outside.mkdir()
        (workspace / "external").symlink_to(outside, target_is_directory=True)
        cases = (
            ("../outside/result.json", ""),
            (str(outside / "result.json"), ""),
            ("external/result.json", ""),
            ("", str(outside) + "/\\n"),
        )
        with patch.dict(os.environ, {"GITHUB_WORKSPACE": str(workspace)}):
            for metadata, paths in cases:
                try:
                    module.result_json_destination(metadata, paths)
                except ValueError as exc:
                    assert "escapes GITHUB_WORKSPACE" in str(exc)
                else:
                    raise AssertionError(f"unsafe destination accepted: {metadata!r}")
        assert not (outside / "result.json").exists()


def main() -> None:
    test_metadata_file_is_overwritten_in_place()
    test_omitted_metadata_lands_next_to_the_paths()
    test_workspace_escapes_are_rejected()
    print("ok")


if __name__ == "__main__":
    main()
