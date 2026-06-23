"""Campaign logging helpers (thin layer over bio_sfm_trust.io_utils)."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List

from bio_sfm_trust.io_utils import write_jsonl  # re-exported for convenience

__all__ = ["write_jsonl", "write_campaign", "write_summary"]


def write_campaign(rows: List[Dict[str, Any]], path: str) -> str:
    write_jsonl(rows, path)
    return path


def write_summary(summary: Dict[str, Any], path: str) -> str:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as fh:
        json.dump(summary, fh, indent=2, sort_keys=True)
        fh.write("\n")
    return path
