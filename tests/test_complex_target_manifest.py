"""Tests for the M6c multi-target manifest validator."""

import io
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

from bio_sfm_designer.experiments.complex_target_manifest import (
    main,
    render_hpc_plan,
    render_target_msa_plan,
    validate_manifest,
)


def _touch(path, text="x\n"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)


def _prep_report(path, target_chain="A", binder_chain="B", contacts=5,
                 target_gaps=None, binder_gaps=None):
    _touch(path, json.dumps({
        "target_chain": target_chain,
        "binder_chain": binder_chain,
        "target_numbering_gaps": target_gaps or [],
        "binder_numbering_gaps": binder_gaps or [],
        "ca_interface_contacts": contacts,
    }) + "\n")


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _target_msa_report(path, fasta, out, ok=True, sequence_length=4):
    _touch(path, json.dumps({
        "ok": ok,
        "fasta": fasta,
        "fasta_sha256": _sha256_file(fasta) if os.path.exists(fasta) else "",
        "out": out,
        "out_sha256": _sha256_file(out) if os.path.exists(out) else "",
        "sequence_length": sequence_length,
    }) + "\n")


def _target_fasta_report(path, pdb, fasta, chain="A", sequence="AAAA"):
    _touch(path, json.dumps({
        "pdb": os.path.abspath(pdb),
        "pdb_sha256": _sha256_file(pdb) if os.path.exists(pdb) else "",
        "chain": chain,
        "length": len(sequence),
        "sequence": sequence,
        "fasta_id": f"target_{chain}",
        "out": os.path.abspath(fasta),
        "out_sha256": _sha256_file(fasta) if os.path.exists(fasta) else "",
        "unknown_allowed": False,
    }) + "\n")


def _default_target_fasta_report(pdb, fasta, chain="A", sequence="AAAA"):
    path = fasta + ".report.json"
    _target_fasta_report(path, pdb, fasta, chain=chain, sequence=sequence)
    return path


def _default_target_msa_report(msa, fasta, sequence_length=4):
    path = msa + ".report.json"
    _target_msa_report(path, fasta, msa, sequence_length=sequence_length)
    return path


class ComplexTargetManifestTests(unittest.TestCase):
    def test_valid_manifest_with_files_and_prep_reports(self):
        with tempfile.TemporaryDirectory() as d:
            targets = []
            for i in range(3):
                tid = f"t{i}"
                pdb = os.path.join(d, f"{tid}.pdb")
                fasta = os.path.join(d, f"{tid}.fasta")
                msa = os.path.join(d, f"{tid}.a3m")
                report = os.path.join(d, f"{tid}.report.json")
                _touch(pdb)
                _touch(fasta, ">target\nAAAA\n")
                _touch(msa, ">target\nAAAA\n")
                _default_target_fasta_report(pdb, fasta)
                _default_target_msa_report(msa, fasta)
                _prep_report(report)
                targets.append({"id": tid, "source_pdb": pdb, "prepared_pdb": pdb,
                                "target_chain": "A", "binder_chain": "B",
                                "target_fasta": fasta, "target_msa": msa, "prep_report": report,
                                "out_prefix": f"hpc_outputs/{tid}"})
            manifest = os.path.join(d, "targets.json")
            _touch(manifest, json.dumps({"targets": targets}) + "\n")

            rep = validate_manifest(manifest, require_files=True, min_targets=3)
            self.assertTrue(rep["ok"])
            self.assertEqual(rep["n_ready_targets"], 3)
            artifacts = rep["input_prep_artifacts"]
            self.assertIn({"target_id": "t0", "field": "prepared_pdb", "path": os.path.join(d, "t0.pdb")}, artifacts)
            self.assertIn({"target_id": "t0", "field": "target_fasta_report", "path": os.path.join(d, "t0.fasta.report.json")}, artifacts)
            self.assertIn({"target_id": "t0", "field": "target_msa_report", "path": os.path.join(d, "t0.a3m.report.json")}, artifacts)
            plan = render_hpc_plan(rep, manifest)
            self.assertIn("extract_chain_fasta.py", plan)
            self.assertIn("set -euo pipefail", plan)
            self.assertIn("complex_target_manifest --manifest", plan)
            self.assertIn("--require-files", plan)
            self.assertIn("--min-targets 3", plan)
            self.assertIn("--min-contacts 1", plan)
            self.assertIn("GEN_00_T0=$(", plan)
            self.assertIn("sbatch --parsable hpc/run_generate_proteinmpnn_complex.sbatch", plan)
            self.assertIn("sbatch --dependency=afterok:${GEN_00_T0}", plan)
            self.assertIn("run_generate_proteinmpnn_complex.sbatch", plan)
            self.assertIn("NUM_SEQ=40", plan)
            self.assertIn("TEMP=0.3", plan)
            self.assertIn("SEED=37", plan)
            self.assertIn("OBJECTIVE=binder", plan)
            self.assertIn("COMPLEX_ID=t0", plan)
            self.assertIn("TARGET_MSA=", plan)
            self.assertIn("Missing target MSA", plan)
            self.assertIn("run_precompute_boltz_target_msa.sbatch", plan)
            self.assertIn("complex_panel_completion", plan)

    def test_planned_records_path_is_not_required_before_jobs_by_default(self):
        with tempfile.TemporaryDirectory() as d:
            pdb = os.path.join(d, "x.pdb")
            fasta = os.path.join(d, "x.fasta")
            msa = os.path.join(d, "x.a3m")
            missing_records = os.path.join(d, "planned", "records.jsonl")
            _touch(pdb)
            _touch(fasta, ">target\nAAAA\n")
            _touch(msa, ">target\nAAAA\n")
            _default_target_fasta_report(pdb, fasta)
            _default_target_msa_report(msa, fasta)
            manifest = os.path.join(d, "targets.json")
            _touch(manifest, json.dumps({"targets": [{
                "id": "x",
                "prepared_pdb": pdb,
                "target_chain": "A",
                "binder_chain": "B",
                "target_fasta": fasta,
                "target_msa": msa,
                "records": missing_records,
            }]}) + "\n")

            rep = validate_manifest(manifest, require_files=True)
            self.assertTrue(rep["ok"])
            self.assertFalse(rep["require_records"])

            strict = validate_manifest(manifest, require_files=True, require_records=True)
            self.assertFalse(strict["ok"])
            self.assertEqual(strict["failures_by_kind"]["missing_file"], 1)

    def test_target_msa_precompute_plan_runs_before_require_files(self):
        with tempfile.TemporaryDirectory() as d:
            manifest = os.path.join(d, "targets.json")
            _touch(manifest, json.dumps({"targets": [
                {
                    "id": "needs msa",
                    "prepared_pdb": "/tmp/prepared target.pdb",
                    "target_chain": "A",
                    "binder_chain": "B",
                    "target_fasta": "/tmp/target fasta.fa",
                    "target_msa": "/tmp/target msa.a3m",
                    "target_msa_report": "/tmp/target msa.report.json",
                },
                {
                    "id": "bad",
                    "prepared_pdb": "/tmp/bad.pdb",
                    "target_chain": "A",
                    "binder_chain": "B",
                    "target_fasta": "/tmp/bad.fa",
                },
            ]}) + "\n")

            plan = render_target_msa_plan(manifest)
            manifest_sha = _sha256_file(manifest)

        self.assertIn("set -euo pipefail", plan)
        self.assertIn("MSA_00_NEEDS_MSA=$(", plan)
        self.assertIn("extract_chain_fasta.py --pdb '/tmp/prepared target.pdb'", plan)
        self.assertIn("--report '/tmp/target fasta.fa.report.json'", plan)
        self.assertIn("FASTA='/tmp/target fasta.fa'", plan)
        self.assertIn("OUT='/tmp/target msa.a3m'", plan)
        self.assertIn("REPORT='/tmp/target msa.report.json'", plan)
        self.assertIn(f"TARGET_MSA_PRECOMPUTE_MANIFEST={manifest}", plan)
        self.assertIn(f"TARGET_MSA_PRECOMPUTE_MANIFEST_SHA256_EXPECTED={manifest_sha}", plan)
        self.assertIn('PYTHON_BIN="${BIO_SFM_PYTHON:-${ENV_PY:-python3}}"', plan)
        self.assertIn('if [ "${TARGET_MSA_PRECOMPUTE_DRY_RUN:-0}" = "1" ]; then', plan)
        self.assertIn("target-MSA precompute dry-run: manifest fresh; no scheduler jobs submitted; receipt untouched.", plan)
        self.assertNotIn("if [ -z \"${TARGET_MSA_PRECOMPUTE_MANIFEST:-}\" ]; then", plan)
        self.assertNotIn("if [ -z \"${TARGET_MSA_PRECOMPUTE_MANIFEST_SHA256_EXPECTED:-}\" ]; then", plan)
        self.assertIn('TARGET_MSA_PRECOMPUTE_MANIFEST_SHA256_ACTUAL=$("$PYTHON_BIN"', plan)
        self.assertIn("target-MSA precompute manifest is stale", plan)
        self.assertLess(
            plan.index('TARGET_MSA_PRECOMPUTE_MANIFEST_SHA256_ACTUAL=$("$PYTHON_BIN"'),
            plan.index("MSA_00_NEEDS_MSA=$("),
        )
        self.assertLess(
            plan.index('if [ "${TARGET_MSA_PRECOMPUTE_DRY_RUN:-0}" = "1" ]; then'),
            plan.index("MSA_00_NEEDS_MSA=$("),
        )
        self.assertIn("\"manifest\": os.environ.get(\"MANIFEST\") or None", plan)
        self.assertIn("\"manifest_sha256\": os.environ.get(\"MANIFEST_SHA256\") or None", plan)
        self.assertIn("sbatch --parsable hpc/run_precompute_boltz_target_msa.sbatch", plan)
        self.assertIn("require_target_msa_job_id() {", plan)
        self.assertIn("empty or whitespace-only job id", plan)
        self.assertIn("non-parsable job id with whitespace", plan)
        self.assertIn("validate_target_msa_precompute_receipt() {", plan)
        self.assertIn("TARGET_MSA_PRECOMPUTE_RECEIPT_STRICT_TARGET_SET", plan)
        self.assertIn("require_target_msa_job_id 'needs msa' \"${MSA_00_NEEDS_MSA}\"", plan)
        self.assertLess(
            plan.index("require_target_msa_job_id 'needs msa' \"${MSA_00_NEEDS_MSA}\""),
            plan.index("record_target_msa_precompute 'needs msa' submitted"),
        )
        self.assertIn("validate_target_msa_precompute_receipt --expect-json", plan)
        self.assertIn("\"target_fasta\":\"/tmp/target fasta.fa\"", plan)
        self.assertIn(f"\"manifest_sha256\":\"{manifest_sha}\"", plan)
        self.assertIn("target_id={target_id} {field} mismatch", plan)
        self.assertIn("'manifest', 'manifest_sha256', 'workstream'", plan)
        self.assertIn("'needs msa'", plan)
        self.assertLess(
            plan.index("record_target_msa_precompute 'needs msa' submitted"),
            plan.index("validate_target_msa_precompute_receipt --expect-json"),
        )
        self.assertIn("if [ -s '/tmp/target msa.a3m' ]; then", plan)
        self.assertIn("target MSA exists; validating and refreshing report: /tmp/target msa.a3m", plan)
        self.assertIn("\"$PYTHON_BIN\" hpc/precompute_boltz_target_msa.py --fasta '/tmp/target fasta.fa' --out '/tmp/target msa.a3m' --report '/tmp/target msa.report.json'", plan)
        self.assertIn("# bad: missing target_msa; skipped", plan)
        self.assertIn("# expected_input_prep_files", plan)
        self.assertIn("# needs msa prepared_pdb: /tmp/prepared target.pdb", plan)
        self.assertIn("# needs msa target_fasta_report: /tmp/target fasta.fa.report.json", plan)
        self.assertIn("# needs msa target_msa_report: /tmp/target msa.report.json", plan)

    def test_target_msa_precompute_plan_dry_run_exits_before_target_work(self):
        with tempfile.TemporaryDirectory() as d:
            manifest = os.path.join(d, "targets.json")
            script = os.path.join(d, "target_msa_precompute.sh")
            python_bin = os.path.join(d, "bin", "python")
            _touch(manifest, json.dumps({"targets": [{
                "id": "needs-msa",
                "prepared_pdb": "/tmp/prepared-target.pdb",
                "target_chain": "A",
                "binder_chain": "B",
                "target_fasta": "/tmp/target.fasta",
                "target_msa": "/tmp/target.a3m",
            }]}) + "\n")
            _touch(script, render_target_msa_plan(manifest))
            os.chmod(script, 0o755)
            os.makedirs(os.path.dirname(python_bin), exist_ok=True)
            os.symlink(sys.executable, python_bin)
            env = os.environ.copy()
            env["PATH"] = os.path.dirname(python_bin) + os.pathsep + env.get("PATH", "")
            env["TARGET_MSA_PRECOMPUTE_DRY_RUN"] = "1"
            result = subprocess.run(
                ["bash", script],
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(result.returncode, 0)
        self.assertIn("target-MSA precompute dry-run", result.stdout)
        self.assertIn("needs-msa", result.stdout)
        self.assertNotIn("extract_chain_fasta.py", result.stdout + result.stderr)
        self.assertNotIn("sbatch --parsable", result.stdout + result.stderr)

    def test_target_msa_precompute_plan_rejects_stale_manifest_before_target_work(self):
        with tempfile.TemporaryDirectory() as d:
            manifest = os.path.join(d, "targets.json")
            script = os.path.join(d, "target_msa_precompute.sh")
            python_bin = os.path.join(d, "bin", "python")
            _touch(manifest, json.dumps({"targets": [{
                "id": "needs-msa",
                "prepared_pdb": "/tmp/prepared-target.pdb",
                "target_chain": "A",
                "binder_chain": "B",
                "target_fasta": "/tmp/target.fasta",
                "target_msa": "/tmp/target.a3m",
            }]}) + "\n")
            plan = render_target_msa_plan(manifest)
            _touch(script, plan)
            os.chmod(script, 0o755)
            os.makedirs(os.path.dirname(python_bin), exist_ok=True)
            os.symlink(sys.executable, python_bin)

            mutated_manifest = {"targets": [{
                "id": "needs-msa",
                "prepared_pdb": "/tmp/prepared-target.pdb",
                "target_chain": "A",
                "binder_chain": "B",
                "target_fasta": "/tmp/target.fasta",
                "target_msa": "/tmp/target.a3m",
                "changed_after_render": True,
            }]}
            _touch(manifest, json.dumps(mutated_manifest) + "\n")
            mutated_sha = hashlib.sha256((json.dumps(mutated_manifest) + "\n").encode()).hexdigest()
            env = os.environ.copy()
            env["PATH"] = os.path.dirname(python_bin) + os.pathsep + env.get("PATH", "")
            env["TARGET_MSA_PRECOMPUTE_MANIFEST_SHA256_EXPECTED"] = mutated_sha
            result = subprocess.run(
                ["bash", script],
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(result.returncode, 2)
        self.assertIn("target-MSA precompute manifest is stale", result.stderr)
        self.assertNotIn("extract_chain_fasta.py", result.stderr + result.stdout)

    def test_target_msa_plan_reuses_existing_msa_to_refresh_report(self):
        with tempfile.TemporaryDirectory() as d:
            manifest = os.path.join(d, "targets.json")
            _touch(manifest, json.dumps({"targets": [{
                "id": "reuse-report",
                "prepared_pdb": "/tmp/reuse.pdb",
                "target_chain": "A",
                "binder_chain": "B",
                "target_fasta": "/tmp/reuse.fa",
                "target_msa": "/tmp/reuse.a3m",
                "target_msa_report": "/tmp/reuse.a3m.report.json",
            }]}) + "\n")

            plan = render_target_msa_plan(manifest)

        self.assertIn("if [ -s /tmp/reuse.a3m ]; then", plan)
        self.assertIn('"$PYTHON_BIN" hpc/precompute_boltz_target_msa.py --fasta /tmp/reuse.fa --out /tmp/reuse.a3m --report /tmp/reuse.a3m.report.json', plan)
        self.assertNotIn("[ -s /tmp/reuse.a3m ] && [ -s /tmp/reuse.a3m.report.json ]", plan)

    def test_target_msa_plan_can_fetch_source_and_prepare_hetdimer(self):
        with tempfile.TemporaryDirectory() as d:
            manifest = os.path.join(d, "targets.json")
            _touch(manifest, json.dumps({"targets": [{
                "id": "1BRS_AD",
                "rcsb_id": "1brs",
                "source_pdb": "/tmp/source 1BRS.pdb",
                "prepared_pdb": "/tmp/prepared 1BRS_AD.pdb",
                "prep_report": "/tmp/prepared 1BRS_AD.report.json",
                "target_chain": "A",
                "binder_chain": "D",
                "target_fasta": "/tmp/1BRS A.fasta",
                "target_fasta_report": "/tmp/1BRS A.fasta.report.json",
                "target_msa": "/tmp/1BRS A.a3m",
            }]}) + "\n")

            plan = render_target_msa_plan(manifest)

        self.assertIn("curl -fsSL https://files.rcsb.org/download/1BRS.pdb -o '/tmp/source 1BRS.pdb'", plan)
        self.assertIn("source PDB already exists: /tmp/source 1BRS.pdb", plan)
        self.assertIn("prepared PDB already exists: /tmp/prepared 1BRS_AD.pdb", plan)
        self.assertIn("prep_hetdimer.py --pdb '/tmp/source 1BRS.pdb' --target-chain A --binder-chain D", plan)
        self.assertIn("--out '/tmp/prepared 1BRS_AD.pdb' --report '/tmp/prepared 1BRS_AD.report.json'", plan)
        self.assertNotIn("--allow-numbering-gaps", plan)
        self.assertIn("extract_chain_fasta.py --pdb '/tmp/prepared 1BRS_AD.pdb'", plan)
        self.assertIn("--out '/tmp/1BRS A.fasta' --report '/tmp/1BRS A.fasta.report.json'", plan)
        self.assertIn("# 1BRS_AD source_pdb: /tmp/source 1BRS.pdb", plan)
        self.assertIn("# 1BRS_AD prep_report: /tmp/prepared 1BRS_AD.report.json", plan)

    def test_target_msa_plan_marks_reviewed_numbering_gap_exception(self):
        with tempfile.TemporaryDirectory() as d:
            manifest = os.path.join(d, "targets.json")
            _touch(manifest, json.dumps({"targets": [{
                "id": "1BRS_AD",
                "rcsb_id": "1BRS",
                "source_pdb": "/tmp/source_1BRS.pdb",
                "prepared_pdb": "/tmp/prepared_1BRS_AD.pdb",
                "prep_report": "/tmp/prepared_1BRS_AD.report.json",
                "allow_numbering_gaps": True,
                "target_chain": "A",
                "binder_chain": "D",
                "target_fasta": "/tmp/1BRS_A.fasta",
                "target_msa": "/tmp/1BRS_A.a3m",
            }]}) + "\n")

            plan = render_target_msa_plan(manifest)

        self.assertIn("--allow-numbering-gaps", plan)

    def test_target_msa_precompute_plan_can_select_targets(self):
        with tempfile.TemporaryDirectory() as d:
            manifest = os.path.join(d, "targets.json")
            _touch(manifest, json.dumps({"targets": [
                {
                    "id": "scale-target",
                    "prepared_pdb": "/tmp/scale.pdb",
                    "target_chain": "A",
                    "target_fasta": "/tmp/scale.fa",
                    "target_msa": "/tmp/scale.a3m",
                },
                {
                    "id": "placeholder",
                    "prepared_pdb": "/tmp/placeholder.pdb",
                    "target_chain": "A",
                    "target_fasta": "/tmp/placeholder.fa",
                    "target_msa": "/tmp/placeholder.a3m",
                },
            ]}) + "\n")

            plan = render_target_msa_plan(manifest, target_ids=["scale-target"])

        self.assertIn("# scale-target", plan)
        self.assertIn("MSA_00_SCALE_TARGET=$(", plan)
        self.assertNotIn("placeholder", plan)

    def test_rejects_duplicate_and_bad_chain(self):
        with tempfile.TemporaryDirectory() as d:
            manifest = os.path.join(d, "targets.json")
            targets = [
                {"id": "dup", "prepared_pdb": "a.pdb", "target_chain": "A",
                 "binder_chain": "A", "target_fasta": "a.fasta", "target_msa": "a.a3m"},
                {"id": "dup", "prepared_pdb": "b.pdb", "target_chain": "A",
                 "binder_chain": "B", "target_fasta": "b.fasta", "target_msa": "b.a3m"},
            ]
            _touch(manifest, json.dumps({"targets": targets}) + "\n")

            rep = validate_manifest(manifest, min_targets=3)
            self.assertFalse(rep["ok"])
            self.assertEqual(rep["failures_by_kind"]["duplicate_target"], 1)
            self.assertEqual(rep["failures_by_kind"]["bad_chains"], 1)
            self.assertEqual(rep["failures_by_kind"]["too_few_targets"], 1)

    def test_rejects_bad_rcsb_id(self):
        with tempfile.TemporaryDirectory() as d:
            manifest = os.path.join(d, "targets.json")
            _touch(manifest, json.dumps({"targets": [{
                "id": "x",
                "rcsb_id": "1BRS;rm",
                "prepared_pdb": "x.pdb",
                "target_chain": "A",
                "binder_chain": "B",
                "target_fasta": "x.fasta",
                "target_msa": "x.a3m",
            }]}) + "\n")

            rep = validate_manifest(manifest)

        self.assertFalse(rep["ok"])
        self.assertEqual(rep["failures_by_kind"]["bad_rcsb_id"], 1)

    def test_rejects_non_bool_allow_numbering_gaps(self):
        with tempfile.TemporaryDirectory() as d:
            manifest = os.path.join(d, "targets.json")
            _touch(manifest, json.dumps({"targets": [{
                "id": "x",
                "allow_numbering_gaps": "true",
                "prepared_pdb": "x.pdb",
                "target_chain": "A",
                "binder_chain": "B",
                "target_fasta": "x.fasta",
                "target_msa": "x.a3m",
            }]}) + "\n")

            rep = validate_manifest(manifest)

        self.assertFalse(rep["ok"])
        self.assertEqual(rep["failures_by_kind"]["bad_allow_numbering_gaps"], 1)

    def test_rejects_bad_prep_report(self):
        with tempfile.TemporaryDirectory() as d:
            pdb = os.path.join(d, "x.pdb")
            fasta = os.path.join(d, "x.fasta")
            msa = os.path.join(d, "x.a3m")
            report = os.path.join(d, "x.report.json")
            _touch(pdb)
            _touch(fasta, ">target\nAAAA\n")
            _touch(msa, ">target\nAAAA\n")
            _default_target_fasta_report(pdb, fasta)
            _default_target_msa_report(msa, fasta)
            _prep_report(report, binder_chain="C", contacts=0)
            manifest = os.path.join(d, "targets.json")
            _touch(manifest, json.dumps({"targets": [{"id": "x", "prepared_pdb": pdb,
                                                       "target_chain": "A", "binder_chain": "B",
                                                       "target_fasta": fasta, "target_msa": msa,
                                                       "prep_report": report}]}) + "\n")

            rep = validate_manifest(manifest, require_files=True, min_contacts=1)
            self.assertFalse(rep["ok"])
            self.assertEqual(rep["failures_by_kind"]["prep_report_mismatch"], 1)
            self.assertEqual(rep["failures_by_kind"]["prep_report_contacts"], 1)

    def test_reviewed_numbering_gap_exception_is_explicit(self):
        with tempfile.TemporaryDirectory() as d:
            pdb = os.path.join(d, "x.pdb")
            fasta = os.path.join(d, "x.fasta")
            msa = os.path.join(d, "x.a3m")
            report = os.path.join(d, "x.report.json")
            _touch(pdb)
            _touch(fasta, ">target\nAAAA\n")
            _touch(msa, ">target\nAAAA\n")
            _default_target_fasta_report(pdb, fasta)
            _default_target_msa_report(msa, fasta)
            _prep_report(report, binder_gaps=[{"after": 63, "before": 66, "missing": 2}])
            base_target = {"id": "x", "prepared_pdb": pdb,
                           "target_chain": "A", "binder_chain": "B",
                           "target_fasta": fasta, "target_msa": msa,
                           "prep_report": report}
            strict_manifest = os.path.join(d, "strict.json")
            _touch(strict_manifest, json.dumps({"targets": [base_target]}) + "\n")
            reviewed_manifest = os.path.join(d, "reviewed.json")
            reviewed_target = dict(base_target, allow_numbering_gaps=True)
            _touch(reviewed_manifest, json.dumps({"targets": [reviewed_target]}) + "\n")

            strict = validate_manifest(strict_manifest, require_files=True)
            reviewed = validate_manifest(reviewed_manifest, require_files=True)

        self.assertFalse(strict["ok"])
        self.assertEqual(strict["failures_by_kind"]["prep_report_gap"], 1)
        self.assertTrue(reviewed["ok"])
        self.assertEqual(reviewed["ready_targets"], ["x"])

    def test_reports_malformed_json_without_exception(self):
        with tempfile.TemporaryDirectory() as d:
            manifest = os.path.join(d, "targets.json")
            _touch(manifest, "{not json")

            rep = validate_manifest(manifest)
            self.assertFalse(rep["ok"])
            self.assertEqual(rep["failures_by_kind"]["bad_manifest_json"], 1)

    def test_reports_bad_prep_report_json_and_quotes_plan_paths(self):
        with tempfile.TemporaryDirectory() as d:
            pdb = os.path.join(d, "target with spaces.pdb")
            fasta = os.path.join(d, "target with spaces.fasta")
            msa = os.path.join(d, "target with spaces.a3m")
            report = os.path.join(d, "bad.report.json")
            _touch(pdb)
            _touch(fasta, ">target\nAAAA\n")
            _touch(msa, ">target\nAAAA\n")
            _default_target_fasta_report(pdb, fasta)
            _default_target_msa_report(msa, fasta)
            _touch(report, "{not json")
            manifest = os.path.join(d, "targets.json")
            _touch(manifest, json.dumps({"targets": [{"id": "x", "prepared_pdb": pdb,
                                                       "target_chain": "A", "binder_chain": "B",
                                                       "target_fasta": fasta, "target_msa": msa,
                                                       "prep_report": report}]}) + "\n")

            rep = validate_manifest(manifest, require_files=True)
            self.assertFalse(rep["ok"])
            self.assertEqual(rep["failures_by_kind"]["bad_prep_report"], 1)

            clean_report = os.path.join(d, "good.report.json")
            _prep_report(clean_report)
            clean_manifest = os.path.join(d, "clean.json")
            _touch(clean_manifest, json.dumps({"targets": [{"id": "x", "prepared_pdb": pdb,
                                                             "target_chain": "A", "binder_chain": "B",
                                                             "target_fasta": fasta, "target_msa": msa,
                                                             "prep_report": clean_report}]}) + "\n")
            clean = validate_manifest(clean_manifest, require_files=True)
            plan = render_hpc_plan(clean, clean_manifest)
            self.assertIn("PDB='", plan)
            self.assertIn("target with spaces.pdb'", plan)
            self.assertIn("TARGET_MSA='", plan)
            self.assertIn("target with spaces.a3m'", plan)
            self.assertIn("extract_chain_fasta.py --pdb '", plan)
            self.assertIn("sbatch --dependency=afterok:${GEN_00_X}", plan)

    def test_plan_uses_manifest_defaults_and_target_overrides(self):
        with tempfile.TemporaryDirectory() as d:
            pdb = os.path.join(d, "x.pdb")
            fasta = os.path.join(d, "x.fasta")
            msa = os.path.join(d, "x.a3m")
            report = os.path.join(d, "x.report.json")
            _touch(pdb)
            _touch(fasta, ">target\nAAAA\n")
            _touch(msa, ">target\nAAAA\n")
            _default_target_fasta_report(pdb, fasta)
            _default_target_msa_report(msa, fasta)
            _prep_report(report)
            manifest = os.path.join(d, "targets.json")
            _touch(manifest, json.dumps({
                "defaults": {"num_seq": 120, "temp": 0.5, "seed": 11, "objective": "panel"},
                "targets": [{
                    "id": "panel-1",
                    "prepared_pdb": pdb,
                    "target_chain": "A",
                    "binder_chain": "B",
                    "target_fasta": fasta,
                    "target_msa": msa,
                    "prep_report": report,
                    "num_seq": 80,
                }],
            }) + "\n")

            rep = validate_manifest(manifest, require_files=True)
            plan = render_hpc_plan(rep, manifest)
            self.assertIn("GEN_00_PANEL_1=$(", plan)
            self.assertIn("NUM_SEQ=80", plan)
            self.assertIn("TEMP=0.5", plan)
            self.assertIn("SEED=11", plan)
            self.assertIn("OBJECTIVE=panel", plan)
            self.assertIn("sbatch --dependency=afterok:${GEN_00_PANEL_1}", plan)

    def test_rejects_target_msa_query_mismatch_before_hpc_plan(self):
        with tempfile.TemporaryDirectory() as d:
            pdb = os.path.join(d, "x.pdb")
            fasta = os.path.join(d, "x.fasta")
            msa = os.path.join(d, "x.a3m")
            report = os.path.join(d, "x.report.json")
            _touch(pdb)
            _touch(fasta, ">target\nAAAA\n")
            _touch(msa, ">target\nAAAT\n")
            _default_target_fasta_report(pdb, fasta)
            _default_target_msa_report(msa, fasta)
            _prep_report(report)
            manifest = os.path.join(d, "targets.json")
            _touch(manifest, json.dumps({"targets": [{"id": "x", "prepared_pdb": pdb,
                                                       "target_chain": "A", "binder_chain": "B",
                                                       "target_fasta": fasta, "target_msa": msa,
                                                       "prep_report": report}]}) + "\n")

            rep = validate_manifest(manifest, require_files=True)
            self.assertFalse(rep["ok"])
            self.assertEqual(rep["failures_by_kind"]["target_msa_mismatch"], 1)

    def test_blocked_hpc_plan_marks_no_submission_commands(self):
        with tempfile.TemporaryDirectory() as d:
            pdb = os.path.join(d, "good.pdb")
            fasta = os.path.join(d, "good.fasta")
            missing_msa = os.path.join(d, "missing.a3m")
            _touch(pdb)
            _touch(fasta, ">target\nAAAA\n")
            _default_target_fasta_report(pdb, fasta)
            manifest = os.path.join(d, "targets.json")
            _touch(manifest, json.dumps({"targets": [{
                "id": "blocked",
                "prepared_pdb": pdb,
                "target_chain": "A",
                "binder_chain": "B",
                "target_fasta": fasta,
                "target_msa": missing_msa,
            }]}) + "\n")

            rep = validate_manifest(manifest, require_files=True)
            msa_plan = os.path.join(d, "custom_msa_plan.sh")
            plan = render_hpc_plan(rep, manifest, msa_plan_path=msa_plan)

        self.assertFalse(rep["ok"])
        self.assertIn("submission blocked", plan)
        self.assertIn("no sbatch submission commands emitted", plan)
        self.assertIn("run the emitted target_msa_precompute plan first", plan)
        self.assertIn(f"expected MSA plan: {msa_plan}", plan)
        self.assertNotIn("results/m6d_candidate_target_msas.sh", plan)
        self.assertIn("missing_file target=blocked field=target_msa", plan)
        self.assertNotIn("run_generate_proteinmpnn_complex.sbatch", plan)
        self.assertNotIn("run_predict_boltz_complex.sbatch", plan)

    def test_validates_declared_target_msa_report(self):
        with tempfile.TemporaryDirectory() as d:
            pdb = os.path.join(d, "x.pdb")
            fasta = os.path.join(d, "x.fasta")
            msa = os.path.join(d, "x.a3m")
            msa_report = os.path.join(d, "x.a3m.report.json")
            _touch(pdb)
            _touch(fasta, ">target\nAAAA\n")
            _touch(msa, ">target\nAAAA\n")
            _default_target_fasta_report(pdb, fasta)
            _target_msa_report(msa_report, fasta, msa)
            manifest = os.path.join(d, "targets.json")
            _touch(manifest, json.dumps({"targets": [{
                "id": "x",
                "prepared_pdb": pdb,
                "target_chain": "A",
                "binder_chain": "B",
                "target_fasta": fasta,
                "target_msa": msa,
                "target_msa_report": msa_report,
            }]}) + "\n")

            rep = validate_manifest(manifest, require_files=True)

        self.assertTrue(rep["ok"])

    def test_accepts_relocated_report_paths_when_hashes_match(self):
        with tempfile.TemporaryDirectory() as d:
            pdb = os.path.join(d, "x.pdb")
            fasta = os.path.join(d, "x.fasta")
            msa = os.path.join(d, "x.a3m")
            _touch(pdb)
            _touch(fasta, ">target\nAAAA\n")
            _touch(msa, ">target\nAAAA\n")
            _touch(fasta + ".report.json", json.dumps({
                "pdb": "/remote/project/x.pdb",
                "pdb_sha256": _sha256_file(pdb),
                "chain": "A",
                "length": 4,
                "sequence": "AAAA",
                "fasta_id": "target_A",
                "out": "/remote/project/x.fasta",
                "out_sha256": _sha256_file(fasta),
                "unknown_allowed": False,
            }) + "\n")
            _touch(msa + ".report.json", json.dumps({
                "ok": True,
                "fasta": "/remote/project/x.fasta",
                "fasta_sha256": _sha256_file(fasta),
                "out": "/remote/project/x.a3m",
                "out_sha256": _sha256_file(msa),
                "sequence_length": 4,
            }) + "\n")
            manifest = os.path.join(d, "targets.json")
            _touch(manifest, json.dumps({"targets": [{
                "id": "x",
                "prepared_pdb": pdb,
                "target_chain": "A",
                "binder_chain": "B",
                "target_fasta": fasta,
                "target_msa": msa,
            }]}) + "\n")

            rep = validate_manifest(manifest, require_files=True)

        self.assertTrue(rep["ok"])

    def test_requires_default_target_fasta_report_under_require_files(self):
        with tempfile.TemporaryDirectory() as d:
            pdb = os.path.join(d, "x.pdb")
            fasta = os.path.join(d, "x.fasta")
            msa = os.path.join(d, "x.a3m")
            _touch(pdb)
            _touch(fasta, ">target\nAAAA\n")
            _touch(msa, ">target\nAAAA\n")
            _default_target_msa_report(msa, fasta)
            manifest = os.path.join(d, "targets.json")
            _touch(manifest, json.dumps({"targets": [{
                "id": "x",
                "prepared_pdb": pdb,
                "target_chain": "A",
                "binder_chain": "B",
                "target_fasta": fasta,
                "target_msa": msa,
            }]}) + "\n")

            rep = validate_manifest(manifest, require_files=True)

        self.assertFalse(rep["ok"])
        self.assertEqual(rep["failures_by_kind"]["missing_file"], 1)
        self.assertEqual(rep["failures"][0]["field"], "target_fasta_report")
        self.assertTrue(rep["failures"][0]["message"].endswith("x.fasta.report.json"))

    def test_requires_default_target_msa_report_under_require_files(self):
        with tempfile.TemporaryDirectory() as d:
            pdb = os.path.join(d, "x.pdb")
            fasta = os.path.join(d, "x.fasta")
            msa = os.path.join(d, "x.a3m")
            _touch(pdb)
            _touch(fasta, ">target\nAAAA\n")
            _touch(msa, ">target\nAAAA\n")
            _default_target_fasta_report(pdb, fasta)
            manifest = os.path.join(d, "targets.json")
            _touch(manifest, json.dumps({"targets": [{
                "id": "x",
                "prepared_pdb": pdb,
                "target_chain": "A",
                "binder_chain": "B",
                "target_fasta": fasta,
                "target_msa": msa,
            }]}) + "\n")

            rep = validate_manifest(manifest, require_files=True)

        self.assertFalse(rep["ok"])
        self.assertEqual(rep["failures_by_kind"]["missing_file"], 1)
        self.assertEqual(rep["failures"][0]["field"], "target_msa_report")
        self.assertTrue(rep["failures"][0]["message"].endswith("x.a3m.report.json"))

    def test_rejects_incomplete_target_msa_report(self):
        with tempfile.TemporaryDirectory() as d:
            pdb = os.path.join(d, "x.pdb")
            fasta = os.path.join(d, "x.fasta")
            msa = os.path.join(d, "x.a3m")
            msa_report = os.path.join(d, "x.a3m.report.json")
            _touch(pdb)
            _touch(fasta, ">target\nAAAA\n")
            _touch(msa, ">target\nAAAA\n")
            _default_target_fasta_report(pdb, fasta)
            _touch(msa_report, json.dumps({"ok": True}) + "\n")
            manifest = os.path.join(d, "targets.json")
            _touch(manifest, json.dumps({"targets": [{
                "id": "x",
                "prepared_pdb": pdb,
                "target_chain": "A",
                "binder_chain": "B",
                "target_fasta": fasta,
                "target_msa": msa,
                "target_msa_report": msa_report,
            }]}) + "\n")

            rep = validate_manifest(manifest, require_files=True)

        self.assertFalse(rep["ok"])
        self.assertEqual(rep["failures_by_kind"]["target_msa_report_missing_field"], 5)

    def test_rejects_bad_target_msa_report_when_declared(self):
        with tempfile.TemporaryDirectory() as d:
            pdb = os.path.join(d, "x.pdb")
            fasta = os.path.join(d, "x.fasta")
            msa = os.path.join(d, "x.a3m")
            missing_report = os.path.join(d, "missing.a3m.report.json")
            bad_report = os.path.join(d, "bad.a3m.report.json")
            mismatch_report = os.path.join(d, "mismatch.a3m.report.json")
            _touch(pdb)
            _touch(fasta, ">target\nAAAA\n")
            _touch(msa, ">target\nAAAA\n")
            _default_target_fasta_report(pdb, fasta)
            _touch(bad_report, "{not json")
            _target_msa_report(mismatch_report, fasta, os.path.join(d, "other.a3m"),
                               ok=False, sequence_length=3)

            def check(report_path):
                manifest = os.path.join(d, os.path.basename(report_path) + ".manifest.json")
                _touch(manifest, json.dumps({"targets": [{
                    "id": "x",
                    "prepared_pdb": pdb,
                    "target_chain": "A",
                    "binder_chain": "B",
                    "target_fasta": fasta,
                    "target_msa": msa,
                    "target_msa_report": report_path,
                }]}) + "\n")
                return validate_manifest(manifest, require_files=True)

            missing = check(missing_report)
            bad = check(bad_report)
            mismatch = check(mismatch_report)

        self.assertFalse(missing["ok"])
        self.assertEqual(missing["failures_by_kind"]["missing_file"], 1)
        self.assertFalse(bad["ok"])
        self.assertEqual(bad["failures_by_kind"]["bad_target_msa_report"], 1)
        self.assertFalse(mismatch["ok"])
        self.assertEqual(mismatch["failures_by_kind"]["target_msa_report_not_ok"], 1)
        self.assertEqual(mismatch["failures_by_kind"]["target_msa_report_mismatch"], 2)

    def test_rejects_stale_target_msa_report_hashes(self):
        with tempfile.TemporaryDirectory() as d:
            pdb = os.path.join(d, "x.pdb")
            fasta = os.path.join(d, "x.fasta")
            msa = os.path.join(d, "x.a3m")
            msa_report = os.path.join(d, "x.a3m.report.json")
            _touch(pdb)
            _touch(fasta, ">target\nAAAA\n")
            _touch(msa, ">target\nAAAA\n")
            _default_target_fasta_report(pdb, fasta)
            _target_msa_report(msa_report, fasta, msa)
            _touch(msa, ">target\nAAAA\n>new_hit\nAAAA\n")
            manifest = os.path.join(d, "targets.json")
            _touch(manifest, json.dumps({"targets": [{
                "id": "x",
                "prepared_pdb": pdb,
                "target_chain": "A",
                "binder_chain": "B",
                "target_fasta": fasta,
                "target_msa": msa,
                "target_msa_report": msa_report,
            }]}) + "\n")

            rep = validate_manifest(manifest, require_files=True)

        self.assertFalse(rep["ok"])
        self.assertEqual(rep["failures_by_kind"]["target_msa_report_mismatch"], 1)
        self.assertIn("out_sha256", rep["failures"][0]["message"])

    def test_rejects_stale_target_fasta_report_hashes(self):
        with tempfile.TemporaryDirectory() as d:
            pdb = os.path.join(d, "x.pdb")
            fasta = os.path.join(d, "x.fasta")
            msa = os.path.join(d, "x.a3m")
            _touch(pdb)
            _touch(fasta, ">target\nAAAA\n")
            _touch(msa, ">target\nAAAA\n")
            _default_target_fasta_report(pdb, fasta)
            _default_target_msa_report(msa, fasta)
            _touch(pdb, "ATOM\nCHANGED\n")
            manifest = os.path.join(d, "targets.json")
            _touch(manifest, json.dumps({"targets": [{
                "id": "x",
                "prepared_pdb": pdb,
                "target_chain": "A",
                "binder_chain": "B",
                "target_fasta": fasta,
                "target_msa": msa,
            }]}) + "\n")

            rep = validate_manifest(manifest, require_files=True)

        self.assertFalse(rep["ok"])
        self.assertEqual(rep["failures_by_kind"]["target_fasta_report_mismatch"], 1)
        self.assertEqual(rep["failures"][0]["field"], "target_fasta_report")
        self.assertIn("pdb_sha256", rep["failures"][0]["message"])

    def test_target_msa_query_ignores_a3m_insertions_and_gaps(self):
        with tempfile.TemporaryDirectory() as d:
            pdb = os.path.join(d, "x.pdb")
            fasta = os.path.join(d, "x.fasta")
            msa = os.path.join(d, "x.a3m")
            _touch(pdb)
            _touch(fasta, ">target\nAD\n")
            _touch(msa, ">target\nA-cD\n>hit\nAXXD\n")
            _default_target_fasta_report(pdb, fasta, sequence="AD")
            _default_target_msa_report(msa, fasta, sequence_length=2)
            manifest = os.path.join(d, "targets.json")
            _touch(manifest, json.dumps({"targets": [{
                "id": "x",
                "prepared_pdb": pdb,
                "target_chain": "A",
                "binder_chain": "B",
                "target_fasta": fasta,
                "target_msa": msa,
            }]}) + "\n")

            rep = validate_manifest(manifest, require_files=True)
            self.assertTrue(rep["ok"])

    def test_can_validate_selected_target_only(self):
        with tempfile.TemporaryDirectory() as d:
            pdb = os.path.join(d, "good.pdb")
            fasta = os.path.join(d, "good.fasta")
            msa = os.path.join(d, "good.a3m")
            report = os.path.join(d, "good.report.json")
            _touch(pdb)
            _touch(fasta, ">target\nAAAA\n")
            _touch(msa, ">target\nAAAA\n")
            _default_target_fasta_report(pdb, fasta)
            _default_target_msa_report(msa, fasta)
            _prep_report(report)
            manifest = os.path.join(d, "targets.json")
            _touch(manifest, json.dumps({"targets": [
                {"id": "good", "prepared_pdb": pdb, "target_chain": "A", "binder_chain": "B",
                 "target_fasta": fasta, "target_msa": msa, "prep_report": report},
                {"id": "bad", "prepared_pdb": "missing.pdb", "target_chain": "A", "binder_chain": "B",
                 "target_fasta": "missing.fasta", "target_msa": "missing.a3m"},
            ]}) + "\n")

            rep = validate_manifest(manifest, require_files=True, min_targets=1, target_ids=["good"])
            self.assertTrue(rep["ok"])
            self.assertEqual(rep["n_targets"], 1)
            self.assertEqual(rep["ready_targets"], ["good"])
            self.assertEqual(rep["target_ids"], ["good"])

            missing = validate_manifest(manifest, require_files=True, min_targets=1, target_ids=["absent"])
            self.assertFalse(missing["ok"])
            self.assertEqual(missing["failures_by_kind"]["missing_target"], 1)

    def test_cli_can_select_target_for_validation_and_msa_plan(self):
        with tempfile.TemporaryDirectory() as d:
            pdb = os.path.join(d, "good.pdb")
            fasta = os.path.join(d, "good.fasta")
            msa = os.path.join(d, "good.a3m")
            report = os.path.join(d, "good.report.json")
            _touch(pdb)
            _touch(fasta, ">target\nAAAA\n")
            _touch(msa, ">target\nAAAA\n")
            _default_target_fasta_report(pdb, fasta)
            _default_target_msa_report(msa, fasta)
            _prep_report(report)
            manifest = os.path.join(d, "targets.json")
            out = os.path.join(d, "selected.json")
            submit_plan = os.path.join(d, "submit.sh")
            msa_plan = os.path.join(d, "msa.sh")
            _touch(manifest, json.dumps({"targets": [
                {"id": "good", "prepared_pdb": pdb, "target_chain": "A", "binder_chain": "B",
                 "target_fasta": fasta, "target_msa": msa, "prep_report": report},
                {"id": "placeholder", "prepared_pdb": "missing.pdb", "target_chain": "A",
                 "binder_chain": "B", "target_fasta": "missing.fasta", "target_msa": "missing.a3m"},
            ]}) + "\n")

            with redirect_stdout(io.StringIO()):
                rep = main([
                    "--manifest", manifest,
                    "--target-id", "good",
                    "--require-files",
                    "--out", out,
                    "--emit-plan", submit_plan,
                    "--emit-msa-plan", msa_plan,
                ])
            with open(out) as fh:
                saved = json.load(fh)
            with open(submit_plan) as fh:
                submit_text = fh.read()
            with open(msa_plan) as fh:
                msa_text = fh.read()

        self.assertTrue(rep["ok"])
        self.assertEqual(saved["target_ids"], ["good"])
        self.assertEqual(saved["ready_targets"], ["good"])
        self.assertIn({"target_id": "good", "field": "target_msa_report", "path": msa + ".report.json"},
                      saved["input_prep_artifacts"])
        self.assertFalse(any(a["target_id"] == "placeholder" for a in saved["input_prep_artifacts"]))
        self.assertIn("COMPLEX_ID=good", submit_text)
        self.assertNotIn("placeholder", submit_text)
        self.assertIn("# good", msa_text)
        self.assertNotIn("placeholder", msa_text)
        self.assertIn("# rerun_manifest_after_msa", msa_text)
        self.assertIn("--target-id good", msa_text)
        self.assertIn("--require-files", msa_text)
        self.assertIn(f"--out {out}", msa_text)
        self.assertIn(f"--emit-plan {submit_plan}", msa_text)
        self.assertNotIn("--emit-msa-plan", msa_text)

    def test_m6d_candidate_manifest_is_structurally_valid(self):
        manifest = os.path.abspath(os.path.join(
            os.path.dirname(__file__),
            "..",
            "configs",
            "m6d_candidate_complex_targets.json",
        ))

        rep = validate_manifest(manifest, require_files=False, min_targets=3)
        plan = render_target_msa_plan(manifest)

        self.assertTrue(rep["ok"])
        self.assertEqual(rep["ready_targets"], ["1BRS_AD", "2SIC_EI", "1CGI_EI"])
        self.assertIn("# 1BRS_AD", plan)
        self.assertIn("# 2SIC_EI", plan)
        self.assertIn("# 1CGI_EI", plan)


if __name__ == "__main__":
    unittest.main()
