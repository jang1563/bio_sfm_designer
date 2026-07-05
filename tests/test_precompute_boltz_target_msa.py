"""Tests for one-time Boltz target-MSA precompute wrapper."""

import importlib.util
import hashlib
import json
import os
import sys
import tempfile
import unittest

_HPC = os.path.join(os.path.dirname(__file__), "..", "hpc")


def _load():
    path = os.path.join(_HPC, "precompute_boltz_target_msa.py")
    spec = importlib.util.spec_from_file_location("precompute_boltz_target_msa_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


class PrecomputeBoltzTargetMsaTests(unittest.TestCase):
    def test_existing_matching_msa_is_reused_without_boltz(self):
        mod = _load()
        with tempfile.TemporaryDirectory() as d:
            fasta = os.path.join(d, "target.fasta")
            out = os.path.join(d, "target.a3m")
            report = os.path.join(d, "target.report.json")
            _write(fasta, ">target\nACD\n")
            _write(out, ">target\nACde-D\n>hit\nACXXD\n\x00")

            def fail_run(*_args, **_kwargs):
                raise AssertionError("Boltz should not run for an existing matching MSA")

            original_run = mod.subprocess.run
            mod.subprocess.run = fail_run
            try:
                rep = mod.precompute_target_msa(fasta=fasta, out=out, report=report)
            finally:
                mod.subprocess.run = original_run

            self.assertTrue(rep["ok"])
            self.assertTrue(rep["reused_existing"])
            self.assertEqual(rep["out_sanitized_nul_bytes"], 1)
            with open(out, "rb") as fh:
                self.assertNotIn(b"\x00", fh.read())
            with open(report) as fh:
                saved = json.load(fh)
            self.assertTrue(saved["reused_existing"])
            self.assertEqual(saved["out_sanitized_nul_bytes"], 1)
            self.assertEqual(saved["fasta"], fasta)
            self.assertEqual(saved["fasta_abs"], os.path.abspath(fasta))
            self.assertEqual(saved["out"], out)
            self.assertEqual(saved["out_abs"], os.path.abspath(out))
            self.assertEqual(saved["fasta_sha256"], _sha256_file(fasta))
            self.assertEqual(saved["out_sha256"], _sha256_file(out))
            self.assertEqual(saved["sequence_length"], 3)

    def test_fake_boltz_run_extracts_matching_a3m(self):
        mod = _load()
        seen = {}

        def fake_run(cmd, **_kwargs):
            seen["cmd"] = cmd
            outdir = cmd[cmd.index("--out_dir") + 1]
            _write(os.path.join(outdir, "processed", "target", "msa", "server.a3m"),
                   ">query\nACde-D\n>hit\nACXXD\n")

        original_run = mod.subprocess.run
        mod.subprocess.run = fake_run
        try:
            with tempfile.TemporaryDirectory() as d:
                fasta = os.path.join(d, "target.fasta")
                out = os.path.join(d, "target.a3m")
                report = os.path.join(d, "target.report.json")
                _write(fasta, ">target\nACD\n")

                rep = mod.precompute_target_msa(
                    fasta=fasta,
                    out=out,
                    report=report,
                    boltz="/bin/true",
                    work_dir=os.path.join(d, "work"),
                    msa_server_url="https://api.colabfold.com",
                )

                self.assertFalse(rep["reused_existing"])
                self.assertTrue(os.path.exists(out))
                with open(out) as fh:
                    self.assertIn("ACde-D", fh.read())
                with open(out, "rb") as fh:
                    self.assertNotIn(b"\x00", fh.read())
                self.assertIn("--use_msa_server", seen["cmd"])
                self.assertIn("--msa_server_url", seen["cmd"])
                self.assertEqual(rep["sequence_length"], 3)
                with open(report) as fh:
                    saved = json.load(fh)
                self.assertEqual(saved["source_msa"], rep["source_msa"])
                self.assertEqual(saved["fasta"], fasta)
                self.assertEqual(saved["fasta_abs"], os.path.abspath(fasta))
                self.assertEqual(saved["out"], out)
                self.assertEqual(saved["out_abs"], os.path.abspath(out))
                self.assertEqual(saved["fasta_sha256"], _sha256_file(fasta))
                self.assertEqual(saved["out_sha256"], _sha256_file(out))
                self.assertEqual(saved["sequence_length"], 3)
        finally:
            mod.subprocess.run = original_run

    def test_report_preserves_declared_relative_paths_for_sync_back(self):
        mod = _load()
        cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as d:
            os.chdir(d)
            try:
                fasta = os.path.join("inputs", "target.fasta")
                out = os.path.join("outputs", "target.a3m")
                report = out + ".report.json"
                _write(fasta, ">target\nACD\n")
                _write(out, ">target\nACde-D\n")

                def fail_run(*_args, **_kwargs):
                    raise AssertionError("Boltz should not run for an existing matching MSA")

                original_run = mod.subprocess.run
                mod.subprocess.run = fail_run
                try:
                    mod.precompute_target_msa(fasta=fasta, out=out, report=report)
                finally:
                    mod.subprocess.run = original_run

                with open(report) as fh:
                    saved = json.load(fh)
                self.assertEqual(saved["fasta"], fasta)
                self.assertEqual(saved["out"], out)
                self.assertEqual(saved["fasta_abs"], os.path.abspath(fasta))
                self.assertEqual(saved["out_abs"], os.path.abspath(out))
            finally:
                os.chdir(cwd)

    def test_keep_work_recovers_existing_matching_a3m_without_boltz(self):
        mod = _load()
        with tempfile.TemporaryDirectory() as d:
            fasta = os.path.join(d, "target.fasta")
            out = os.path.join(d, "target.a3m")
            report = os.path.join(d, "target.report.json")
            work = os.path.join(d, "work")
            _write(fasta, ">target\nACD\n")
            _write(os.path.join(work, "boltz_results_target", "msa", "server.a3m"),
                   ">query\nACde-D\n>hit\nACXXD\n")

            def fail_run(*_args, **_kwargs):
                raise AssertionError("Boltz should not run when keep_work has a matching MSA")

            original_run = mod.subprocess.run
            mod.subprocess.run = fail_run
            try:
                rep = mod.precompute_target_msa(
                    fasta=fasta,
                    out=out,
                    report=report,
                    boltz="/bin/true",
                    work_dir=work,
                    keep_work=True,
                )
            finally:
                mod.subprocess.run = original_run

            self.assertTrue(rep["ok"])
            self.assertFalse(rep["reused_existing"])
            self.assertTrue(rep["recovered_existing_work"])
            self.assertFalse(rep["recovered_after_boltz_failure"])
            with open(out) as fh:
                self.assertIn("ACde-D", fh.read())
            with open(report) as fh:
                saved = json.load(fh)
            self.assertTrue(saved["recovered_existing_work"])

    def test_boltz_failure_recovers_matching_a3m(self):
        mod = _load()

        def fake_run(cmd, **_kwargs):
            outdir = cmd[cmd.index("--out_dir") + 1]
            _write(os.path.join(outdir, "processed", "target", "msa", "server.a3m"),
                   ">query\nACde-D\n>hit\nACXXD\n")
            raise mod.subprocess.CalledProcessError(7, cmd)

        original_run = mod.subprocess.run
        mod.subprocess.run = fake_run
        try:
            with tempfile.TemporaryDirectory() as d:
                fasta = os.path.join(d, "target.fasta")
                out = os.path.join(d, "target.a3m")
                report = os.path.join(d, "target.report.json")
                _write(fasta, ">target\nACD\n")

                rep = mod.precompute_target_msa(
                    fasta=fasta,
                    out=out,
                    report=report,
                    boltz="/bin/true",
                    work_dir=os.path.join(d, "work"),
                )

                self.assertTrue(rep["ok"])
                self.assertFalse(rep["reused_existing"])
                self.assertFalse(rep["recovered_existing_work"])
                self.assertTrue(rep["recovered_after_boltz_failure"])
                self.assertEqual(rep["boltz_returncode"], 7)
                with open(out) as fh:
                    self.assertIn("ACde-D", fh.read())
                with open(report) as fh:
                    saved = json.load(fh)
                self.assertTrue(saved["recovered_after_boltz_failure"])
                self.assertEqual(saved["boltz_returncode"], 7)
        finally:
            mod.subprocess.run = original_run

    def test_mismatched_existing_msa_is_rejected(self):
        mod = _load()
        with tempfile.TemporaryDirectory() as d:
            fasta = os.path.join(d, "target.fasta")
            out = os.path.join(d, "target.a3m")
            _write(fasta, ">target\nAAAA\n")
            _write(out, ">target\nAAAT\n")

            with self.assertRaisesRegex(ValueError, "does not match FASTA"):
                mod.precompute_target_msa(fasta=fasta, out=out)

    def test_cli_writes_report_with_fake_boltz(self):
        mod = _load()

        def fake_run(cmd, **_kwargs):
            outdir = cmd[cmd.index("--out_dir") + 1]
            _write(os.path.join(outdir, "processed", "target.a3m"), ">target\nAAAA\n")

        original_run = mod.subprocess.run
        mod.subprocess.run = fake_run
        try:
            with tempfile.TemporaryDirectory() as d:
                fasta = os.path.join(d, "target.fasta")
                out = os.path.join(d, "target.a3m")
                report = os.path.join(d, "target.report.json")
                _write(fasta, ">target\nAAAA\n")
                argv = sys.argv
                sys.argv = [
                    "precompute_boltz_target_msa.py",
                    "--fasta", fasta,
                    "--out", out,
                    "--report", report,
                    "--work-dir", os.path.join(d, "work"),
                    "--boltz", "/bin/true",
                ]
                try:
                    rep = mod.main()
                finally:
                    sys.argv = argv

                self.assertTrue(rep["ok"])
                self.assertTrue(os.path.exists(report))
        finally:
            mod.subprocess.run = original_run


if __name__ == "__main__":
    unittest.main()
