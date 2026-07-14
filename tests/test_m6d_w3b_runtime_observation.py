"""Tests for W3b runtime observation and shared structure metrics."""

from __future__ import annotations

import hashlib
import json
import numpy as np
import pytest

from bio_sfm_designer.experiments.m6d_w3b_runtime_observation import (
    canonical_distribution_manifest,
    observe_af2,
)
from bio_sfm_designer.experiments.m6d_w3b_structure_metrics import (
    interface_pae,
    lrmsd,
)


def test_distribution_manifest_is_canonical_and_excludes_pyc(tmp_path):
    first = tmp_path / "a.py"
    second = tmp_path / "b.json"
    ignored = tmp_path / "cache.pyc"
    first.write_text("a = 1\n")
    second.write_text("{}\n")
    ignored.write_bytes(b"ignored")
    files = [("b.json", second), ("cache.pyc", ignored), ("a.py", first)]

    count, digest = canonical_distribution_manifest(files)
    rows = [{
        "path": name,
        "bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    } for name, path in (("a.py", first), ("b.json", second))]
    expected = hashlib.sha256(
        json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()

    assert count == 2
    assert digest == expected


def test_af2_observation_hashes_container_and_all_five_weights(tmp_path):
    runtime = tmp_path / "colabfold.sif"
    runtime.write_bytes(b"runtime")
    params = tmp_path / "data" / "params"
    params.mkdir(parents=True)
    (params / "download_complexes_multimer_v3_finished.txt").write_text("ok\n")
    for index in range(1, 6):
        (params / f"params_model_{index}_multimer_v3.npz").write_bytes(f"weight-{index}".encode())

    identity = observe_af2(runtime, tmp_path / "data", "1.6.1")

    assert identity["predictor_id"] == "af2_multimer_colabfold_v1"
    assert identity["container_sha256"] == hashlib.sha256(b"runtime").hexdigest()
    assert len(identity["weights"]) == 5
    assert identity["execution_parameters"]["random_seed"] == 0
    assert identity["execution_parameters"]["prediction_time_network_used"] is False


def test_af2_observation_rejects_version_drift(tmp_path):
    runtime = tmp_path / "colabfold.sif"
    runtime.write_bytes(b"runtime")
    with pytest.raises(ValueError, match="1.6.1 is required"):
        observe_af2(runtime, tmp_path / "missing", "1.6.0")


def test_target_aligned_lrmsd_and_interface_pae():
    target = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
    binder = [(0.0, 0.0, 1.0), (1.0, 0.0, 1.0)]
    translated_target = [(x + 5.0, y - 3.0, z + 2.0) for x, y, z in target]
    translated_binder = [(x + 5.0, y - 3.0, z + 2.0) for x, y, z in binder]
    pae = np.asarray([
        [0.0, 0.0, 2.0, 4.0],
        [0.0, 0.0, 6.0, 8.0],
        [10.0, 12.0, 0.0, 0.0],
        [14.0, 16.0, 0.0, 0.0],
    ])

    assert lrmsd(translated_target, translated_binder, target, binder) == pytest.approx(0.0)
    assert interface_pae(pae, 2) == pytest.approx(9.0)


def test_structure_metrics_reject_nonfinite_pae():
    pae = np.zeros((4, 4), dtype=float)
    pae[0, 3] = np.nan
    with pytest.raises(ValueError, match="invalid pAE"):
        interface_pae(pae, 2)
