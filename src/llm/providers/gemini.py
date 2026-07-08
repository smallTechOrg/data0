import re
import time

from google import genai
from google.genai import types

from llm.providers.base import LLMResponse
from observability.events import get_logger

logger = get_logger("llm.gemini")

# Adaptive 429 retry — engages ONLY when the API actually returns a 429/
# RESOURCE_EXHAUSTED (free-tier rate limit). Zero added latency otherwise.
_MAX_RETRIES = 3  # 4 attempts total
_TOTAL_WAIT_CEILING_S = 90.0  # beyond this, retrying is pointless (daily quota)
_FALLBACK_DELAYS_S = (2.0, 8.0, 30.0)  # per attempt, when the server gives no hint
_DELAY_BUFFER_S = 0.5  # padding on top of the server's suggested delay

# Google's 429 body carries the suggested delay both as prose
# ("... Please retry in 1.984709948s.") and as structured RetryInfo detail
# ("'retryDelay': '1s'"). Take whichever parses.
_RETRY_IN_RE = re.compile(r"[Pp]lease retry in ([0-9.]+)s")
_RETRY_DELAY_RE = re.compile(r"['\"]retryDelay['\"]:\s*['\"]([0-9.]+)s['\"]")


def _is_rate_limit_error(exc: Exception) -> bool:
    """True only for 429/RESOURCE_EXHAUSTED. Prefer the SDK's structured
    ``code`` attribute (google.genai.errors.APIError); fall back to text."""
    code = getattr(exc, "code", None)
    if isinstance(code, int):
        return code == 429
    text = str(exc)
    return "429" in text or "RESOURCE_EXHAUSTED" in text


def _parse_retry_delay_s(exc: Exception) -> float | None:
    """Server-suggested retry delay in seconds, or None if unparsable."""
    text = str(exc)
    match = _RETRY_IN_RE.search(text) or _RETRY_DELAY_RE.search(text)
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


class GeminiProvider:
    DEFAULT_MODEL = "gemini-3.1-flash-lite"

    def __init__(self, api_key: str, model: str) -> None:
        self._client = genai.Client(api_key=api_key)
        self._model = model or self.DEFAULT_MODEL

    def _generate_with_retry(
        self, prompt: str, config: "types.GenerateContentConfig | None"
    ):
        """Call generate_content, retrying ONLY on 429/RESOURCE_EXHAUSTED.

        Honors the server's suggested retryDelay (+ a small buffer), falling
        back to exponential delays when unparsable. Caps at _MAX_RETRIES and
        a total accumulated wait of _TOTAL_WAIT_CEILING_S — if the next sleep
        would blow past the ceiling (e.g. daily-quota exhaustion), the original
        error re-raises immediately so a dead key fails fast with the real
        message. Any non-429 error re-raises immediately, unchanged.
        """
        total_wait_s = 0.0
        for attempt in range(_MAX_RETRIES + 1):
            try:
                return self._client.models.generate_content(
                    model=self._model,
                    contents=prompt,
                    config=config,
                )
            except Exception as exc:
                if not _is_rate_limit_error(exc):
                    raise
                if attempt >= _MAX_RETRIES:
                    raise
                suggested_s = _parse_retry_delay_s(exc)
                if suggested_s is not None:
                    delay_s = suggested_s + _DELAY_BUFFER_S
                else:
                    delay_s = _FALLBACK_DELAYS_S[attempt]
                if total_wait_s + delay_s > _TOTAL_WAIT_CEILING_S:
                    raise
                logger.warning(
                    "gemini_429_retry",
                    attempt=attempt + 1,
                    delay_s=round(delay_s, 2),
                )
                time.sleep(delay_s)
                total_wait_s += delay_s
        raise RuntimeError("unreachable: retry loop exited without return/raise")

    def complete(self, prompt: str, *, system: str | None = None) -> LLMResponse:
        config = types.GenerateContentConfig(
            system_instruction=system,
        ) if system else None
        response = self._generate_with_retry(prompt, config)
        # Real usage from Gemini's usage_metadata (prompt_token_count =
        # input, candidates_token_count = output). Absent -> 0 (caller estimates).
        # cached_content_token_count (C39) is how many of prompt_token_count were
        # served from the implicit prompt cache — absent/None on a cold call -> 0.
        usage = getattr(response, "usage_metadata", None)
        tokens_input = int(getattr(usage, "prompt_token_count", 0) or 0)
        tokens_output = int(getattr(usage, "candidates_token_count", 0) or 0)
        tokens_cached = int(getattr(usage, "cached_content_token_count", 0) or 0)
        return LLMResponse(
            response.text or "", tokens_input, tokens_output, tokens_cached
        )

    def call_model(self, prompt: str, *, system: str | None = None) -> str:
        return self.complete(prompt, system=system).text
