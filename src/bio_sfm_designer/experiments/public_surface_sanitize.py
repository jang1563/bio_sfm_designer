"""Sanitize tracked public-surface artifacts after local regeneration.

This helper does not submit work or contact remote systems. It rewrites only
selected git-tracked files, defaulting to tracked ``results/`` artifacts, so
environment-specific local/Cayuga paths do not leak into the public GitHub
surface while ignored operator runbooks can still keep executable commands.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from bio_sfm_designer.experiments.public_release_readiness import (
    CAYUGA_HOME_PATH,
    CAYUGA_LOGIN_PREFIX,
    LOCAL_USER_PATH,
)


_DEFAULT_PREFIXES = ("results/",)


def _write_json(path: str, obj: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as fh:
        json.dump(obj, fh, indent=2, sort_keys=True)
        fh.write("\n")


def _write_text(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)


def _tracked_files(root: str) -> Tuple[List[str], Optional[str]]:
    proc = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        check=False,
        capture_output=True,
    )
    if proc.returncode != 0:
        message = proc.stderr.decode("utf-8", errors="replace").strip() or "git ls-files failed"
        return [], message
    files = [
        rel.decode("utf-8", errors="replace")
        for rel in proc.stdout.split(b"\0")
        if rel
    ]
    return files, None


def _candidate(rel_path: str, prefixes: Sequence[str]) -> bool:
    return any(rel_path == prefix.rstrip("/") or rel_path.startswith(prefix) for prefix in prefixes)


def _read_text(path: str) -> Tuple[Optional[str], Optional[str]]:
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError as exc:
        return None, f"read_error:{exc}"
    if b"\0" in data:
        return None, "binary"
    return data.decode("utf-8", errors="replace"), None


def _replacement_patterns(root: str) -> List[Tuple[str, re.Pattern[str], str]]:
    root = os.path.abspath(root)
    return [
        ("repo_root", re.compile(re.escape(root)), "<repo-root>"),
        ("local_user_path", re.compile(re.escape(LOCAL_USER_PATH) + r"\b"), "/Users/<local-user>"),
        ("cayuga_home_path", re.compile(re.escape(CAYUGA_HOME_PATH) + r"\b"), "/home/fs01/<user>"),
        ("cayuga_login_host", re.compile(r"\b" + re.escape(CAYUGA_LOGIN_PREFIX) + r"[0-9]*\b"), "<hpc-login-host>"),
    ]


def _sanitize_text(text: str, *, root: str) -> Tuple[str, Dict[str, int]]:
    counts: Dict[str, int] = {}
    out = text
    for name, pattern, repl in _replacement_patterns(root):
        out, n = pattern.subn(repl, out)
        if n:
            counts[name] = n
    return out, counts


def build_report(
    *,
    root: str = ".",
    prefixes: Sequence[str] = _DEFAULT_PREFIXES,
    apply: bool = False,
) -> Dict[str, Any]:
    root = os.path.abspath(root)
    tracked, error = _tracked_files(root)
    failures: List[Dict[str, Any]] = []
    if error:
        failures.append({
            "kind": "tracked_file_scan_unavailable",
            "message": error,
        })
        tracked = []

    scanned = 0
    changed: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    for rel in sorted(tracked):
        if not _candidate(rel, prefixes):
            continue
        path = os.path.join(root, rel)
        text, reason = _read_text(path)
        if text is None:
            skipped.append({"path": rel, "reason": reason})
            continue
        scanned += 1
        sanitized, counts = _sanitize_text(text, root=root)
        if not counts:
            continue
        changed.append({"path": rel, "replacements": counts})
        if apply:
            _write_text(path, sanitized)

    status = "public_surface_sanitized" if apply else "public_surface_sanitize_dry_run"
    if failures:
        status = "public_surface_sanitize_blocked"
    elif changed and not apply:
        status = "public_surface_sanitize_needed"
    return {
        "artifact": "public_surface_sanitize",
        "status": status,
        "audit_ok": not failures,
        "apply": apply,
        "root": root,
        "prefixes": list(prefixes),
        "tracked_file_count": len(tracked),
        "scanned_file_count": scanned,
        "changed_file_count": len(changed),
        "changed_files": changed,
        "skipped_files": skipped,
        "failures": failures,
        "claim_boundary": "local public-surface cleanup only; does not submit jobs or alter ignored private runbooks",
    }


def render_markdown(rep: Dict[str, Any]) -> str:
    lines = [
        "# Public Surface Sanitizer",
        "",
        f"Status: `{rep.get('status')}`.",
        f"Audit ok: `{rep.get('audit_ok')}`.",
        f"Apply: `{rep.get('apply')}`.",
        f"Scanned files: `{rep.get('scanned_file_count')}`.",
        f"Changed files: `{rep.get('changed_file_count')}`.",
        "",
        "## Changed Files",
        "",
    ]
    changed = rep.get("changed_files") if isinstance(rep.get("changed_files"), list) else []
    if not changed:
        lines.append("- none")
    for row in changed:
        lines.append(f"- `{row.get('path')}`: `{row.get('replacements')}`")
    lines.extend(["", "## Failures", ""])
    failures = rep.get("failures") if isinstance(rep.get("failures"), list) else []
    if not failures:
        lines.append("- none")
    for failure in failures:
        lines.append(f"- `{failure.get('kind')}`: {failure.get('message') or failure}")
    lines.append("")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".")
    ap.add_argument("--path-prefix", action="append", dest="prefixes", default=None)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--out-json", default="results/public_surface_sanitize.json")
    ap.add_argument("--out-md", default="results/public_surface_sanitize.md")
    args = ap.parse_args(argv)

    rep = build_report(
        root=args.root,
        prefixes=tuple(args.prefixes or _DEFAULT_PREFIXES),
        apply=args.apply,
    )
    _write_json(args.out_json, rep)
    _write_text(args.out_md, render_markdown(rep))
    print(render_markdown(rep))
    print(f"wrote {args.out_json}")
    print(f"wrote {args.out_md}")
    return 0 if rep.get("audit_ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
