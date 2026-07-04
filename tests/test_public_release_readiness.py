"""Tests for the public release readiness audit."""

import json
import os
import tempfile
import unittest

from bio_sfm_designer.experiments.public_release_readiness import (
    build_audit,
    main,
    render_markdown,
)


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)


def _minimal_claim_text():
    return """
This is not a publication plan.
The core mechanism is an external calibrated trust gate.
Current W2 results are not W2 generalization evidence.
Pooled-only evidence is not proof.
Independent-predictor robustness is not supported.
"""


def _write_public_skeleton(root):
    _write(os.path.join(root, "README.md"), _minimal_claim_text())
    _write(os.path.join(root, "LICENSE"), "MIT\n")
    _write(os.path.join(root, "pyproject.toml"), "\n".join([
        "[project]",
        "name = 'demo'",
        "dependencies = [",
        "  'bio-sfm-trust @ git+https://github.com/jang1563/bio-sfm-trust-core.git@abc123'",
        "]",
        "",
    ]))
    _write(os.path.join(root, "SECURITY.md"), "# Security\n")
    _write(os.path.join(root, "CITATION.cff"), "cff-version: 1.2.0\n")
    _write(os.path.join(root, "CONTRIBUTING.md"), "# Contributing\n")
    _write(os.path.join(root, ".github", "workflows", "ci.yml"), "name: ci\n")
    _write(os.path.join(root, "docs", "ARCHITECTURE.md"), "# Architecture\n")
    _write(os.path.join(root, "docs", "BACKGROUND.md"), "# Background\n")
    _write(os.path.join(root, "docs", "PROJECT_ROADMAP.md"), _minimal_claim_text())


class PublicReleaseReadinessTests(unittest.TestCase):
    def test_public_skeleton_is_ready(self):
        with tempfile.TemporaryDirectory() as d:
            _write_public_skeleton(d)

            rep = build_audit(d, repo_visibility="public")

            self.assertTrue(rep["audit_ok"])
            self.assertTrue(rep["public_ready"])
            self.assertEqual(rep["status"], "public_release_ready")
            self.assertEqual(rep["summary"]["n_blockers"], 0)
            self.assertIn("Public Release Readiness Audit", render_markdown(rep))

    def test_private_visibility_and_missing_governance_block_release(self):
        with tempfile.TemporaryDirectory() as d:
            _write(os.path.join(d, "README.md"), _minimal_claim_text())
            _write(os.path.join(d, "LICENSE"), "MIT\n")
            _write(os.path.join(d, "pyproject.toml"), "[project]\nname = 'demo'\n")

            rep = build_audit(d, repo_visibility="private")

            self.assertFalse(rep["audit_ok"])
            self.assertEqual(rep["status"], "public_release_blocked")
            kinds = {finding["kind"] for finding in rep["findings"]}
            self.assertIn("repository_not_publicly_visible", kinds)
            self.assertIn("missing_required_public_file", kinds)

    def test_secret_like_token_is_blocker_and_redacted(self):
        with tempfile.TemporaryDirectory() as d:
            _write_public_skeleton(d)
            secret = "sk-ant-" + ("A" * 36)
            _write(os.path.join(d, "src", "bad.py"), f"API_KEY = '{secret}'\n")

            rep = build_audit(d, repo_visibility="public")

            self.assertFalse(rep["audit_ok"])
            hits = [f for f in rep["findings"] if f["kind"] == "anthropic_api_key"]
            self.assertEqual(len(hits), 1)
            self.assertNotIn(secret, hits[0]["snippet"])
            self.assertIn("REDACTED", hits[0]["snippet"])

    def test_internal_paths_and_key_incident_notes_are_blockers(self):
        with tempfile.TemporaryDirectory() as d:
            _write_public_skeleton(d)
            local_path = "/" + "Users" + "/jak4013/demo"
            login_host = "cayuga-" + "login1"
            key_phrase = "exposed " + "sk-ant-"
            _write(
                os.path.join(d, "HANDOFF.md"),
                f"Use {local_path} and {login_host}. "
                f"An {key_phrase} key was seen elsewhere.\n",
            )

            rep = build_audit(d, repo_visibility="public")

            self.assertFalse(rep["audit_ok"])
            kinds = {finding["kind"] for finding in rep["findings"]}
            self.assertIn("local_absolute_path", kinds)
            self.assertIn("cayuga_login_host", kinds)
            self.assertIn("exposed_key_incident_note", kinds)

    def test_bare_trust_dependency_blocks_public_installability(self):
        with tempfile.TemporaryDirectory() as d:
            _write_public_skeleton(d)
            _write(os.path.join(d, "pyproject.toml"), "\n".join([
                "[project]",
                "name = 'demo'",
                "dependencies = ['bio-sfm-trust']",
                "",
            ]))

            rep = build_audit(d, repo_visibility="public")

            self.assertFalse(rep["audit_ok"])
            kinds = {finding["kind"] for finding in rep["findings"]}
            self.assertIn("bio_sfm_trust_dependency_not_public_installable", kinds)

    def test_cli_writes_json_and_markdown(self):
        with tempfile.TemporaryDirectory() as d:
            _write(os.path.join(d, "README.md"), _minimal_claim_text())
            out_json = os.path.join(d, "results", "audit.json")
            out_md = os.path.join(d, "results", "audit.md")

            rc = main([
                "--root", d,
                "--repo-visibility", "private",
                "--out-json", out_json,
                "--out-md", out_md,
            ])

            self.assertEqual(rc, 1)
            with open(out_json) as fh:
                rep = json.load(fh)
            self.assertFalse(rep["audit_ok"])
            self.assertTrue(os.path.exists(out_md))


if __name__ == "__main__":
    unittest.main()
