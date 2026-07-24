import json
import unittest
from types import SimpleNamespace

from bio_sfm_designer.loop.providers import (
    AnthropicMessagesProvider,
    FixtureOrchestrationProvider,
    OpenAIResponsesProvider,
    OrchestrationProviderResult,
    call_provider_with_metadata,
    get_orchestration_provider,
    is_live_provider,
)


class _FakeOpenAIResponses:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            output_text='{"reason": "bounded", "hypothesis": "collect evidence"}',
            status="completed",
            incomplete_details=None,
            usage=SimpleNamespace(input_tokens=17, output_tokens=11),
        )


class _FakeAnthropicMessages:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            content=[
                SimpleNamespace(type="thinking", text="private"),
                SimpleNamespace(
                    type="text",
                    text='{"reason": "bounded", "hypothesis": "collect evidence"}',
                ),
            ],
            stop_reason="end_turn",
            usage=SimpleNamespace(input_tokens=19, output_tokens=13),
        )


class ProviderTests(unittest.TestCase):
    def test_fixture_matches_orchestration_contract_shape(self):
        provider = FixtureOrchestrationProvider()
        payload = json.loads(provider("prompt"))
        self.assertEqual(set(payload), {"reason", "hypothesis"})
        result = provider.call_with_metadata("prompt")
        self.assertEqual(result.stop_reason, "fixture_complete")

    def test_openai_adapter_is_bounded_and_returns_output_text(self):
        responses = _FakeOpenAIResponses()
        client = SimpleNamespace(responses=responses)
        provider = OpenAIResponsesProvider(
            model="test-openai-model",
            max_output_tokens=123,
            client=client,
        )
        self.assertEqual(
            provider("hello"),
            '{"reason": "bounded", "hypothesis": "collect evidence"}',
        )
        self.assertEqual(
            responses.calls,
            [
                {
                    "model": "test-openai-model",
                    "input": "hello",
                    "max_output_tokens": 123,
                    "store": False,
                }
            ],
        )
        result = provider.call_with_metadata("hello again")
        self.assertEqual(result.input_tokens, 17)
        self.assertEqual(result.output_tokens, 11)
        self.assertEqual(result.stop_reason, "completed")

    def test_anthropic_adapter_keeps_only_text_blocks(self):
        messages = _FakeAnthropicMessages()
        client = SimpleNamespace(messages=messages)
        provider = AnthropicMessagesProvider(
            model="test-anthropic-model",
            max_output_tokens=234,
            client=client,
        )
        self.assertEqual(
            provider("hello"),
            '{"reason": "bounded", "hypothesis": "collect evidence"}',
        )
        self.assertEqual(messages.calls[0]["model"], "test-anthropic-model")
        self.assertEqual(messages.calls[0]["max_tokens"], 234)
        result = provider.call_with_metadata("hello again")
        self.assertEqual(result.input_tokens, 19)
        self.assertEqual(result.output_tokens, 13)
        self.assertEqual(result.stop_reason, "end_turn")

    def test_metadata_helper_preserves_legacy_callable_contract(self):
        result = call_provider_with_metadata(lambda prompt: f"raw:{prompt}", "x")
        self.assertEqual(
            result,
            OrchestrationProviderResult(text="raw:x"),
        )

    def test_metadata_helper_rejects_non_string_legacy_result(self):
        with self.assertRaisesRegex(TypeError, "non-string"):
            call_provider_with_metadata(lambda prompt: 123, "x")

    def test_live_provider_requires_credential_hygiene_attestation(self):
        with self.assertRaisesRegex(RuntimeError, "P0 credential hygiene"):
            get_orchestration_provider(
                "anthropic",
                model="test-model",
                credential_hygiene_attested=False,
            )

    def test_live_provider_requires_explicit_model(self):
        with self.assertRaisesRegex(ValueError, "explicit model"):
            get_orchestration_provider(
                "openai",
                credential_hygiene_attested=True,
            )

    def test_fixture_needs_no_key_or_attestation(self):
        provider = get_orchestration_provider("fixture")
        self.assertIsInstance(provider, FixtureOrchestrationProvider)

    def test_live_provider_classification(self):
        self.assertTrue(is_live_provider("openai"))
        self.assertTrue(is_live_provider("anthropic"))
        self.assertFalse(is_live_provider("fixture"))
        self.assertFalse(is_live_provider(None))

    def test_response_budget_is_bounded(self):
        with self.assertRaisesRegex(ValueError, r"\[1, 1024\]"):
            OpenAIResponsesProvider(model="x", max_output_tokens=1025)


if __name__ == "__main__":
    unittest.main()
