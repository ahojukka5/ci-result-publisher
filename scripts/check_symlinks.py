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
"""

from __future__ import annotations

import os
import sys


def iter_symlinks(root: str):
    if os.path.islink(root):
        yield root
        return
    if not os.path.isdir(root):
        return
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        for name in dirnames + filenames:
            candidate = os.path.join(dirpath, name)
            if os.path.islink(candidate):
                yield candidate


def main() -> int:
    paths_raw = os.environ.get("INPUT_PATHS", "")
    paths = [p.strip() for p in paths_raw.splitlines() if p.strip()]
    rejected = False
    for path in paths:
        if not os.path.exists(path):
            continue
        root = os.path.realpath(path)
        for link in iter_symlinks(path):
            target = os.path.realpath(link)
            if target == root or target.startswith(root + os.sep):
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
