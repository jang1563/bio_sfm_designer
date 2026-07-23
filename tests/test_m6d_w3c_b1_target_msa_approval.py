"""Tests for the hash-bound, no-submit W3c-B1 target-MSA packet."""

import copy
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile

from bio_sfm_designer.experiments.m6d_w3c_b1_target_msa_approval import (
    APPROVAL_ENV,
    APPROVAL_PHRASE,
    APPROVAL_TOKEN,
    TARGET_IDS,
    build_execution_manifest,
)
from bio_sfm_designer.experiments.m6d_w3c_b1_target_msa_preflight import run_preflight


ROOT = pathlib.Path(__file__).resolve().parents[1]
LOCKED_MANIFEST_PATH = ROOT / "configs/m6d_w3c_fresh_targets.json"
FRESH_LOCK_PATH = ROOT / "results/m6d_w3c_fresh_target_lock.json"
PROTOCOL_PATH = ROOT / "configs/m6d_w3c_validity_first_protocol.json"
EXECUTION_MANIFEST_PATH = ROOT / "configs/m6d_w3c_b1_target_msa_manifest.json"
PACKET_PATH = ROOT / "results/m6d_w3c_b1_target_msa_approval_packet.json"
MANIFEST_AUDIT_PATH = ROOT / "results/m6d_w3c_b1_target_manifest_pre_msa.json"
WRAPPER_PATH = ROOT / "hpc/run_w3c_b1_target_msa_guarded.sh"
FIXTURE_PATH = ROOT / "tests/fixtures/m6d_w3c_fresh_structure_fixture.json"


def _load(path):
    return json.loads(path.read_text())


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_ca_pdb(path, fixture_row):
    aa3 = {
        "A": "ALA", "C": "CYS", "D": "ASP", "E": "GLU", "F": "PHE",
        "G": "GLY", "H": "HIS", "I": "ILE", "K": "LYS", "L": "LEU",
        "M": "MET", "N": "ASN", "P": "PRO", "Q": "GLN", "R": "ARG",
        "S": "SER", "T": "THR", "V": "VAL", "W": "TRP", "Y": "TYR",
    }
    selected = fixture_row["selected_sequences"]
    chain_cas = fixture_row["structure"]["chain_cas"]
    sequence_by_chain = {
        selected["target_chain"]: selected["target_sequence"],
        selected["binder_chain"]: selected["binder_sequence"],
    }
    lines = []
    serial = 1
    for chain in (selected["target_chain"], selected["binder_chain"]):
        sequence = sequence_by_chain[chain]
        coordinates = chain_cas[chain]
        assert len(sequence) == len(coordinates)
        for index, (amino_acid, coordinate) in enumerate(zip(sequence, coordinates), 1):
            _resseq, _icode, x, y, z = coordinate
            lines.append(
                f"ATOM  {serial:5d}  CA  {aa3[amino_acid]:>3} {chain}{index:4d}    "
                f"{x:8.3f}{y:8.3f}{z:8.3f}  1.00 20.00           C\n"
            )
            serial += 1
    lines.append("END\n")
    path.write_text("".join(lines))


def test_execution_manifest_is_exact_deterministic_derivation():
    generated = build_execution_manifest(
        _load(LOCKED_MANIFEST_PATH),
        _load(FRESH_LOCK_PATH),
        _load(PROTOCOL_PATH),
        locked_manifest_path=str(LOCKED_MANIFEST_PATH.relative_to(ROOT)),
        fresh_lock_path=str(FRESH_LOCK_PATH.relative_to(ROOT)),
        protocol_path=str(PROTOCOL_PATH.relative_to(ROOT)),
    )

    assert generated == _load(EXECUTION_MANIFEST_PATH)


def test_packet_is_ready_but_authorizes_zero_queries_now():
    packet = _load(PACKET_PATH)

    assert packet["status"] == "w3c_b1_packet_prepared_cayuga_no_submit_validation_required"
    assert packet["approval_packet_ready"] is True
    assert packet["approval_recorded"] is False
    assert packet["submission_performed"] is False
    assert packet["required_user_phrase"] == APPROVAL_PHRASE
    assert packet["approval_env_var"] == APPROVAL_ENV
    assert packet["approval_env_value"] == APPROVAL_TOKEN
    assert packet["target_ids"] == TARGET_IDS
    assert packet["target_count"] == 8
    assert packet["maximum_target_msa_queries"] == 8
    assert packet["maximum_a40_gpu_hours"] == 8.0
    assert packet["target_msa_queries_authorized_by_this_packet"] == 0
    assert packet["target_msa_queries_if_explicitly_approved"] == 8
    assert packet["can_submit_target_msa_if_explicitly_approved"] is True
    assert packet["can_submit_proteinmpnn"] is False
    assert packet["can_submit_structure_predictors"] is False
    assert packet["can_prepare_w3c_b2"] is False
    assert packet["cayuga_no_submit_validation_required"] is True
    assert packet["cayuga_no_submit_validation_status"] == "not_run"
    assert packet["ready_to_request_exact_approval"] is False
    assert packet["receipt_exists"] is False
    assert packet["failures"] == []
    assert packet["no_submit"] is True
    assert packet["cayuga_submission_allowed"] is False
    audit = _load(MANIFEST_AUDIT_PATH)
    assert audit["manifest"] == "configs/m6d_w3c_b1_target_msa_manifest.json"
    assert audit["ok"] is True
    assert audit["n_ready_targets"] == 8


def test_packet_and_wrapper_bind_every_runtime_artifact():
    packet = _load(PACKET_PATH)
    wrapper = WRAPPER_PATH.read_text()
    expected_names = {
        "execution_manifest",
        "extract_chain_fasta",
        "fresh_target_lock",
        "historical_overlap_registry",
        "locked_manifest",
        "plan",
        "precompute_python",
        "precompute_sbatch",
        "preflight",
        "prep_heterodimer",
        "protocol",
        "structure_fixture",
    }
    assert set(packet["bound_artifacts"]) == expected_names
    for name, binding in packet["bound_artifacts"].items():
        assert binding["sha256"] == _sha256(ROOT / binding["path"])
        marker = re.search(
            rf'^EXPECTED_{name.upper()}_SHA256="([0-9a-f]{{64}})"$',
            wrapper,
            re.MULTILINE,
        )
        assert marker is not None
        assert marker.group(1) == binding["sha256"]
    assert packet["wrapper"]["sha256"] == _sha256(WRAPPER_PATH)


def test_wrapper_scope_syntax_and_a40_budget_lock():
    syntax = subprocess.run(
        ["bash", "-n", str(WRAPPER_PATH)],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    wrapper = WRAPPER_PATH.read_text().lower()
    sbatch = (ROOT / "hpc/run_precompute_boltz_target_msa.sbatch").read_text()

    assert syntax.returncode == 0, syntax.stderr
    assert "exactly eight one-hour a40 target-msa jobs only" in wrapper
    assert "generate_proteinmpnn" not in wrapper
    assert "run_predict_boltz" not in wrapper
    assert "predict_af2" not in wrapper
    assert "#SBATCH --gres=gpu:a40:1" in sbatch
    assert "#SBATCH --time=01:00:00" in sbatch


def test_wrapper_dry_run_submits_nothing_and_creates_no_provenance_files():
    with tempfile.TemporaryDirectory() as tmp:
        receipt = pathlib.Path(tmp) / "receipt.jsonl"
        summary = pathlib.Path(tmp) / "summary.json"
        preflight = pathlib.Path(tmp) / "preflight.json"
        env = {
            **os.environ,
            "BIO_SFM_PYTHON": sys.executable,
            "TARGET_MSA_PRECOMPUTE_DRY_RUN": "1",
            "W3C_B1_TARGET_MSA_RECEIPT": str(receipt),
            "W3C_B1_TARGET_MSA_SUMMARY": str(summary),
            "W3C_B1_TARGET_MSA_PREFLIGHT": str(preflight),
        }
        result = subprocess.run(
            ["bash", str(WRAPPER_PATH)],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
        )

        assert result.returncode == 0, result.stderr
        assert "no scheduler jobs submitted" in result.stdout
        for target_id in TARGET_IDS:
            assert target_id in result.stdout
        assert not receipt.exists()
        assert not summary.exists()
        assert not preflight.exists()


def test_wrapper_refuses_non_dry_run_without_exact_approval():
    for approval in (None, "approved", "approve-w3c-b1-target-msa"):
        with tempfile.TemporaryDirectory() as tmp:
            receipt = pathlib.Path(tmp) / "receipt.jsonl"
            summary = pathlib.Path(tmp) / "summary.json"
            preflight = pathlib.Path(tmp) / "preflight.json"
            env = {
                **os.environ,
                "BIO_SFM_PYTHON": sys.executable,
                "W3C_B1_TARGET_MSA_RECEIPT": str(receipt),
                "W3C_B1_TARGET_MSA_SUMMARY": str(summary),
                "W3C_B1_TARGET_MSA_PREFLIGHT": str(preflight),
            }
            env.pop("TARGET_MSA_PRECOMPUTE_DRY_RUN", None)
            env.pop(APPROVAL_ENV, None)
            if approval is not None:
                env[APPROVAL_ENV] = approval
            result = subprocess.run(
                ["bash", str(WRAPPER_PATH)],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
            )

            assert result.returncode == 64
            assert "refusing W3c-B1 target-MSA submission" in result.stderr
            assert not receipt.exists()
            assert not summary.exists()
            assert not preflight.exists()


def test_preflight_materializes_fixture_inputs_without_network_or_scheduler():
    fixture = _load(FIXTURE_PATH)
    fixture_by_id = {row["target_id"]: row for row in fixture["targets"]}
    manifest = copy.deepcopy(_load(EXECUTION_MANIFEST_PATH))
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        for row in manifest["targets"]:
            target_id = row["id"]
            target_dir = root / target_id
            target_dir.mkdir(parents=True)
            source = target_dir / f"source_{row['rcsb_id']}.pdb"
            _write_ca_pdb(source, fixture_by_id[target_id])
            row["source_pdb"] = str(source)
            row["source_pdb_sha256"] = _sha256(source)
            row["source_pdb_url"] = "https://invalid.example/not-used.pdb"
            row["prepared_pdb"] = str(target_dir / f"prepared_{target_id}.pdb")
            row["prep_report"] = str(target_dir / f"prepared_{target_id}.report.json")
            row["target_fasta"] = str(target_dir / f"{target_id}_{row['target_chain']}.fasta")
            row["target_fasta_report"] = str(
                target_dir / f"{target_id}_{row['target_chain']}.fasta.report.json"
            )
            row["target_msa"] = str(target_dir / f"{target_id}_{row['target_chain']}.a3m")
            row["target_msa_report"] = str(
                target_dir / f"{target_id}_{row['target_chain']}.a3m.report.json"
            )

        report = run_preflight(
            manifest,
            materialize=True,
            project_root=str(ROOT),
            python_bin=sys.executable,
        )

        assert report["audit_ok"] is True
        assert report["target_ids"] == TARGET_IDS
        assert report["source_pdbs_verified"] == 8
        assert report["target_fastas_verified"] == 8
        assert report["scheduler_jobs_submitted"] == 0
        assert report["target_msa_queries_submitted"] == 0
        assert report["proteinmpnn_designs"] == 0
        assert report["predictor_evaluations"] == 0
        assert all(not pathlib.Path(row["target_msa"]).exists() for row in manifest["targets"])
