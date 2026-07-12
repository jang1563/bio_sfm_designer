#!/usr/bin/env python3
"""Refresh checksums and JSONL record counts in the public manifest."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "release" / "public_release_manifest.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def jsonl_records(path: Path) -> int:
    count = 0
    for line_no, line in enumerate(path.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        try:
            json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSONL at {path.relative_to(ROOT)}:{line_no}: {exc}") from exc
        count += 1
    return count


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True, help="Explicit YYYY-MM-DD update date")
    args = parser.parse_args()
    update_date = dt.date.fromisoformat(args.date).isoformat()
    if update_date != args.date:
        raise ValueError("--date must use canonical YYYY-MM-DD form")
    manifest = json.loads(MANIFEST.read_text())
    for artifact in manifest["artifacts"]:
        path = ROOT / artifact["path"]
        if not path.is_file():
            raise FileNotFoundError(path)
        artifact["sha256"] = sha256_file(path)
        if path.suffix == ".jsonl":
            artifact["records"] = jsonl_records(path)
    manifest["last_updated"] = update_date
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"refreshed {len(manifest['artifacts'])} public artifacts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
