"""Audit whether the repo is ready to become a public research artifact.

This tool does not publish anything. It checks the public surface for release
blockers: missing governance files, credential-shaped strings, private
infrastructure breadcrumbs, and missing scientific claim boundaries.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import subprocess
from typing import Any, Dict, Iterable, List, Optional, Pattern, Sequence, Tuple


REQUIRED_PUBLIC_FILES = [
    "README.md",
    "LICENSE",
    "pyproject.toml",
    "SECURITY.md",
    "CITATION.cff",
    "CONTRIBUTING.md",
    ".github/workflows/ci.yml",
]

RECOMMENDED_PUBLIC_FILES = [
    "docs/ARCHITECTURE.md",
    "docs/BACKGROUND.md",
    "docs/PROJECT_ROADMAP.md",
]

EXCLUDED_DIR_NAMES = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "hpc_outputs",
    "venv",
}

EXCLUDED_GLOBS = [
    "*.egg-info/*",
    "*.pyc",
    "*.pyo",
    "*.so",
    "*.dylib",
    "*.png",
    "*.jpg",
    "*.jpeg",
    "*.gif",
    "*.pdf",
    "*.pdb",
    "*.a3m",
]

SECRET_PATTERNS: Sequence[Tuple[str, Pattern[str]]] = [
    ("anthropic_api_key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b")),
    ("openai_project_key", re.compile(r"\bsk-proj-[A-Za-z0-9_-]{20,}\b")),
    ("openai_api_key", re.compile(r"\bsk-[A-Za-z0-9]{32,}\b")),
    ("github_classic_token", re.compile(r"\bghp_[A-Za-z0-9_]{20,}\b")),
    ("github_fine_grained_token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b")),
    ("huggingface_token", re.compile(r"\bhf_[A-Za-z0-9]{20,}\b")),
    ("aws_access_key_id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("private_key_block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
]

LOCAL_USER_PATH = "/" + "Users" + "/" + "jak4013"
CAYUGA_HOME_PATH = "/" + "home" + "/" + "fs01" + "/" + "jak4013"
CAYUGA_LOGIN_PREFIX = "cayuga-" + "login"
PRIVATE_GITHUB_PHRASE = "private " + "GitHub"

INTERNAL_PATTERNS: Sequence[Tuple[str, Pattern[str]]] = [
    ("local_absolute_path", re.compile(re.escape(LOCAL_USER_PATH) + r"\b")),
    ("cayuga_home_path", re.compile(re.escape(CAYUGA_HOME_PATH) + r"\b")),
    ("cayuga_login_host", re.compile(r"\b" + re.escape(CAYUGA_LOGIN_PREFIX) + r"[0-9]*\b")),
    ("private_github_context", re.compile(r"\b" + re.escape(PRIVATE_GITHUB_PHRASE) + r"\b", re.IGNORECASE)),
]

PUBLIC_SENSITIVE_NOTE_PATTERNS: Sequence[Tuple[str, Pattern[str]]] = [
    ("exposed_key_incident_note", re.compile(r"exposed\s+[`'\"]?sk-ant-", re.IGNORECASE)),
    ("live_key_rotation_note", re.compile(r"exposed\s+API\s+key|key\s+is\s+rotated", re.IGNORECASE)),
]

CLAIM_BOUNDARY_CHECKS: Sequence[Tuple[str, Sequence[str], str]] = [
    (
        "not_publication_plan",
        ("not a publication plan", "not publication"),
        "Public surface should frame this as a research-engine project, not a publication package.",
    ),
    (
        "external_trust_gate",
        ("external calibrated trust gate", "external trust gate"),
        "Public surface should make clear that trust is owned by an external calibrated gate.",
    ),
    (
        "w2_not_generalization",
        ("not w2 generalization", "not a w2 generalization", "w2 generalization evidence"),
        "W2 public wording must not imply a multi-target generalization result.",
    ),
    (
        "pooled_only_not_proof",
        ("pooled-only evidence is not", "pooled-only evidence"),
        "Pooled diagnostics must be explicitly separated from target-wise proof.",
    ),
    (
        "w3_not_supported",
        ("independent-predictor robustness is not supported", "w3 independent-predictor robustness is not supported"),
        "Second-predictor robustness should stay negative/unsupported unless new evidence changes it.",
    ),
]


def _write_json(path: str, obj: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as fh:
        json.dump(obj, fh, indent=2, sort_keys=True)
        fh.write("\n")


def _write_text(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)


def _relpath(root: str, path: str) -> str:
    return os.path.relpath(path, root).replace(os.sep, "/")


def _is_excluded(relpath: str, *, include_results: bool) -> bool:
    parts = relpath.split("/")
    if not include_results and parts and parts[0] == "results":
        return True
    if any(part in EXCLUDED_DIR_NAMES for part in parts):
        return True
    return any(fnmatch.fnmatch(relpath, pattern) for pattern in EXCLUDED_GLOBS)


def _iter_files(root: str, *, include_results: bool) -> Iterable[str]:
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = _relpath(root, dirpath)
        kept_dirnames = []
        for name in dirnames:
            rel = name if rel_dir == "." else f"{rel_dir}/{name}"
            if not _is_excluded(rel, include_results=include_results):
                kept_dirnames.append(name)
        dirnames[:] = kept_dirnames
        for filename in filenames:
            path = os.path.join(dirpath, filename)
            rel = _relpath(root, path)
            if not _is_excluded(rel, include_results=include_results):
                yield path


def _tracked_file_paths(root: str, *, include_results: bool) -> Tuple[List[str], Optional[str]]:
    proc = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        check=False,
        capture_output=True,
    )
    if proc.returncode != 0:
        message = proc.stderr.decode("utf-8", errors="replace").strip() or "git ls-files failed"
        return [], message
    paths = []
    for rel_bytes in proc.stdout.split(b"\0"):
        if not rel_bytes:
            continue
        rel = rel_bytes.decode("utf-8", errors="replace")
        if not _is_excluded(rel, include_results=include_results):
            paths.append(os.path.join(root, rel))
    return paths, None


def _read_text(path: str, *, max_bytes: int) -> Tuple[Optional[str], Optional[str]]:
    try:
        size = os.path.getsize(path)
    except OSError as exc:
        return None, f"stat_error:{exc}"
    if size > max_bytes:
        return None, f"too_large:{size}"
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError as exc:
        return None, f"read_error:{exc}"
    if b"\0" in data:
        return None, "binary"
    return data.decode("utf-8", errors="replace"), None


def _redact_line(line: str) -> str:
    out = line.strip()
    out = out.replace(LOCAL_USER_PATH, "/Users/<local-user>")
    out = out.replace(CAYUGA_HOME_PATH, "/home/fs01/<user>")
    for _kind, pattern in SECRET_PATTERNS:
        out = pattern.sub(lambda m: f"{m.group(0)[:8]}...REDACTED", out)
    out = re.sub(r"sk-ant-[A-Za-z0-9_-]*", "sk-ant-...REDACTED", out)
    return out[:220]


def _is_synthetic_test_internal_context_line(rel: str, line: str) -> bool:
    if not rel.startswith("tests/"):
        return False
    synthetic_markers = (
        "<user>",
        "<local-user>",
        "<hpc-login-host>",
        "/remote/root",
        "private_user_",
        CAYUGA_LOGIN_PREFIX + "-private",
    )
    return any(marker in line for marker in synthetic_markers)


def _line_findings(
    *,
    root: str,
    path: str,
    text: str,
    patterns: Sequence[Tuple[str, Pattern[str]]],
    category: str,
    severity: str,
) -> List[Dict[str, Any]]:
    findings = []
    rel = _relpath(root, path)
    for line_no, line in enumerate(text.splitlines(), start=1):
        for kind, pattern in patterns:
            if pattern.search(line):
                if category == "internal_context" and _is_synthetic_test_internal_context_line(rel, line):
                    continue
                finding_severity = "warning" if category == "internal_context" and rel.startswith("tests/") else severity
                findings.append({
                    "severity": finding_severity,
                    "category": category,
                    "kind": kind,
                    "path": rel,
                    "line": line_no,
                    "snippet": _redact_line(line),
                })
    return findings


def _scan_files(root: str, *, include_results: bool, max_bytes: int, tracked_only: bool) -> Dict[str, Any]:
    findings: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    scanned_files = 0
    if tracked_only:
        paths, tracked_error = _tracked_file_paths(root, include_results=include_results)
        if tracked_error:
            findings.append({
                "severity": "blocker",
                "category": "scan_scope",
                "kind": "tracked_file_scan_unavailable",
                "message": f"Could not enumerate git-tracked files: {tracked_error}",
            })
            skipped.append({"path": ".", "reason": "git_ls_files_failed"})
            paths = []
    else:
        paths = list(_iter_files(root, include_results=include_results))
    for path in sorted(paths):
        text, reason = _read_text(path, max_bytes=max_bytes)
        rel = _relpath(root, path)
        if text is None:
            skipped.append({"path": rel, "reason": reason})
            continue
        scanned_files += 1
        findings.extend(_line_findings(
            root=root,
            path=path,
            text=text,
            patterns=SECRET_PATTERNS,
            category="credential",
            severity="blocker",
        ))
        findings.extend(_line_findings(
            root=root,
            path=path,
            text=text,
            patterns=INTERNAL_PATTERNS,
            category="internal_context",
            severity="blocker",
        ))
        findings.extend(_line_findings(
            root=root,
            path=path,
            text=text,
            patterns=PUBLIC_SENSITIVE_NOTE_PATTERNS,
            category="public_sensitive_note",
            severity="blocker",
        ))
    return {
        "scanned_files": scanned_files,
        "skipped_files": skipped,
        "findings": findings,
    }


def _file_presence(root: str) -> Dict[str, Any]:
    findings = []
    required = []
    recommended = []
    for rel in REQUIRED_PUBLIC_FILES:
        exists = os.path.exists(os.path.join(root, rel))
        required.append({"path": rel, "exists": exists})
        if not exists:
            findings.append({
                "severity": "blocker",
                "category": "missing_public_file",
                "kind": "missing_required_public_file",
                "path": rel,
                "message": f"Required public-release file is missing: {rel}",
            })
    for rel in RECOMMENDED_PUBLIC_FILES:
        exists = os.path.exists(os.path.join(root, rel))
        recommended.append({"path": rel, "exists": exists})
        if not exists:
            findings.append({
                "severity": "warning",
                "category": "missing_public_file",
                "kind": "missing_recommended_public_file",
                "path": rel,
                "message": f"Recommended public-release file is missing: {rel}",
            })
    return {"required": required, "recommended": recommended, "findings": findings}


def _claim_corpus(root: str) -> str:
    chunks = []
    for rel in ("README.md", "HANDOFF.md", "docs/PROJECT_ROADMAP.md", "docs/CODEX_GOAL_MODE.md"):
        path = os.path.join(root, rel)
        if not os.path.exists(path):
            continue
        text, _reason = _read_text(path, max_bytes=2_000_000)
        if text:
            chunks.append(text.lower())
    return "\n".join(chunks)


def _claim_boundary_findings(root: str) -> Dict[str, Any]:
    corpus = _claim_corpus(root)
    checks = []
    findings = []
    for check_id, needles, message in CLAIM_BOUNDARY_CHECKS:
        present = any(needle in corpus for needle in needles)
        checks.append({"id": check_id, "present": present, "message": message})
        if not present:
            findings.append({
                "severity": "blocker",
                "category": "claim_boundary",
                "kind": f"missing_{check_id}",
                "message": message,
            })
    return {"checks": checks, "findings": findings}


def _dependency_findings(root: str) -> Dict[str, Any]:
    path = os.path.join(root, "pyproject.toml")
    text, reason = _read_text(path, max_bytes=500_000) if os.path.exists(path) else (None, "missing")
    checks = []
    findings = []
    if text is None:
        checks.append({"id": "pyproject_dependency_readable", "present": False, "reason": reason})
        return {"checks": checks, "findings": findings}

    has_trust_dep = "bio-sfm-trust" in text
    has_public_git_dep = (
        "bio-sfm-trust @ git+https://github.com/jang1563/bio-sfm-trust-core.git" in text
    )
    bare_dep = bool(re.search(r"dependencies\s*=\s*\[[^\]]*[\"']bio-sfm-trust[\"']", text, re.S))
    checks.append({
        "id": "bio_sfm_trust_dependency_public_installable",
        "present": (not has_trust_dep) or has_public_git_dep,
        "has_trust_dep": has_trust_dep,
        "has_public_git_dep": has_public_git_dep,
        "bare_dep": bare_dep,
    })
    if has_trust_dep and not has_public_git_dep:
        findings.append({
            "severity": "blocker",
            "category": "dependency_access",
            "kind": "bio_sfm_trust_dependency_not_public_installable",
            "path": "pyproject.toml",
            "message": (
                "bio-sfm-trust is not published on PyPI; public installs need a "
                "GitHub direct dependency or a documented preinstall step."
            ),
        })
    return {"checks": checks, "findings": findings}


def _git_status(root: str) -> Optional[Dict[str, Any]]:
    try:
        proc = subprocess.run(
            ["git", "status", "--short"],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        return {"ok": False, "error": str(exc), "dirty": None, "n_changed": None}
    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    return {
        "ok": proc.returncode == 0,
        "dirty": bool(lines),
        "n_changed": len(lines),
        "sample": lines[:30],
    }


def _visibility_findings(repo_visibility: str) -> List[Dict[str, Any]]:
    if repo_visibility == "private":
        return [{
            "severity": "blocker",
            "category": "repository_visibility",
            "kind": "repository_not_publicly_visible",
            "message": "Repository is currently private or not visible to unauthenticated public API checks.",
        }]
    if repo_visibility == "unknown":
        return [{
            "severity": "warning",
            "category": "repository_visibility",
            "kind": "repository_visibility_unknown",
            "message": "Repository public/private status was not supplied to the audit.",
        }]
    return []


def _next_actions(findings: Sequence[Dict[str, Any]]) -> List[str]:
    categories = {f.get("category") for f in findings if f.get("severity") == "blocker"}
    kinds = {f.get("kind") for f in findings if f.get("severity") == "blocker"}
    actions = []
    if "repository_visibility" in categories:
        actions.append("Keep the repo private until the content blockers below are cleared, then flip visibility deliberately.")
    if "missing_required_public_file" in kinds:
        actions.append("Add public governance files: SECURITY.md, CITATION.cff, CONTRIBUTING.md, and CI.")
    if "credential" in categories or "public_sensitive_note" in categories:
        actions.append("Remove or rewrite credential/key-incident notes from public docs; rotate any real exposed keys out-of-band.")
    if "internal_context" in categories:
        actions.append("Move internal handoff/HPC breadcrumbs to a private runbook or sanitize them for public reproducibility.")
    if "claim_boundary" in categories:
        actions.append("Repair README/HANDOFF/roadmap wording so unsupported W2/W3 claims remain explicitly unsupported.")
    if not actions:
        actions.append("Run the full test suite and publish from a clean release branch with this audit artifact attached.")
    return actions


def build_audit(
    root: str = ".",
    *,
    repo_visibility: str = "unknown",
    include_results: bool = False,
    tracked_only: bool = False,
    check_git_status: bool = False,
    max_bytes: int = 1_500_000,
) -> Dict[str, Any]:
    root = os.path.abspath(root)
    presence = _file_presence(root)
    scan = _scan_files(root, include_results=include_results, max_bytes=max_bytes, tracked_only=tracked_only)
    claim_boundaries = _claim_boundary_findings(root)
    dependencies = _dependency_findings(root)

    findings = []
    findings.extend(_visibility_findings(repo_visibility))
    findings.extend(presence["findings"])
    findings.extend(scan["findings"])
    findings.extend(claim_boundaries["findings"])
    findings.extend(dependencies["findings"])

    git = None
    if check_git_status:
        git = _git_status(root)
        if git and git.get("dirty"):
            findings.append({
                "severity": "warning",
                "category": "git_state",
                "kind": "dirty_worktree",
                "message": f"Working tree has {git.get('n_changed')} changed paths; cut public releases from a clean branch.",
            })

    blockers = [f for f in findings if f.get("severity") == "blocker"]
    warnings = [f for f in findings if f.get("severity") == "warning"]
    public_ready = not blockers
    score = max(0, 100 - (12 * len(blockers)) - (3 * len(warnings)))
    return {
        "artifact": "public_release_readiness_audit",
        "status": (
            "public_release_ready"
            if public_ready and not warnings
            else "public_release_ready_with_warnings"
            if public_ready
            else "public_release_blocked"
        ),
        "audit_ok": public_ready,
        "public_ready": public_ready,
        "readiness_score": score,
        "root": root,
        "repo_visibility": repo_visibility,
        "scope": {
            "include_results": include_results,
            "tracked_only": tracked_only,
            "max_bytes": max_bytes,
            "check_git_status": check_git_status,
        },
        "summary": {
            "n_blockers": len(blockers),
            "n_warnings": len(warnings),
            "n_findings": len(findings),
            "scanned_files": scan["scanned_files"],
            "skipped_files": len(scan["skipped_files"]),
        },
        "file_presence": {
            "required": presence["required"],
            "recommended": presence["recommended"],
        },
        "claim_boundaries": claim_boundaries["checks"],
        "dependency_checks": dependencies["checks"],
        "findings": findings,
        "skipped_files": scan["skipped_files"][:100],
        "git_status": git,
        "next_actions": _next_actions(findings),
    }


def render_markdown(rep: Dict[str, Any]) -> str:
    summary = rep.get("summary") if isinstance(rep.get("summary"), dict) else {}
    lines = [
        "# Public Release Readiness Audit",
        "",
        f"Status: `{rep.get('status')}`.",
        f"Audit ok: `{rep.get('audit_ok')}`.",
        f"Public ready: `{rep.get('public_ready')}`.",
        f"Readiness score: `{rep.get('readiness_score')}`.",
        "",
        "## Summary",
        "",
        f"- repo visibility: `{rep.get('repo_visibility')}`",
        f"- blockers: `{summary.get('n_blockers')}`",
        f"- warnings: `{summary.get('n_warnings')}`",
        f"- scanned files: `{summary.get('scanned_files')}`",
        f"- skipped files: `{summary.get('skipped_files')}`",
        "",
        "## Blockers",
        "",
    ]
    blockers = [f for f in rep.get("findings", []) if f.get("severity") == "blocker"]
    if not blockers:
        lines.append("- none")
    for finding in blockers[:50]:
        loc = finding.get("path") or "(repo)"
        if finding.get("line"):
            loc = f"{loc}:{finding.get('line')}"
        detail = finding.get("message") or finding.get("snippet") or ""
        lines.append(f"- `{finding.get('kind')}` at `{loc}`: {detail}")
    if len(blockers) > 50:
        lines.append(f"- ... {len(blockers) - 50} more blockers omitted from markdown; see JSON.")

    warnings = [f for f in rep.get("findings", []) if f.get("severity") == "warning"]
    lines.extend(["", "## Warnings", ""])
    if not warnings:
        lines.append("- none")
    for finding in warnings[:25]:
        loc = finding.get("path") or "(repo)"
        detail = finding.get("message") or finding.get("snippet") or ""
        lines.append(f"- `{finding.get('kind')}` at `{loc}`: {detail}")
    if len(warnings) > 25:
        lines.append(f"- ... {len(warnings) - 25} more warnings omitted from markdown; see JSON.")

    lines.extend(["", "## Next Actions", ""])
    for action in rep.get("next_actions", []):
        lines.append(f"- {action}")
    lines.append("")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".")
    ap.add_argument("--repo-visibility", choices=("unknown", "private", "public"), default="unknown")
    ap.add_argument("--include-results", action="store_true")
    ap.add_argument("--tracked-only", action="store_true")
    ap.add_argument("--check-git-status", action="store_true")
    ap.add_argument("--max-bytes", type=int, default=1_500_000)
    ap.add_argument("--out-json", default="results/public_release_readiness_audit.json")
    ap.add_argument("--out-md", default="results/public_release_readiness_audit.md")
    args = ap.parse_args(argv)

    rep = build_audit(
        args.root,
        repo_visibility=args.repo_visibility,
        include_results=args.include_results,
        tracked_only=args.tracked_only,
        check_git_status=args.check_git_status,
        max_bytes=args.max_bytes,
    )
    _write_json(args.out_json, rep)
    _write_text(args.out_md, render_markdown(rep))
    print(render_markdown(rep))
    print(f"wrote {args.out_json}")
    print(f"wrote {args.out_md}")
    return 0 if rep.get("audit_ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
