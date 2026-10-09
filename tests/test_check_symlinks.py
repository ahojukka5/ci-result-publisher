#!/usr/bin/env python3
"""A configured path that is an escaping symlink must be rejected."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_symlinks.py"


def run(workspace: Path, paths: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["GITHUB_WORKSPACE"] = str(workspace)
    env["INPUT_PATHS"] = paths
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=workspace,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )


def test_nested_escape_is_rejected() -> None:
    with tempfile.TemporaryDirectory() as directory:
        workspace = Path(directory)
        folder = workspace / "bundle"
        folder.mkdir()
        (folder / "escape").symlink_to("/etc/passwd")
        completed = run(workspace, "bundle/\n")
        assert completed.returncode == 1, completed.stderr
        assert "escape" in completed.stderr


def test_configured_symlink_outside_workspace_is_rejected() -> None:
    with tempfile.TemporaryDirectory() as directory:
        workspace = Path(directory)
        link = workspace / "outdir"
        link.symlink_to("/etc")
        completed = run(workspace, "outdir/\n")
        assert completed.returncode == 1, completed.stderr
        assert "Configured path" in completed.stderr
        assert "/etc" not in completed.stdout


def test_configured_symlink_inside_workspace_is_allowed() -> None:
    with tempfile.TemporaryDirectory() as directory:
        workspace = Path(directory)
        real = workspace / "real"
        real.mkdir()
        (real / "note.txt").write_text("ok", encoding="utf-8")
        (workspace / "outdir").symlink_to(real)
        completed = run(workspace, "outdir\n")
        assert completed.returncode == 0, completed.stderr


def test_directory_symlink_still_rejects_a_nested_escape() -> None:
    with tempfile.TemporaryDirectory() as directory:
        workspace = Path(directory)
        real = workspace / "real"
        real.mkdir()
        (real / "escape").symlink_to("/etc/passwd")
        (workspace / "outdir").symlink_to(real)
        completed = run(workspace, "outdir\n")
        assert completed.returncode == 1, completed.stderr
        assert "escape" in completed.stderr


def test_configured_dangling_symlink_fails_cleanly() -> None:
    with tempfile.TemporaryDirectory() as directory:
        workspace = Path(directory)
        (workspace / "dangling").symlink_to(workspace / "missing")
        completed = run(workspace, "dangling/\n")
        assert completed.returncode == 1, completed.stderr
        assert "dangling symlink" in completed.stderr
        assert "Traceback" not in completed.stderr


def main() -> None:
    test_nested_escape_is_rejected()
    test_configured_symlink_outside_workspace_is_rejected()
    test_configured_symlink_inside_workspace_is_allowed()
    test_directory_symlink_still_rejects_a_nested_escape()
    test_configured_dangling_symlink_fails_cleanly()
    print("ok")


if __name__ == "__main__":
    main()
