"""Optional LLM providers for DBTL orchestration.

The provider boundary is deliberately small: ``prompt -> raw text``. Parsing,
authority, and audit logging stay in :mod:`loop.interpreter`, so a provider can
never call the trust gate or submit compute.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional


_LIVE_PROVIDERS = {"anthropic", "anthropic_messages", "openai", "openai_responses"}
_FIXTURE_PROVIDERS = {"fixture", "mock", "mock_defer", "mock_orchestrator"}


@dataclass(frozen=True)
class OrchestrationProviderResult:
    """Provider text plus optional transport metadata from the same call."""

    text: str
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    stop_reason: Optional[str] = None


def _validate_max_output_tokens(value: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 1024:
        raise ValueError("max_output_tokens must be an integer in [1, 1024]")
    return value


class FixtureOrchestrationProvider:
    """Dependency-free, deterministic provider used for contract tests."""

    provider_name = "fixture"
    model = "deterministic-hypothesis-orchestrator-v3"

    def call_with_metadata(self, prompt: str) -> OrchestrationProviderResult:
        del prompt
        return OrchestrationProviderResult(
            text=json.dumps(
                {
                    "reason": (
                        "The immutable controller decision leaves a bounded "
                        "evidence question."
                    ),
                    "hypothesis": (
                        "Compare one additional evidence slice while preserving "
                        "gate-selected parents and the frozen campaign limits."
                    ),
                },
                sort_keys=True,
            ),
            stop_reason="fixture_complete",
        )

    def __call__(self, prompt: str) -> str:
        return self.call_with_metadata(prompt).text


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

    def call_with_metadata(self, prompt: str) -> OrchestrationProviderResult:
        response = self._get_client().responses.create(
            model=self.model,
            input=prompt,
            max_output_tokens=self.max_output_tokens,
            store=False,
        )
        text = getattr(response, "output_text", None)
        if not isinstance(text, str) or not text.strip():
            raise RuntimeError("OpenAI response did not contain output_text")
        usage = getattr(response, "usage", None)
        incomplete = getattr(response, "incomplete_details", None)
        stop_reason = getattr(incomplete, "reason", None)
        if not isinstance(stop_reason, str) or not stop_reason.strip():
            status = getattr(response, "status", None)
            stop_reason = status if isinstance(status, str) and status.strip() else None
        return OrchestrationProviderResult(
            text=text,
            input_tokens=_optional_token_count(
                getattr(usage, "input_tokens", None)
            ),
            output_tokens=_optional_token_count(
                getattr(usage, "output_tokens", None)
            ),
            stop_reason=stop_reason,
        )

    def __call__(self, prompt: str) -> str:
        return self.call_with_metadata(prompt).text


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

    def call_with_metadata(self, prompt: str) -> OrchestrationProviderResult:
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
        usage = getattr(response, "usage", None)
        stop_reason = getattr(response, "stop_reason", None)
        return OrchestrationProviderResult(
            text=text,
            input_tokens=_optional_token_count(
                getattr(usage, "input_tokens", None)
            ),
            output_tokens=_optional_token_count(
                getattr(usage, "output_tokens", None)
            ),
            stop_reason=(
                stop_reason
                if isinstance(stop_reason, str) and stop_reason.strip()
                else None
            ),
        )

    def __call__(self, prompt: str) -> str:
        return self.call_with_metadata(prompt).text


def _optional_token_count(value: Any) -> Optional[int]:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


def call_provider_with_metadata(
    provider: Any,
    prompt: str,
) -> OrchestrationProviderResult:
    """Call a provider once and normalize optional transport metadata."""

    method = getattr(provider, "call_with_metadata", None)
    result = method(prompt) if callable(method) else provider(prompt)
    if isinstance(result, OrchestrationProviderResult):
        if not isinstance(result.text, str):
            raise TypeError("provider returned non-string response text")
        return result
    if not isinstance(result, str):
        raise TypeError("provider returned a non-string response")
    return OrchestrationProviderResult(text=result)


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
