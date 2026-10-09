#!/usr/bin/env python3
"""Reject symlinks that escape the configured artifact paths.

Documented policy (see README.md "Security"): a symlink found under one of
the configured `paths` whose resolved target falls outside that same path's
own root is rejected -- the step fails rather than silently uploading
whatever the link happened to point at. This is deliberately the stricter
of the two options the design allows (reject vs. safely dereference): an
artifact that may be made public should never silently gain files from
outside the directory the project asked to publish.

A symlink whose target resolves *inside* the configured root is left alone;
actions/upload-artifact resolves those itself.

A configured path that is itself a symlink is judged against the workspace,
not against its own resolved target. One that leaves the workspace is
rejected and is not walked.
"""

from __future__ import annotations

import os
import sys


def normalize(path: str) -> str:
    stripped = path.rstrip(os.sep)
    return stripped if stripped else path


def inside(root: str, target: str) -> bool:
    return target == root or target.startswith(root + os.sep)


def iter_symlinks(root: str):
    if os.path.islink(root) and not os.path.isdir(root):
        yield root
        return
    if not os.path.isdir(root):
        return
    if os.path.islink(root):
        yield root
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        for name in dirnames + filenames:
            candidate = os.path.join(dirpath, name)
            if os.path.islink(candidate):
                yield candidate


def main() -> int:
    paths_raw = os.environ.get("INPUT_PATHS", "")
    paths = [normalize(p.strip()) for p in paths_raw.splitlines() if p.strip()]
    workspace = os.path.realpath(os.environ.get("GITHUB_WORKSPACE") or os.getcwd())
    rejected = False
    for path in paths:
        if not os.path.lexists(path):
            continue
        if os.path.islink(path):
            if not os.path.exists(path):
                print(
                    f"::error::Configured path '{path}' is a dangling symlink; "
                    "rejecting rather than attempting to follow it.",
                    file=sys.stderr,
                )
                rejected = True
                continue
            target = os.path.realpath(path)
            if not inside(workspace, target):
                print(
                    f"::error::Configured path '{path}' is a symlink that "
                    f"resolves outside the workspace '{workspace}' "
                    f"(-> '{target}'); rejecting per this action's symlink "
                    "policy (see README.md Security section).",
                    file=sys.stderr,
                )
                rejected = True
                continue
        root = os.path.realpath(path)
        for link in iter_symlinks(path):
            if os.path.islink(path) and os.path.samefile(link, path):
                continue
            target = os.path.realpath(link)
            if inside(root, target):
                continue
            print(
                f"::error::Symlink '{link}' resolves outside its configured "
                f"root '{root}' (-> '{target}'); rejecting per this action's "
                "symlink policy (see README.md Security section).",
                file=sys.stderr,
            )
            rejected = True
    return 1 if rejected else 0


if __name__ == "__main__":
    raise SystemExit(main())
