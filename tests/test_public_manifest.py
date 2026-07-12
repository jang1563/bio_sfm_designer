"""Regression tests for the curated public manifest and surface gate."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from scripts.check_public_manifest import (
    PROHIBITED_PATHS,
    SCHEDULER_CONTEXT,
    check_manifest,
    numeric_job_metadata,
)


ROOT = Path(__file__).resolve().parents[1]


def test_current_public_manifest_and_surface_pass() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/check_public_manifest.py"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK public manifest and surface check passed" in result.stdout


def test_manifest_hashes_and_counts_pass() -> None:
    assert check_manifest() == []


def test_numeric_scheduler_metadata_is_rejected_without_banning_scientific_ids() -> None:
    key = "slurm_" + "job_ids"
    numeric = "123" + "4567"
    payload = {key: [numeric], "mondo_id": "MONDO:0019225", "pmid": 14913280}

    issues = numeric_job_metadata(payload)

    assert issues == ["/slurm_job_ids"]


def test_scheduler_context_and_internal_paths_are_rejected() -> None:
    numeric = "123" + "4567"
    prose = "external HPC Boltz " + "jobs `" + numeric + "` completed"
    internal_path = "docs/" + "CODEX_GOAL_MODE.md"

    assert SCHEDULER_CONTEXT.search(prose)
    assert any(pattern.search(internal_path) for pattern in PROHIBITED_PATHS)
