"""Provider contract.

Every LLM provider (gemini / openrouter / stub / anthropic) implements this
single uniform interface. `LLMClient` is the only caller; no graph node ever
touches a provider SDK directly.
"""
from __future__ import annotations

from typing import NamedTuple, Protocol, runtime_checkable


class LLMResponse(NamedTuple):
    """A model reply plus REAL provider token usage.

    `tokens_input` / `tokens_output` are the provider's actual counts when it
    reports them (Gemini `usage_metadata`, Anthropic `usage`, OpenRouter
    `usage`), else `0` — callers fall back to a `chars/4` estimate only when a
    provider reports nothing.

    `tokens_cached` (C39) is how many of `tokens_input` were served from the
    provider's prompt cache (a SUBSET counted at full value in `tokens_input`,
    never additional tokens). Gemini reads `usage_metadata.
    cached_content_token_count`; anthropic/openrouter/stub make no
    cache-control calls, so the default `0` is honest for them — and unlike
    `tokens_input` there is NO estimation fallback: unreported cached is `0`.
    """

    text: str
    tokens_input: int = 0
    tokens_output: int = 0
    tokens_cached: int = 0


@runtime_checkable
class LLMProvider(Protocol):
    """Uniform completion interface shared by all providers.

    A provider takes a fully-assembled prompt and an optional system
    instruction and returns the model's reply. `complete` carries the real
    token usage; `call_model` is the text-only convenience wrapper over it.
    Implementations read their own `api_key` / `model` in their constructor;
    the stub takes neither.
    """

    def complete(self, prompt: str, *, system: str | None = None) -> "LLMResponse":
        """Return the model's reply + real token usage for `prompt`."""
        ...

    def call_model(self, prompt: str, *, system: str | None = None) -> str:
        """Return just the model's text reply (convenience over `complete`)."""
        ...
