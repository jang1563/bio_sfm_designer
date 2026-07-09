"""Tests for tracked public-surface sanitization."""

import json
import os
import subprocess
import tempfile
import unittest

from bio_sfm_designer.experiments.public_release_readiness import (
    CAYUGA_HOME_PATH,
    CAYUGA_LOGIN_PREFIX,
)
from bio_sfm_designer.experiments.public_surface_sanitize import (
    build_report,
    main,
    render_markdown,
)


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)


def _read(path):
    with open(path) as fh:
        return fh.read()


class PublicSurfaceSanitizeTests(unittest.TestCase):
    def test_dry_run_reports_tracked_result_replacements_without_writing(self):
        with tempfile.TemporaryDirectory() as d:
            tracked = os.path.join(d, "results", "tracked.json")
            _write(
                tracked,
                f'{{"root": "{d}", "remote": "{CAYUGA_LOGIN_PREFIX}1:{CAYUGA_HOME_PATH}/bio_sfm_smoke"}}\n',
            )
            subprocess.run(["git", "init", "-q"], cwd=d, check=True)
            subprocess.run(["git", "add", "."], cwd=d, check=True)

            rep = build_report(root=d)

            self.assertTrue(rep["audit_ok"])
            self.assertEqual(rep["status"], "public_surface_sanitize_needed")
            self.assertEqual(rep["changed_file_count"], 1)
            self.assertIn("tracked.json", rep["changed_files"][0]["path"])
            self.assertIn(CAYUGA_HOME_PATH, _read(tracked))
            self.assertIn("Public Surface Sanitizer", render_markdown(rep))

    def test_apply_sanitizes_tracked_results_but_not_untracked_private_runbook(self):
        with tempfile.TemporaryDirectory() as d:
            tracked = os.path.join(d, "results", "tracked.json")
            private = os.path.join(d, "results", "private_runbook.json")
            _write(
                tracked,
                f'{{"root": "{d}", "remote": "{CAYUGA_LOGIN_PREFIX}1:{CAYUGA_HOME_PATH}/bio_sfm_smoke"}}\n',
            )
            _write(private, f"ssh {CAYUGA_LOGIN_PREFIX}1 'cd {CAYUGA_HOME_PATH}/bio_sfm_smoke'\n")
            subprocess.run(["git", "init", "-q"], cwd=d, check=True)
            subprocess.run(["git", "add", tracked], cwd=d, check=True)

            rep = build_report(root=d, apply=True)

            self.assertTrue(rep["audit_ok"])
            self.assertEqual(rep["status"], "public_surface_sanitized")
            self.assertIn("<repo-root>", _read(tracked))
            self.assertIn("<hpc-login-host>", _read(tracked))
            self.assertIn("/home/fs01/<user>", _read(tracked))
            self.assertIn(CAYUGA_HOME_PATH, _read(private))
            self.assertIn(CAYUGA_LOGIN_PREFIX + "1", _read(private))

    def test_cli_writes_report(self):
        with tempfile.TemporaryDirectory() as d:
            tracked = os.path.join(d, "results", "tracked.json")
            out_json = os.path.join(d, "report.json")
            out_md = os.path.join(d, "report.md")
            _write(tracked, f'{{"remote": "{CAYUGA_HOME_PATH}/bio_sfm_smoke"}}\n')
            subprocess.run(["git", "init", "-q"], cwd=d, check=True)
            subprocess.run(["git", "add", "."], cwd=d, check=True)

            rc = main(["--root", d, "--out-json", out_json, "--out-md", out_md])

            self.assertEqual(rc, 0)
            with open(out_json) as fh:
                rep = json.load(fh)
            self.assertEqual(rep["changed_file_count"], 1)
            self.assertTrue(os.path.exists(out_md))


if __name__ == "__main__":
    unittest.main()
