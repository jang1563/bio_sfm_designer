#!/usr/bin/env python3
"""Fail closed on manifest drift or internal public-surface metadata."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path, PurePosixPath

try:
    from .refresh_public_manifest import jsonl_records, sha256_file
except ImportError:  # direct script execution
    from refresh_public_manifest import jsonl_records, sha256_file


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "release" / "public_release_manifest.json"
SHA256 = re.compile(r"^[a-f0-9]{64}$")
PROHIBITED_PATHS = (
    re.compile(r"(^|/)HANDOFF\.md$"),
    re.compile(r"(^|/)CODEX_GOAL_MODE\.md$"),
    re.compile(r"(^|/)M6D_GOAL_MODE_ANCHOR\.md$"),
    re.compile(r"(^|/)M6C_RUNBOOK\.md$"),
    re.compile(r"(^|/)[^/]*APPROVAL[^/]*\.md$"),
    re.compile(r"^results/.*(?:receipt|job_state|postsubmit|sync_back)"),
    re.compile(r"^src/.*/(?:complex_project_status|m6d_goal_[^/]*)\.py$"),
)
SCHEDULER_CONTEXT = re.compile(
    r"(?i)\b(?:slurm|scheduler|hpc|proteinmpnn|boltz)\b[^\n]{0,100}\bjobs?\b[^\n]{0,40}\d{6,12}\b"
)
PERSONAL_PATH = re.compile(
    r"(?:"
    r"/Users/(?!<local-user>(?:/|\b))[A-Za-z0-9._-]+"
    r"|/home/[A-Za-z0-9._-]+/(?!<user>(?:/|\b))[A-Za-z0-9._-]+"
    r"|/scratch/(?!<user>(?:/|\b)|USER(?:/|\b))[A-Za-z0-9._-]+"
    r")"
)
INTERNAL_NOTE = re.compile(
    r"(?i)(?:"
    + re.escape("." + "claude/")
    + "|"
    + re.escape("~/" + ".api_keys")
    + "|"
    + r"rotate\s+the\s+exposed\s+key"
    + "|"
    + r"fresh\s+session\s+handoff"
    + "|"
    + r"codex\s+goal\s+mode"
    + ")"
)


def tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, check=True, capture_output=True, text=True
    )
    return [ROOT / rel for rel in result.stdout.splitlines() if rel and (ROOT / rel).is_file()]


def numeric_job_metadata(value: object, path: str = "") -> list[str]:
    issues: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            child = f"{path}/{key}"
            normalized = key.lower()
            if normalized.endswith("job_id") or normalized.endswith("job_ids"):
                values = item if isinstance(item, list) else [item]
                if any(re.fullmatch(r"\d{6,12}", str(entry)) for entry in values):
                    issues.append(child)
            issues.extend(numeric_job_metadata(item, child))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            issues.extend(numeric_job_metadata(item, f"{path}/{index}"))
    return issues


def check_manifest() -> list[str]:
    issues: list[str] = []
    manifest = json.loads(MANIFEST.read_text())
    for key in (
        "manifest_version",
        "project",
        "version",
        "release_profile",
        "status",
        "visibility",
        "claim_boundaries",
        "included_surface",
        "excluded_surface",
        "artifacts",
    ):
        if key not in manifest:
            issues.append(f"manifest missing key: {key}")
    seen: set[str] = set()
    for artifact in manifest.get("artifacts", []):
        rel = artifact.get("path")
        if not isinstance(rel, str) or not rel:
            issues.append(f"invalid artifact path: {rel!r}")
            continue
        parsed = PurePosixPath(rel)
        if parsed.is_absolute() or ".." in parsed.parts:
            issues.append(f"artifact path escapes repository: {rel}")
            continue
        if rel in seen:
            issues.append(f"duplicate artifact path: {rel}")
        seen.add(rel)
        path = ROOT / rel
        if not path.is_file():
            issues.append(f"artifact missing: {rel}")
            continue
        expected = artifact.get("sha256")
        if not isinstance(expected, str) or not SHA256.fullmatch(expected):
            issues.append(f"artifact missing valid sha256: {rel}")
        elif sha256_file(path) != expected:
            issues.append(f"artifact sha256 mismatch: {rel}")
        if "records" in artifact and jsonl_records(path) != artifact["records"]:
            issues.append(f"artifact record count mismatch: {rel}")
    return issues


def check_surface() -> list[str]:
    issues: list[str] = []
    for path in tracked_files():
        rel = path.relative_to(ROOT).as_posix()
        for pattern in PROHIBITED_PATHS:
            if pattern.search(rel):
                issues.append(f"prohibited public path: {rel}")
                break
        if path.suffix.lower() not in {".json", ".jsonl", ".md", ".py", ".sh", ".sbatch", ".toml", ".yaml", ".yml"}:
            continue
        text = path.read_text(errors="ignore")
        if PERSONAL_PATH.search(text):
            issues.append(f"personal absolute path: {rel}")
        if INTERNAL_NOTE.search(text):
            issues.append(f"internal session or credential note: {rel}")
        if SCHEDULER_CONTEXT.search(text):
            issues.append(f"numeric scheduler context: {rel}")
        if path.suffix == ".json":
            try:
                value = json.loads(text)
            except json.JSONDecodeError as exc:
                issues.append(f"invalid JSON: {rel}: {exc}")
            else:
                for location in numeric_job_metadata(value):
                    issues.append(f"numeric scheduler metadata: {rel}{location}")
    return issues


def main() -> int:
    issues = check_manifest() + check_surface()
    if issues:
        print(f"FAIL public manifest check found {len(issues)} issue(s)")
        for issue in issues:
            print(f"- {issue}")
        return 1
    print("OK public manifest and surface check passed")
    print(f"- tracked files: {len(tracked_files())}")
    print(f"- checksummed artifacts: {len(json.loads(MANIFEST.read_text())['artifacts'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
