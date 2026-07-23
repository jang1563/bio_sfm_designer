import json
import unittest
from types import SimpleNamespace

from bio_sfm_designer.loop.providers import (
    AnthropicMessagesProvider,
    FixtureOrchestrationProvider,
    OpenAIResponsesProvider,
    get_orchestration_provider,
    is_live_provider,
)


class _FakeOpenAIResponses:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(output_text='{"stop": false}')


class _FakeAnthropicMessages:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            content=[
                SimpleNamespace(type="thinking", text="private"),
                SimpleNamespace(type="text", text='{"stop": false}'),
            ]
        )


class ProviderTests(unittest.TestCase):
    def test_fixture_matches_orchestration_contract_shape(self):
        payload = json.loads(FixtureOrchestrationProvider()("prompt"))
        self.assertEqual(set(payload), {"stop", "reason", "hypothesis", "explore"})

    def test_openai_adapter_is_bounded_and_returns_output_text(self):
        responses = _FakeOpenAIResponses()
        client = SimpleNamespace(responses=responses)
        provider = OpenAIResponsesProvider(
            model="test-openai-model",
            max_output_tokens=123,
            client=client,
        )
        self.assertEqual(provider("hello"), '{"stop": false}')
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

    def test_anthropic_adapter_keeps_only_text_blocks(self):
        messages = _FakeAnthropicMessages()
        client = SimpleNamespace(messages=messages)
        provider = AnthropicMessagesProvider(
            model="test-anthropic-model",
            max_output_tokens=234,
            client=client,
        )
        self.assertEqual(provider("hello"), '{"stop": false}')
        self.assertEqual(messages.calls[0]["model"], "test-anthropic-model")
        self.assertEqual(messages.calls[0]["max_tokens"], 234)

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
