"""Canonical hashing helpers for exact W2 panel approval scope binding."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict


def file_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def scope_sha256(scope: Dict[str, Any]) -> str:
    payload = {key: value for key, value in scope.items() if key != "scope_sha256"}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def bind_scope(scope: Dict[str, Any]) -> Dict[str, Any]:
    bound = dict(scope)
    bound["scope_sha256"] = scope_sha256(bound)
    return bound


def scope_is_bound(scope: Dict[str, Any]) -> bool:
    observed = scope.get("scope_sha256")
    return isinstance(observed, str) and len(observed) == 64 and observed == scope_sha256(scope)


def manifest_target_ids(path: str) -> list[str]:
    manifest = json.loads(Path(path).read_text())
    return [
        str(target.get("id", f"target_{index}"))
        for index, target in enumerate(manifest.get("targets", []))
        if isinstance(target, dict)
    ]
