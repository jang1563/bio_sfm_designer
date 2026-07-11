import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date

from bio_sfm_designer.experiments.m6d_w2_panel_guarded_preflight import (
    build_approval_packet,
    build_preflight,
    main,
    render_guarded_wrapper,
    render_postsubmit_driver_script,
    render_sync_back_script,
)
from bio_sfm_designer.experiments.m6d_w2_panel_wrapper_guard_audit import build_audit
from bio_sfm_designer.experiments.m6d_w2_approval_scope import bind_scope


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
        self.assertIn("M6D_W2_V11_APPROVAL_INTENT_AUDIT", text)
        self.assertIn("m6d_w2_v11_approval_intent_audit", text)
        self.assertIn("approval_intent_accepted", text)
        self.assertIn("../hpc/m6d_w2_submit_with_receipt.sh", text)
        self.assertNotIn("sbatch", text)

    def test_real_wrapper_refuses_without_accepted_approval_intent_audit(self):
        with tempfile.TemporaryDirectory() as d:
            shared_name = "shared_submit.sh"
            shared = os.path.join(d, shared_name)
            wrapper = os.path.join(d, "submit_with_receipt.sh")
            _write(shared, "#!/usr/bin/env bash\nset -euo pipefail\necho delegated\n")
            os.chmod(shared, 0o755)
            _write(wrapper, render_guarded_wrapper(
                manifest="configs/v11.json",
                submit_receipt="results/v11_receipt.jsonl",
                submit_summary="results/v11_summary.json",
                workstream="m6d_w2_target_family_redesign_v11",
                approval_env_var="BIO_SFM_APPROVE_V11_PANEL",
                approval_token="approve-v11-panel-submit",
                dry_run_env_var="M6D_W2_V11_SUBMIT_DRY_RUN",
                shared_wrapper=shared_name,
            ))
            os.chmod(wrapper, 0o755)
            env = os.environ.copy()
            env["BIO_SFM_APPROVE_V11_PANEL"] = "approve-v11-panel-submit"
            env["BIO_SFM_PYTHON"] = sys.executable
            env.pop("M6D_W2_V11_SUBMIT_DRY_RUN", None)
            env.pop("M6D_W2_V11_APPROVAL_INTENT_AUDIT", None)

            proc = subprocess.run(
                [wrapper],
                cwd=d,
                env=env,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

        self.assertEqual(proc.returncode, 2)
        self.assertNotIn("delegated", proc.stdout)
        self.assertIn("approval-intent audit JSON", proc.stderr)

    def test_real_wrapper_accepts_approval_intent_audit_before_delegating(self):
        with tempfile.TemporaryDirectory() as d:
            shared_name = "shared_submit.sh"
            shared = os.path.join(d, shared_name)
            wrapper = os.path.join(d, "submit_with_receipt.sh")
            intent = os.path.join(d, "accepted_intent.json")
            manifest = os.path.join(d, "v11.json")
            _write_json(manifest, {"targets": [{"id": "t0"}]})
            scope = bind_scope({
                "manifest": manifest,
                "manifest_sha256": _sha(manifest),
                "target_ids": ["t0"],
                "n_ready_targets": 1,
                "planned_design_records": 100,
            })
            _write(shared, "#!/usr/bin/env bash\nset -euo pipefail\necho delegated\n")
            os.chmod(shared, 0o755)
            _write_json(intent, {
                "artifact": "m6d_w2_v11_approval_intent_audit",
                "status": "approval_intent_accepted",
                "audit_ok": True,
                "approval_intent_accepted": True,
                "no_submit": True,
                "submitted": False,
                "date": date.today().isoformat(),
                "approval_scope": scope,
                "approval_scope_sha256": scope["scope_sha256"],
                "manifest_sha256": scope["manifest_sha256"],
            })
            _write(wrapper, render_guarded_wrapper(
                manifest=manifest,
                submit_receipt="results/v11_receipt.jsonl",
                submit_summary="results/v11_summary.json",
                workstream="m6d_w2_target_family_redesign_v11",
                approval_env_var="BIO_SFM_APPROVE_V11_PANEL",
                approval_token="approve-v11-panel-submit",
                dry_run_env_var="M6D_W2_V11_SUBMIT_DRY_RUN",
                shared_wrapper=shared_name,
            ))
            os.chmod(wrapper, 0o755)
            env = os.environ.copy()
            env["BIO_SFM_APPROVE_V11_PANEL"] = "approve-v11-panel-submit"
            env["BIO_SFM_PYTHON"] = sys.executable
            env["M6D_W2_V11_APPROVAL_INTENT_AUDIT"] = intent
            env.pop("M6D_W2_V11_SUBMIT_DRY_RUN", None)

            proc = subprocess.run(
                [wrapper],
                cwd=d,
                env=env,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("delegated", proc.stdout)

    def test_real_wrapper_rejects_manifest_changed_after_approval(self):
        with tempfile.TemporaryDirectory() as d:
            shared = os.path.join(d, "shared_submit.sh")
            wrapper = os.path.join(d, "submit_with_receipt.sh")
            intent = os.path.join(d, "accepted_intent.json")
            manifest = os.path.join(d, "v11.json")
            _write(shared, "#!/usr/bin/env bash\necho delegated\n")
            os.chmod(shared, 0o755)
            _write_json(manifest, {"targets": [{"id": "t0"}]})
            scope = bind_scope({
                "manifest": manifest,
                "manifest_sha256": _sha(manifest),
                "target_ids": ["t0"],
            })
            _write_json(intent, {
                "artifact": "m6d_w2_v11_approval_intent_audit",
                "status": "approval_intent_accepted",
                "audit_ok": True,
                "approval_intent_accepted": True,
                "no_submit": True,
                "submitted": False,
                "date": date.today().isoformat(),
                "approval_scope": scope,
                "approval_scope_sha256": scope["scope_sha256"],
                "manifest_sha256": scope["manifest_sha256"],
            })
            _write(wrapper, render_guarded_wrapper(
                manifest=manifest,
                submit_receipt=os.path.join(d, "receipt.jsonl"),
                submit_summary=os.path.join(d, "summary.json"),
                workstream="m6d_w2_target_family_redesign_v11",
                approval_env_var="BIO_SFM_APPROVE_V11_PANEL",
                approval_token="approve-v11-panel-submit",
                dry_run_env_var="M6D_W2_V11_SUBMIT_DRY_RUN",
                shared_wrapper=os.path.basename(shared),
            ))
            os.chmod(wrapper, 0o755)
            _write_json(manifest, {"targets": [{"id": "t0"}, {"id": "t1"}]})
            env = os.environ.copy()
            env.update({
                "BIO_SFM_APPROVE_V11_PANEL": "approve-v11-panel-submit",
                "BIO_SFM_PYTHON": sys.executable,
                "M6D_W2_V11_APPROVAL_INTENT_AUDIT": intent,
            })
            proc = subprocess.run([wrapper], cwd=d, env=env, text=True, capture_output=True, check=False)

        self.assertNotEqual(proc.returncode, 0)
        self.assertNotIn("delegated", proc.stdout)
        self.assertIn("approval-intent audit is not accepted", proc.stderr)

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

    def test_build_preflight_blocks_historical_target_reuse(self):
        with tempfile.TemporaryDirectory() as d:
            manifest = os.path.join(d, "manifest.json")
            _write_json(manifest, {"targets": [{"id": "old_A", "rcsb_id": "old"}]})
            rep = build_preflight(
                manifest_path=manifest,
                manifest_report_path=os.path.join(d, "manifest_report.json"),
                wrapper_path=os.path.join(d, "wrapper.sh"),
                submit_receipt=os.path.join(d, "receipt.jsonl"),
                submit_summary=os.path.join(d, "summary.json"),
                workstream="w2_v11",
                approval_env_var="APPROVE",
                approval_token="yes",
                dry_run_env_var="DRY_RUN",
                manifest_report={"ok": True},
                wrapper_guard={"audit_ok": True},
                historical_registry_path="registry.json",
                historical_overlap_audit={
                    "audit_ok": False,
                    "historical_target_overlap": ["old_A"],
                    "failures": [{"kind": "historical_target_reuse"}],
                },
            )

        self.assertFalse(rep["audit_ok"])
        self.assertIn("historical_target_overlap", {failure["kind"] for failure in rep["failures"]})

    def test_sync_back_script_requires_postsubmit_sync_ready_before_records(self):
        text = render_sync_back_script(
            manifest="configs/v11.json",
            completion_script="results/completion.sh",
            submit_receipt="results/receipt.jsonl",
            submit_summary="results/summary.json",
            postsubmit_status="results/postsubmit.json",
            job_state_probe="results/job_states.json",
            remote_spec="cayuga-login1:/remote/root",
        )

        self.assertIn("m6d_w2_panel_postsubmit_status", text)
        self.assertIn("--require-sync-ready", text)
        self.assertIn("test -s \"$RECEIPT\"", text)
        self.assertIn("test -s \"$SUMMARY\"", text)
        self.assertIn("remote job-state probe is missing", text)
        self.assertIn("rsync -avP \"$REMOTE_ROOT/$JOB_STATES\"", text)
        self.assertIn("test -s \"$JOB_STATES\"", text)
        self.assertLess(
            text.index("m6d_w2_panel_postsubmit_status"),
            text.index("rsync -avP \"$REMOTE_ROOT/$relpath\""),
        )

    def test_postsubmit_driver_chains_read_only_bridge_without_submit(self):
        text = render_postsubmit_driver_script(
            receipt_monitor_script="results/receipt_monitor.sh",
            job_state_query_script="results/job_state_query.sh",
            postsync_replay_script="results/postsync_replay.sh",
            job_state_probe="results/job_state_probe.json",
            sacct_states="results/sacct_states.tsv",
            manifest="configs/v11.json",
            submit_receipt="results/receipt.jsonl",
            submit_summary="results/summary.json",
            postsubmit_status="results/postsubmit_status.json",
            remote_host="hpc-login",
            remote_root="/remote/root",
            cayuga_python="/remote/boltz/bin/python",
        )

        self.assertIn("This script never submits jobs", text)
        self.assertIn('REMOTE_HOST="${CAYUGA_BIO_SFM_HOST:-hpc-login}"', text)
        self.assertIn('REMOTE_PATH="${CAYUGA_BIO_SFM_REMOTE_ROOT:-/remote/root}"', text)
        self.assertIn('REMOTE_PYTHON="${CAYUGA_BIO_SFM_PYTHON:-/remote/boltz/bin/python}"', text)
        self.assertIn('bash "$RECEIPT_MONITOR"', text)
        self.assertIn('ssh "$REMOTE_HOST" "$remote_cmd"', text)
        self.assertIn('BIO_SFM_PYTHON=%q PYTHONNOUSERSITE=1 bash %q', text)
        self.assertIn('MAX_POLLS="${M6D_W2_POSTSUBMIT_MAX_POLLS:-120}"', text)
        self.assertIn('POLL_SECONDS="${M6D_W2_POSTSUBMIT_POLL_SECONDS:-300}"', text)
        self.assertIn("W2 v11 postsubmit poll", text)
        self.assertIn("m6d_w2_panel_postsubmit_status", text)
        self.assertIn("--out-json \"$POSTSUBMIT\"", text)
        self.assertIn("rep.get('sync_ready') is True", text)
        self.assertIn("postsubmit jobs are not sync-ready", text)
        self.assertIn('rsync -avP "$REMOTE_ROOT/$JOB_STATES"', text)
        self.assertIn('rsync -avP "$REMOTE_ROOT/$SACCT_STATES"', text)
        self.assertIn('bash "$POSTSYNC_REPLAY"', text)
        self.assertNotIn("sbatch", text)

    def test_cli_generates_wrapper_guard_and_preflight_without_submit(self):
        with tempfile.TemporaryDirectory() as d:
            manifest = os.path.join(d, "targets.json")
            _write_json(manifest, {
                "defaults": {"num_seq": 100, "objective": "binder", "seed": 37, "temp": 0.3},
                "targets": [_write_target_files(d, "t0"), _write_target_files(d, "t1")],
            })
            shared = os.path.join(d, "m6d_w2_target_family_redesign_v2_rcsb_submit_with_receipt.sh")
            _write(shared, "#!/usr/bin/env bash\nset -euo pipefail\necho 'dry-run t0: ProteinMPNN -> c0; Boltz -> r0'\necho 'dry-run t1: ProteinMPNN -> c1; Boltz -> r1'\n")
            os.chmod(shared, 0o755)

            wrapper = os.path.join(d, "submit_with_receipt.sh")
            receipt = os.path.join(d, "receipt.jsonl")
            summary = os.path.join(d, "summary.json")
            postsubmit_status = os.path.join(d, "postsubmit_status.json")
            job_state_probe = os.path.join(d, "job_state_probe.json")
            receipt_monitor = os.path.join(d, "receipt_monitor.sh")
            job_state_query = os.path.join(d, "job_state_query.sh")
            postsync_replay = os.path.join(d, "postsync_replay.sh")
            postsubmit_driver = os.path.join(d, "postsubmit_driver.sh")
            manifest_report = os.path.join(d, "manifest_report.json")
            guard_json = os.path.join(d, "guard.json")
            guard_md = os.path.join(d, "guard.md")
            preflight_json = os.path.join(d, "preflight.json")
            preflight_md = os.path.join(d, "preflight.md")
            runbook_json = os.path.join(d, "runbook.json")
            runbook_md = os.path.join(d, "runbook.md")
            approval_packet_json = os.path.join(d, "approval_packet.json")
            approval_packet_md = os.path.join(d, "approval_packet.md")
            sync_back = os.path.join(d, "sync_back.sh")
            completion = os.path.join(d, "completion.json")
            completion_script = os.path.join(d, "completion.sh")
            panel_out = os.path.join(d, "panel_report.json")

            rc = main([
                "--manifest", manifest,
                "--workstream", "m6d_w2_target_family_redesign_v11",
                "--wrapper-out", wrapper,
                "--submit-receipt", receipt,
                "--submit-summary", summary,
                "--postsubmit-status", postsubmit_status,
                "--job-state-probe", job_state_probe,
                "--receipt-monitor-script", receipt_monitor,
                "--job-state-query-script", job_state_query,
                "--postsync-replay-script", postsync_replay,
                "--postsubmit-driver-script", postsubmit_driver,
                "--manifest-report", manifest_report,
                "--guard-out-json", guard_json,
                "--guard-out-md", guard_md,
                "--preflight-out-json", preflight_json,
                "--preflight-out-md", preflight_md,
                "--runbook-out-json", runbook_json,
                "--runbook-out-md", runbook_md,
                "--approval-packet-out-json", approval_packet_json,
                "--approval-packet-out-md", approval_packet_md,
                "--sync-back-out", sync_back,
                "--completion-out", completion,
                "--completion-script-out", completion_script,
                "--panel-out", panel_out,
                "--approval-env-var", "BIO_SFM_APPROVE_V11_PANEL",
                "--approval-token", "approve-v11-panel-submit",
                "--dry-run-env-var", "M6D_W2_V11_SUBMIT_DRY_RUN",
                "--shared-wrapper", os.path.basename(shared),
                "--cayuga-python", "/remote/boltz/bin/python",
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
            with open(runbook_json) as fh:
                runbook = json.load(fh)
            self.assertEqual(runbook["status"], "approval_runbook_ready_not_submitted")
            self.assertFalse(runbook["submit_state"]["submitted"])
            self.assertIn("BIO_SFM_APPROVE_V11_PANEL", runbook["approval"]["submit_command_if_explicitly_approved"])
            self.assertEqual(runbook["post_submit"]["receipt_monitor_script"], receipt_monitor)
            self.assertEqual(runbook["post_submit"]["job_state_query_plan_after_probe"], job_state_query)
            self.assertIn("rsync -avP", runbook["post_submit"]["job_state_probe_sync_after_query"])
            self.assertIn(job_state_probe, runbook["post_submit"]["job_state_probe_sync_after_query"])
            self.assertIn("rsync -avP", runbook["post_submit"]["job_state_query_command_after_probe"])
            self.assertEqual(runbook["post_submit"]["postsubmit_driver_script"], postsubmit_driver)
            self.assertEqual(
                runbook["post_submit"]["postsubmit_driver_command_after_submit"],
                "bash " + postsubmit_driver,
            )
            self.assertEqual(
                runbook["post_submit"]["postsubmit_driver_polling"]["max_polls_env_var"],
                "M6D_W2_POSTSUBMIT_MAX_POLLS",
            )
            self.assertEqual(runbook["post_submit"]["postsubmit_driver_polling"]["default_max_polls"], 120)
            self.assertTrue(runbook["post_submit"]["postsubmit_driver_polling"]["proceeds_only_when_sync_ready"])
            self.assertEqual(runbook["post_submit"]["postsync_replay_script"], postsync_replay)
            self.assertIn("m6d_w2_panel_job_state_probe", runbook["post_submit"]["job_state_probe_command_after_receipt_sync"])
            self.assertIn("--require-sync-ready", runbook["post_submit"]["postsubmit_status_command_before_sync"])
            self.assertIn(f"--manifest {manifest}", runbook["post_submit"]["postsubmit_status_command_before_sync"])
            self.assertIn(f"--receipt {receipt}", runbook["post_submit"]["postsubmit_status_command_before_sync"])
            self.assertIn(f"--summary {summary}", runbook["post_submit"]["postsubmit_status_command_before_sync"])
            self.assertIn(f"--job-states {job_state_probe}", runbook["post_submit"]["postsubmit_status_command_before_sync"])
            self.assertIn(f"--out-json {postsubmit_status}", runbook["post_submit"]["postsubmit_status_command_before_sync"])
            self.assertTrue(os.path.exists(sync_back))
            self.assertTrue(os.path.exists(completion_script))
            self.assertTrue(os.path.exists(postsubmit_driver))
            self.assertTrue(os.path.exists(receipt_monitor))
            self.assertTrue(os.path.exists(job_state_query))
            self.assertTrue(os.path.exists(postsync_replay))
            with open(postsubmit_driver) as fh:
                postsubmit_driver_text = fh.read()
            self.assertIn("This script never submits jobs", postsubmit_driver_text)
            self.assertIn('bash "$RECEIPT_MONITOR"', postsubmit_driver_text)
            self.assertIn('MAX_POLLS="${M6D_W2_POSTSUBMIT_MAX_POLLS:-120}"', postsubmit_driver_text)
            self.assertIn("m6d_w2_panel_postsubmit_status", postsubmit_driver_text)
            self.assertIn("rep.get('sync_ready') is True", postsubmit_driver_text)
            self.assertNotIn("sbatch", postsubmit_driver_text)
            with open(completion_script) as fh:
                completion_text = fh.read()
            self.assertIn('PYTHON_BIN="${BIO_SFM_PYTHON:-${ENV_PY:-python3}}"', completion_text)
            self.assertIn('BIO_SFM_TRUST_CORE_SRC=', completion_text)
            self.assertIn('$REPO_ROOT/src:$BIO_SFM_TRUST_CORE_SRC', completion_text)
            self.assertIn('export PYTHONNOUSERSITE="${PYTHONNOUSERSITE:-1}"', completion_text)
            self.assertIn('"$PYTHON_BIN" -m bio_sfm_designer.experiments.complex_panel_completion', completion_text)
            with open(sync_back) as fh:
                sync_back_text = fh.read()
            self.assertIn("m6d_w2_panel_postsubmit_status", sync_back_text)
            self.assertIn("--require-sync-ready", sync_back_text)
            self.assertIn("remote job-state probe is missing", sync_back_text)
            with open(approval_packet_json) as fh:
                approval_packet = json.load(fh)
            self.assertEqual(approval_packet["status"], "panel_approval_packet_ready")
            self.assertTrue(approval_packet["approval_packet_ready"])
            self.assertTrue(approval_packet["can_submit_panel_if_user_explicitly_approves"])
            self.assertFalse(approval_packet["can_claim_w2_generalization"])
            self.assertEqual(approval_packet["panel_approval_env_var"], "BIO_SFM_APPROVE_V11_PANEL")
            self.assertEqual(approval_packet["manifest"], manifest)
            self.assertTrue(approval_packet["checks"]["approval_scope_ready"])
            self.assertTrue(approval_packet["checks"]["post_submit_scripts_ready"])
            self.assertTrue(all(approval_packet["post_submit_script_checks"].values()))
            self.assertEqual(approval_packet["approval_scope"]["target_ids"], ["t0", "t1"])
            self.assertEqual(approval_packet["approval_scope"]["n_targets"], 2)
            self.assertEqual(approval_packet["approval_scope"]["n_ready_targets"], 2)
            self.assertEqual(approval_packet["approval_scope"]["min_targets"], 2)
            self.assertEqual(approval_packet["approval_scope"]["records_per_target_planned"], 100)
            self.assertEqual(approval_packet["approval_scope"]["planned_design_records"], 200)
            self.assertEqual(approval_packet["approval_scope"]["expected_job_pairs"], 2)
            self.assertEqual(approval_packet["approval_scope"]["expected_slurm_jobs"], 4)
            self.assertEqual(approval_packet["approval_scope"]["job_pair_model"], "ProteinMPNN -> Boltz")
            self.assertEqual(approval_packet["approval_scope"]["target_alpha"], 0.2)
            self.assertFalse(approval_packet["approval_scope"]["can_claim_w2_generalization"])
            self.assertIn("receipt_monitor.sh", approval_packet["receipt_monitor_after_submit"])
            self.assertIn("postsubmit_driver.sh", approval_packet["postsubmit_driver_after_submit"])
            self.assertEqual(
                approval_packet["postsubmit_driver_polling"]["poll_seconds_env_var"],
                "M6D_W2_POSTSUBMIT_POLL_SECONDS",
            )
            self.assertIn("job_state_query.sh", approval_packet["job_state_query_after_receipt"])
            self.assertIn("rsync -avP", approval_packet["job_state_probe_sync_after_query"])
            self.assertIn("m6d_w2_panel_postsubmit_status", approval_packet["postsubmit_sync_ready_gate"])
            self.assertIn("--require-sync-ready", approval_packet["postsubmit_status_command_before_sync"])
            self.assertIn(f"--manifest {manifest}", approval_packet["postsubmit_status_command_before_sync"])
            self.assertIn(f"--receipt {receipt}", approval_packet["postsubmit_status_command_before_sync"])
            self.assertIn(f"--summary {summary}", approval_packet["postsubmit_status_command_before_sync"])
            self.assertIn(f"--job-states {job_state_probe}", approval_packet["postsubmit_status_command_before_sync"])
            self.assertIn(f"--out-json {postsubmit_status}", approval_packet["postsubmit_status_command_before_sync"])
            self.assertIn("postsync_replay.sh", approval_packet["postsync_replay_after_sync"])

            guard = build_audit(
                wrapper,
                receipt,
                run_no_env_check=True,
                approval_env_var="BIO_SFM_APPROVE_V11_PANEL",
                approval_token="approve-v11-panel-submit",
                dry_run_env_var="M6D_W2_V11_SUBMIT_DRY_RUN",
                refusal_message="refusing v11 panel submission without explicit approval env",
                shared_wrapper_marker=f'{os.path.basename(shared)}"',
            )
            self.assertTrue(guard["audit_ok"])


if __name__ == "__main__":
    unittest.main()
