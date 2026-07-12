#!/usr/bin/env python3
"""Scan every commit reachable from HEAD for the public-surface boundary."""

from __future__ import annotations

import json
import subprocess
from pathlib import PurePosixPath

try:
    from .check_public_manifest import (
        INTERNAL_NOTE,
        PERSONAL_PATH,
        PROHIBITED_PATHS,
        SCHEDULER_CONTEXT,
        numeric_job_metadata,
    )
except ImportError:  # direct script execution
    from check_public_manifest import (
        INTERNAL_NOTE,
        PERSONAL_PATH,
        PROHIBITED_PATHS,
        SCHEDULER_CONTEXT,
        numeric_job_metadata,
    )


TEXT_SUFFIXES = {
    ".json",
    ".jsonl",
    ".md",
    ".py",
    ".sh",
    ".sbatch",
    ".toml",
    ".yaml",
    ".yml",
}


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], check=True, capture_output=True, text=True
    ).stdout


def main() -> int:
    issues: list[str] = []
    commits = [value for value in git("rev-list", "HEAD").splitlines() if value]
    for commit in commits:
        paths = [
            value
            for value in git("ls-tree", "-r", "--name-only", commit).splitlines()
            if value
        ]
        for rel in paths:
            if any(pattern.search(rel) for pattern in PROHIBITED_PATHS):
                issues.append(f"{commit[:12]} prohibited historical path: {rel}")
                continue
            if PurePosixPath(rel).suffix.lower() not in TEXT_SUFFIXES:
                continue
            blob = git("show", f"{commit}:{rel}")
            if PERSONAL_PATH.search(blob):
                issues.append(f"{commit[:12]} personal path in {rel}")
            if INTERNAL_NOTE.search(blob):
                issues.append(f"{commit[:12]} internal note in {rel}")
            if SCHEDULER_CONTEXT.search(blob):
                issues.append(f"{commit[:12]} numeric scheduler context in {rel}")
            if rel.endswith(".json"):
                try:
                    value = json.loads(blob)
                except json.JSONDecodeError:
                    continue
                if numeric_job_metadata(value):
                    issues.append(f"{commit[:12]} numeric scheduler metadata in {rel}")
    if issues:
        print(f"FAIL public history check found {len(issues)} issue(s)")
        for issue in issues[:100]:
            print(f"- {issue}")
        if len(issues) > 100:
            print(f"- ... {len(issues) - 100} additional issue(s)")
        return 1
    print("OK public history check passed")
    print(f"- reachable commits: {len(commits)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
