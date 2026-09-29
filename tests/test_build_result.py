#!/usr/bin/env python3
"""load_project_json must not crash the publisher on non-object JSON."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_result.py"


def load_module():
    spec = importlib.util.spec_from_file_location("build_result", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_non_object_metadata_falls_back() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "meta.json"
        for payload in ("[]", "null", '"ok"', "1", "true"):
            path.write_text(payload, encoding="utf-8")
            assert module.load_project_json(str(path)) == {}


def test_object_metadata_is_kept() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "meta.json"
        path.write_text('{"details": {"rows": 2}}\n', encoding="utf-8")
        loaded = module.load_project_json(str(path))
        assert loaded == {"details": {"rows": 2}}


def test_main_publishes_default_envelope_for_a_list() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        meta = root / "meta.json"
        meta.write_text("[]\n", encoding="utf-8")
        output = root / "github-output"
        env = os.environ.copy()
        env.update(
            {
                "INPUT_ARTIFACT_NAME": "evidence",
                "INPUT_STATUS": "success",
                "INPUT_PATHS": "out.txt\n",
                "INPUT_METADATA_FILE": str(meta),
                "INPUT_SUMMARY_FILE": "",
                "INPUT_REDACT": "",
                "RUNNER_TEMP": str(root),
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
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 0, completed.stderr
        assert "not an object" in completed.stderr
        result = json.loads(
            (root / "ci-result-publisher" / "result.json").read_text(encoding="utf-8")
        )
        assert result["schema"] == "private-ci-result-v1"
        assert result["status"] == "success"
        assert result["outputs"] == [{"path": "out.txt", "kind": "unspecified"}]


def main() -> None:
    test_non_object_metadata_falls_back()
    test_object_metadata_is_kept()
    test_main_publishes_default_envelope_for_a_list()
    print("ok")


if __name__ == "__main__":
    main()
