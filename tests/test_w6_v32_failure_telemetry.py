import json
import unittest

from bio_sfm_designer.experiments.w6_v32_failure_telemetry import (
    classify_provider_failure,
    success_telemetry,
    validate_failure_telemetry,
)


class ProviderFailure(RuntimeError):
    status_code = 503


class W6V32FailureTelemetryTests(unittest.TestCase):
    def test_success_record_contains_no_failure_payload(self):
        record = validate_failure_telemetry(success_telemetry())
        self.assertEqual(record["outcome"], "success")
        self.assertIsNone(record["safe_reason_code"])
        self.assertFalse(record["retry_authorized"])

    def test_known_empty_text_error_gets_a_stable_safe_code(self):
        record = classify_provider_failure(
            RuntimeError("Anthropic response did not contain a text block")
        )
        self.assertEqual(record["safe_reason_code"], "empty_text_response")
        self.assertEqual(record["transience_class"], "unknown")

    def test_http_status_takes_precedence_without_storing_message(self):
        secret = "sk-ant-" + ("A" * 40)
        record = validate_failure_telemetry(
            classify_provider_failure(ProviderFailure(secret))
        )
        serialized = json.dumps(record)
        self.assertEqual(record["safe_reason_code"], "server_error")
        self.assertEqual(record["http_status"], 503)
        self.assertEqual(record["transience_class"], "potentially_transient")
        self.assertNotIn(secret, serialized)
        self.assertNotIn("sk-ant-", serialized)

    def test_rate_limit_type_is_classified_without_retry_authority(self):
        error = type("RateLimitError", (Exception,), {})("sensitive message")
        record = classify_provider_failure(error)
        self.assertEqual(record["safe_reason_code"], "rate_limit")
        self.assertFalse(record["retry_authorized"])

    def test_validator_rejects_message_storage_flags(self):
        record = classify_provider_failure(RuntimeError("opaque"))
        record["exception_message_stored"] = True
        with self.assertRaisesRegex(ValueError, "exception_message_stored"):
            validate_failure_telemetry(record)

    def test_validator_rejects_retry_authority(self):
        record = classify_provider_failure(RuntimeError("opaque"))
        record["retry_authorized"] = True
        with self.assertRaisesRegex(ValueError, "cannot authorize retries"):
            validate_failure_telemetry(record)


if __name__ == "__main__":
    unittest.main()
