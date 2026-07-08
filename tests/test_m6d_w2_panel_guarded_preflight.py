import hashlib
import json
import os
import tempfile
import unittest

from bio_sfm_designer.experiments.m6d_w2_panel_guarded_preflight import (
    build_preflight,
    main,
    render_guarded_wrapper,
)
from bio_sfm_designer.experiments.m6d_w2_panel_wrapper_guard_audit import build_audit


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)


def _write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(obj, fh)
        fh.write("\n")


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_target_files(d, tid):
    pdb = os.path.join(d, f"{tid}.pdb")
    fasta = os.path.join(d, f"{tid}.fasta")
    msa = os.path.join(d, f"{tid}.a3m")
    seq = "ACDE"
    _write(pdb, "ATOM\n")
    _write(fasta, f">{tid}\n{seq}\n")
    _write(msa, f">{tid}\n{seq}\n")
    _write_json(fasta + ".report.json", {
        "pdb": pdb,
        "pdb_sha256": _sha(pdb),
        "chain": "A",
        "out": fasta,
        "out_sha256": _sha(fasta),
        "length": len(seq),
        "sequence": seq,
    })
    _write_json(msa + ".report.json", {
        "out": msa,
        "out_sha256": _sha(msa),
        "fasta": fasta,
        "fasta_sha256": _sha(fasta),
        "sequence_length": len(seq),
        "ok": True,
    })
    return {
        "id": tid,
        "prepared_pdb": pdb,
        "target_chain": "A",
        "binder_chain": "B",
        "target_fasta": fasta,
        "target_msa": msa,
        "records": os.path.join(d, "records", tid, "records_boltz_complex.jsonl"),
        "out_prefix": os.path.join(d, "records", tid),
    }


class M6DW2PanelGuardedPreflightTests(unittest.TestCase):
    def test_rendered_wrapper_has_v11_approval_guard(self):
        text = render_guarded_wrapper(
            manifest="configs/v11.json",
            submit_receipt="results/v11_receipt.jsonl",
            submit_summary="results/v11_summary.json",
            workstream="m6d_w2_target_family_redesign_v11",
            approval_env_var="BIO_SFM_APPROVE_V11_PANEL",
            approval_token="approve-v11-panel-submit",
            dry_run_env_var="M6D_W2_V11_SUBMIT_DRY_RUN",
        )

        self.assertIn("BIO_SFM_APPROVE_V11_PANEL", text)
        self.assertIn("approve-v11-panel-submit", text)
        self.assertIn("M6D_W2_V11_SUBMIT_DRY_RUN", text)
        self.assertIn("m6d_w2_target_family_redesign_v2_rcsb_submit_with_receipt.sh", text)
        self.assertNotIn("sbatch", text)

    def test_build_preflight_blocks_if_wrapper_guard_failed(self):
        with tempfile.TemporaryDirectory() as d:
            manifest = os.path.join(d, "manifest.json")
            _write_json(manifest, {"targets": [{"id": "t0"}, {"id": "t1"}]})

            rep = build_preflight(
                manifest_path=manifest,
                manifest_report_path=os.path.join(d, "manifest_report.json"),
                wrapper_path=os.path.join(d, "wrapper.sh"),
                submit_receipt=os.path.join(d, "receipt.jsonl"),
                submit_summary=os.path.join(d, "summary.json"),
                workstream="m6d_w2_target_family_redesign_v11",
                approval_env_var="BIO_SFM_APPROVE_V11_PANEL",
                approval_token="approve-v11-panel-submit",
                dry_run_env_var="M6D_W2_V11_SUBMIT_DRY_RUN",
                manifest_report={
                    "ok": True,
                    "n_targets": 2,
                    "n_ready_targets": 2,
                    "min_targets": 2,
                    "min_contacts": 20,
                    "require_files": True,
                },
                wrapper_guard={"audit_ok": False, "status": "panel_wrapper_guard_failed"},
            )

        self.assertFalse(rep["audit_ok"])
        self.assertIn("wrapper_guard_not_ok", {failure["kind"] for failure in rep["failures"]})

    def test_cli_generates_wrapper_guard_and_preflight_without_submit(self):
        with tempfile.TemporaryDirectory() as d:
            manifest = os.path.join(d, "targets.json")
            _write_json(manifest, {"targets": [_write_target_files(d, "t0"), _write_target_files(d, "t1")]})
            shared = os.path.join(d, "m6d_w2_target_family_redesign_v2_rcsb_submit_with_receipt.sh")
            _write(shared, "#!/usr/bin/env bash\nset -euo pipefail\necho 'dry-run t0: ProteinMPNN -> c0; Boltz -> r0'\necho 'dry-run t1: ProteinMPNN -> c1; Boltz -> r1'\n")
            os.chmod(shared, 0o755)

            wrapper = os.path.join(d, "submit_with_receipt.sh")
            receipt = os.path.join(d, "receipt.jsonl")
            summary = os.path.join(d, "summary.json")
            manifest_report = os.path.join(d, "manifest_report.json")
            guard_json = os.path.join(d, "guard.json")
            guard_md = os.path.join(d, "guard.md")
            preflight_json = os.path.join(d, "preflight.json")
            preflight_md = os.path.join(d, "preflight.md")

            rc = main([
                "--manifest", manifest,
                "--workstream", "m6d_w2_target_family_redesign_v11",
                "--wrapper-out", wrapper,
                "--submit-receipt", receipt,
                "--submit-summary", summary,
                "--manifest-report", manifest_report,
                "--guard-out-json", guard_json,
                "--guard-out-md", guard_md,
                "--preflight-out-json", preflight_json,
                "--preflight-out-md", preflight_md,
                "--approval-env-var", "BIO_SFM_APPROVE_V11_PANEL",
                "--approval-token", "approve-v11-panel-submit",
                "--dry-run-env-var", "M6D_W2_V11_SUBMIT_DRY_RUN",
                "--shared-wrapper", os.path.basename(shared),
                "--min-targets", "2",
                "--run-local-dry-run",
            ])

            self.assertEqual(rc, 0)
            self.assertFalse(os.path.exists(receipt))
            self.assertFalse(os.path.exists(summary))
            with open(preflight_json) as fh:
                preflight = json.load(fh)
            self.assertEqual(preflight["status"], "panel_preflight_dry_run_passed_not_submitted")
            self.assertEqual(preflight["submit_ready"]["n_ready_targets"], 2)
            self.assertEqual(preflight["local_dry_run"]["n_targets_enumerated"], 2)

            guard = build_audit(
                wrapper,
                receipt,
                run_no_env_check=True,
                approval_env_var="BIO_SFM_APPROVE_V11_PANEL",
                approval_token="approve-v11-panel-submit",
                dry_run_env_var="M6D_W2_V11_SUBMIT_DRY_RUN",
                refusal_message="refusing v11 panel submission without explicit approval env",
            )
            self.assertTrue(guard["audit_ok"])


if __name__ == "__main__":
    unittest.main()
