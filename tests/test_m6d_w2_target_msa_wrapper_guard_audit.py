"""Tests for the W2 v9 target-MSA wrapper guard audit."""

import json
import os
import tempfile
import unittest

from bio_sfm_designer.experiments.m6d_w2_target_msa_wrapper_guard_audit import (
    build_audit,
    main,
    render_markdown,
)


def _write_text(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)


def _wrapper(receipt):
    return f"""#!/usr/bin/env bash
set -euo pipefail
RECEIPT="{receipt}"
APPROVAL_ENV_VAR="BIO_SFM_APPROVE_V9_TARGET_MSA"
APPROVAL_TOKEN="approve-v9-target-msa-precompute"
if [ "${{TARGET_MSA_PRECOMPUTE_DRY_RUN:-0}}" = "1" ]; then
  exit 0
fi
if [ "${{BIO_SFM_APPROVE_V9_TARGET_MSA:-}}" != "$APPROVAL_TOKEN" ]; then
  echo "refusing v9 target-MSA submission without explicit approval env:" >&2
  exit 2
fi
mkdir -p "$(dirname "$RECEIPT")"
: > "$RECEIPT"
"""


class M6DW2TargetMsaWrapperGuardAuditTests(unittest.TestCase):
    def test_static_and_no_env_guard_pass_without_receipt_side_effect(self):
        with tempfile.TemporaryDirectory() as d:
            receipt = os.path.join(d, "receipt.jsonl")
            wrapper = os.path.join(d, "wrapper.sh")
            _write_text(wrapper, _wrapper(receipt))

            rep = build_audit(wrapper, receipt, run_no_env_check=True)

        self.assertTrue(rep["audit_ok"])
        self.assertTrue(rep["static_audit"]["ok"])
        self.assertTrue(rep["no_env_run"]["ok"])
        self.assertEqual(rep["no_env_run"]["returncode"], 2)
        self.assertFalse(rep["no_env_run"]["receipt_exists_after"])
        self.assertIn("Required approval environment", render_markdown(rep))

    def test_static_audit_blocks_receipt_truncate_before_approval_guard(self):
        with tempfile.TemporaryDirectory() as d:
            receipt = os.path.join(d, "receipt.jsonl")
            wrapper = os.path.join(d, "wrapper.sh")
            _write_text(
                wrapper,
                f"""#!/usr/bin/env bash
RECEIPT="{receipt}"
APPROVAL_ENV_VAR="BIO_SFM_APPROVE_V9_TARGET_MSA"
APPROVAL_TOKEN="approve-v9-target-msa-precompute"
TARGET_MSA_PRECOMPUTE_DRY_RUN=0
: > "$RECEIPT"
if [ "${{BIO_SFM_APPROVE_V9_TARGET_MSA:-}}" != "$APPROVAL_TOKEN" ]; then
  echo "refusing v9 target-MSA submission without explicit approval env:" >&2
  exit 2
fi
mkdir -p "$(dirname "$RECEIPT")"
""",
            )

            rep = build_audit(wrapper, receipt, run_no_env_check=True)

        self.assertFalse(rep["audit_ok"])
        kinds = {failure["kind"] for failure in rep["failures"]}
        self.assertIn("approval_guard_not_before_receipt_truncate", kinds)
        self.assertIn("no_env_runtime_guard_failed", kinds)
        self.assertFalse(rep["no_env_run"]["ran"])

    def test_cli_writes_audit(self):
        with tempfile.TemporaryDirectory() as d:
            receipt = os.path.join(d, "receipt.jsonl")
            wrapper = os.path.join(d, "wrapper.sh")
            out_json = os.path.join(d, "audit.json")
            out_md = os.path.join(d, "audit.md")
            _write_text(wrapper, _wrapper(receipt))

            rc = main([
                "--wrapper", wrapper,
                "--receipt", receipt,
                "--run-no-env-check",
                "--out-json", out_json,
                "--out-md", out_md,
            ])

            self.assertEqual(rc, 0)
            with open(out_json) as fh:
                rep = json.load(fh)
            self.assertTrue(rep["audit_ok"])
            self.assertTrue(os.path.exists(out_md))


if __name__ == "__main__":
    unittest.main()
