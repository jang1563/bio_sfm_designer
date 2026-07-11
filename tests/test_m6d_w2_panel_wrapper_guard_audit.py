"""Tests for the W2 v9 panel wrapper guard audit."""

import json
import os
import tempfile
import unittest

from bio_sfm_designer.experiments.m6d_w2_panel_wrapper_guard_audit import (
    build_audit,
    main,
    render_markdown,
)


def _write_text(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)


def _wrapper(
    receipt,
    *,
    approval_env_var="BIO_SFM_APPROVE_V9_PANEL",
    approval_token="approve-v9-panel-submit",
    dry_run_env_var="M6D_W2_V9_SUBMIT_DRY_RUN",
    refusal_message="refusing v9 panel submission without explicit approval env:",
):
    return f"""#!/usr/bin/env bash
set -euo pipefail
export SUBMIT_RECEIPT="${{SUBMIT_RECEIPT:-{receipt}}}"
export BIO_SFM_SUBMIT_DRY_RUN="${{{dry_run_env_var}:-${{BIO_SFM_SUBMIT_DRY_RUN:-0}}}}"
APPROVAL_ENV_VAR="{approval_env_var}"
APPROVAL_TOKEN="{approval_token}"
if [ "${{BIO_SFM_SUBMIT_DRY_RUN:-0}}" = "1" ]; then
  exec "$SCRIPT_DIR/../hpc/m6d_w2_submit_with_receipt.sh"
fi
if [ "${{{approval_env_var}:-}}" != "$APPROVAL_TOKEN" ]; then
  echo "{refusal_message}" >&2
  exit 2
fi
exec "$SCRIPT_DIR/../hpc/m6d_w2_submit_with_receipt.sh"
"""


class M6DW2PanelWrapperGuardAuditTests(unittest.TestCase):
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

    def test_static_and_no_env_guard_pass_with_v11_parameters(self):
        with tempfile.TemporaryDirectory() as d:
            receipt = os.path.join(d, "receipt.jsonl")
            wrapper = os.path.join(d, "wrapper.sh")
            _write_text(
                wrapper,
                _wrapper(
                    receipt,
                    approval_env_var="BIO_SFM_APPROVE_V11_PANEL",
                    approval_token="approve-v11-panel-submit",
                    dry_run_env_var="M6D_W2_V11_SUBMIT_DRY_RUN",
                    refusal_message="refusing v11 panel submission without explicit approval env:",
                ),
            )

            rep = build_audit(
                wrapper,
                receipt,
                run_no_env_check=True,
                approval_env_var="BIO_SFM_APPROVE_V11_PANEL",
                approval_token="approve-v11-panel-submit",
                dry_run_env_var="M6D_W2_V11_SUBMIT_DRY_RUN",
                refusal_message="refusing v11 panel submission without explicit approval env",
                panel_label="W2 v11 panel",
            )

        self.assertTrue(rep["audit_ok"])
        self.assertEqual(rep["panel_approval_env_var"], "BIO_SFM_APPROVE_V11_PANEL")
        self.assertEqual(rep["panel_approval_env_value"], "approve-v11-panel-submit")
        self.assertEqual(rep["dry_run_env_var"], "M6D_W2_V11_SUBMIT_DRY_RUN")
        self.assertEqual(rep["panel_label"], "W2 v11 panel")
        self.assertIn("W2 v11 panel submission", rep["next_action"])

    def test_static_audit_blocks_shared_wrapper_exec_before_approval_guard(self):
        with tempfile.TemporaryDirectory() as d:
            receipt = os.path.join(d, "receipt.jsonl")
            wrapper = os.path.join(d, "wrapper.sh")
            _write_text(
                wrapper,
                f"""#!/usr/bin/env bash
export SUBMIT_RECEIPT="${{SUBMIT_RECEIPT:-{receipt}}}"
export BIO_SFM_SUBMIT_DRY_RUN="${{M6D_W2_V9_SUBMIT_DRY_RUN:-${{BIO_SFM_SUBMIT_DRY_RUN:-0}}}}"
APPROVAL_ENV_VAR="BIO_SFM_APPROVE_V9_PANEL"
APPROVAL_TOKEN="approve-v9-panel-submit"
TARGET="m6d_w2_submit_with_receipt.sh"
exec "$TARGET"
if [ "${{BIO_SFM_APPROVE_V9_PANEL:-}}" != "$APPROVAL_TOKEN" ]; then
  echo "refusing v9 panel submission without explicit approval env:" >&2
  exit 2
fi
""",
            )

            rep = build_audit(wrapper, receipt, run_no_env_check=True)

        self.assertFalse(rep["audit_ok"])
        kinds = {failure["kind"] for failure in rep["failures"]}
        self.assertIn("approval_guard_not_before_shared_submit_wrapper", kinds)
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
