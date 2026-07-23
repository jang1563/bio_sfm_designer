"""Optional LLM providers for DBTL orchestration.

The provider boundary is deliberately small: ``prompt -> raw text``. Parsing,
authority, and audit logging stay in :mod:`loop.interpreter`, so a provider can
never call the trust gate or submit compute.
"""

from __future__ import annotations

import json
from typing import Any, Optional


_LIVE_PROVIDERS = {"anthropic", "anthropic_messages", "openai", "openai_responses"}
_FIXTURE_PROVIDERS = {"fixture", "mock", "mock_defer", "mock_orchestrator"}


def _validate_max_output_tokens(value: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 1024:
        raise ValueError("max_output_tokens must be an integer in [1, 1024]")
    return value


class FixtureOrchestrationProvider:
    """Dependency-free, deterministic provider used for contract tests."""

    provider_name = "fixture"
    model = "deterministic-orchestrator-v1"

    def __call__(self, prompt: str) -> str:
        del prompt
        return json.dumps(
            {
                "stop": False,
                "reason": "continue under deterministic campaign limits",
                "hypothesis": "diversify the next batch while preserving gate-selected parents",
                "explore": True,
            },
            sort_keys=True,
        )


class OpenAIResponsesProvider:
    """OpenAI Responses API adapter with lazy SDK/client construction."""

    provider_name = "openai"

    def __init__(
        self,
        *,
        model: str,
        max_output_tokens: int = 256,
        client: Optional[Any] = None,
    ) -> None:
        if not model or not model.strip():
            raise ValueError("an explicit OpenAI model is required")
        self.model = model.strip()
        self.max_output_tokens = _validate_max_output_tokens(max_output_tokens)
        self._client = client

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                from openai import OpenAI
            except ImportError as exc:  # pragma: no cover - depends on optional SDK
                raise RuntimeError(
                    "OpenAI provider requires the 'llm-openai' optional dependency"
                ) from exc
            self._client = OpenAI(max_retries=0, timeout=60.0)
        return self._client

    def __call__(self, prompt: str) -> str:
        response = self._get_client().responses.create(
            model=self.model,
            input=prompt,
            max_output_tokens=self.max_output_tokens,
            store=False,
        )
        text = getattr(response, "output_text", None)
        if not isinstance(text, str) or not text.strip():
            raise RuntimeError("OpenAI response did not contain output_text")
        return text


class AnthropicMessagesProvider:
    """Anthropic Messages API adapter with lazy SDK/client construction."""

    provider_name = "anthropic"

    def __init__(
        self,
        *,
        model: str,
        max_output_tokens: int = 256,
        client: Optional[Any] = None,
    ) -> None:
        if not model or not model.strip():
            raise ValueError("an explicit Anthropic model is required")
        self.model = model.strip()
        self.max_output_tokens = _validate_max_output_tokens(max_output_tokens)
        self._client = client

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                from anthropic import Anthropic
            except ImportError as exc:  # pragma: no cover - depends on optional SDK
                raise RuntimeError(
                    "Anthropic provider requires the 'llm-anthropic' optional dependency"
                ) from exc
            self._client = Anthropic(max_retries=0, timeout=60.0)
        return self._client

    def __call__(self, prompt: str) -> str:
        response = self._get_client().messages.create(
            model=self.model,
            max_tokens=self.max_output_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        parts = [
            block.text
            for block in getattr(response, "content", [])
            if getattr(block, "type", None) == "text" and isinstance(getattr(block, "text", None), str)
        ]
        text = "".join(parts)
        if not text.strip():
            raise RuntimeError("Anthropic response did not contain a text block")
        return text


def get_orchestration_provider(
    name: str,
    *,
    model: Optional[str] = None,
    max_output_tokens: int = 256,
    credential_hygiene_attested: bool = False,
) -> Any:
    """Construct an orchestration provider without exposing credentials.

    Live providers require an explicit model and an out-of-band credential
    hygiene attestation. API keys are read only by the provider SDK.
    """

    normalized = name.strip().lower()
    max_output_tokens = _validate_max_output_tokens(max_output_tokens)
    if normalized in _FIXTURE_PROVIDERS:
        return FixtureOrchestrationProvider()
    if normalized not in _LIVE_PROVIDERS:
        choices = sorted(_FIXTURE_PROVIDERS | _LIVE_PROVIDERS)
        raise ValueError(f"unknown orchestration provider {name!r}; choose from {choices}")
    if not credential_hygiene_attested:
        raise RuntimeError(
            "live provider blocked: complete and attest P0 credential hygiene first"
        )
    if not model or not model.strip():
        raise ValueError("live provider requires an explicit model")
    if normalized in {"openai", "openai_responses"}:
        return OpenAIResponsesProvider(
            model=model,
            max_output_tokens=max_output_tokens,
        )
    return AnthropicMessagesProvider(
        model=model,
        max_output_tokens=max_output_tokens,
    )


def is_live_provider(name: Optional[str]) -> bool:
    """Return whether ``name`` selects a network-backed provider."""

    return bool(name and name.strip().lower() in _LIVE_PROVIDERS)
