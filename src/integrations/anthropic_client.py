"""Async wrapper around the Anthropic SDK.

One class — ``AnthropicClient`` — owns:
- prompt loading from ``src/prompts/*.md``
- model selection (Haiku for classification, Sonnet for extraction)
- robust JSON-mode parsing for Claude responses
- structured logging of latency and token usage

Why a wrapper, not raw SDK calls? Two reasons:
1. The orchestrator should not care which model handled a step.
2. Prompts are version-controlled markdown, not string literals.
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from anthropic import AsyncAnthropic
from anthropic.types import Message

from ..config import Settings, get_settings
from ..utils.logging import get_logger

log = get_logger(__name__)

PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"


class AnthropicError(RuntimeError):
    """Raised when Claude returns an error or unparseable output."""


class AnthropicClient:
    """Thin async wrapper around the Anthropic SDK.

    Holds prompt strings in memory after first read so subsequent calls don't
    pay disk I/O. Stateless beyond that.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._client = AsyncAnthropic(api_key=self.settings.anthropic_api_key.get_secret_value())
        self._prompt_cache: dict[str, str] = {}

    # --- Public API --------------------------------------------------------

    async def hello(self) -> str:
        """Smoke-test method — returns Claude's greeting. Used by setup checks."""
        msg = await self._client.messages.create(
            model=self.settings.classifier_model,
            max_tokens=64,
            messages=[{"role": "user", "content": "Say 'hello from PA-Agent' and nothing else."}],
        )
        return _extract_text(msg).strip()

    async def classify(self, voice_text: str) -> dict[str, Any]:
        """Run the intent classifier (Haiku). Returns parsed JSON dict.

        Args:
            voice_text: Raw transcribed user speech.

        Returns:
            Dict with keys ``intent``, ``confidence``, ``reasoning``.

        Raises:
            AnthropicError: If Claude returns non-JSON or the call fails.
        """
        system_prompt = self._load_prompt("classifier.md")
        return await self._call_json(
            model=self.settings.classifier_model,
            system_prompt=system_prompt,
            user_message=voice_text,
            max_tokens=256,
            label="classify",
        )

    async def extract(
        self, voice_text: str, intent: str, *, now: datetime | None = None
    ) -> dict[str, Any]:
        """Run the field extractor (Sonnet) for a given intent.

        Args:
            voice_text: Raw transcribed user speech.
            intent: One of the values returned by ``classify``.
            now: Override "current time" for testing; defaults to local now.

        Returns:
            Intent-specific structured fields. Schema lives in ``extractor.md``.
        """
        from .._tz import LOCAL_TZ as _LOCAL_TZ
        system_prompt = self._load_prompt("extractor.md")
        current = now or datetime.now(_LOCAL_TZ)
        user_message = (
            f"Today: {current.strftime('%Y-%m-%d %A')}\n"
            f"Current time: {current.strftime('%H:%M %Z')}\n"
            f"Intent: {intent}\n"
            f"Voice text: {voice_text}\n"
            f"Return strict JSON for this intent's schema only."
        )
        return await self._call_json(
            model=self.settings.extractor_model,
            system_prompt=system_prompt,
            user_message=user_message,
            max_tokens=1024,
            label="extract",
        )

    async def nudge(self, context_json: str) -> str:
        """Generate the PWA's daily "Claude's take" one-liner.

        Args:
            context_json: A JSON-serialized snapshot of the user's current
                state (urgent counts, bills due, wins today, etc.). The
                prompt teaches Claude to read this and respond with one
                short, action-oriented sentence.

        Returns:
            The nudge text — typically 1-2 sentences, no quotes, no preamble.
        """
        system_prompt = (
            "You are a calm, practical personal assistant. Given a snapshot "
            "of the user's day, write ONE short observation (1-2 sentences, "
            "max 35 words) that names what's actually pressing and suggests "
            "where to start. Be specific. No generic motivational language. "
            "No quotes, no preamble, no 'Here's your nudge'. Just the line."
        )
        try:
            msg = await self._client.messages.create(
                model=self.settings.classifier_model,  # cheap Haiku is fine
                max_tokens=120,
                system=system_prompt,
                messages=[{"role": "user", "content": context_json}],
            )
        except Exception as e:
            log.error("anthropic.nudge_failed", error=str(e))
            raise AnthropicError(f"Anthropic nudge call failed: {e}") from e
        text = _extract_text(msg).strip().strip('"').strip("'")
        log.info(
            "anthropic.nudge_ok",
            input_tokens=msg.usage.input_tokens,
            output_tokens=msg.usage.output_tokens,
            chars=len(text),
        )
        return text

    # --- Internals ---------------------------------------------------------

    def _load_prompt(self, filename: str) -> str:
        if filename not in self._prompt_cache:
            path = PROMPTS_DIR / filename
            self._prompt_cache[filename] = path.read_text(encoding="utf-8")
        return self._prompt_cache[filename]

    async def _call_json(
        self,
        *,
        model: str,
        system_prompt: str,
        user_message: str,
        max_tokens: int,
        label: str,
    ) -> dict[str, Any]:
        start = time.perf_counter()
        try:
            msg = await self._client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
            )
        except Exception as e:  # network, auth, rate-limit
            log.error("anthropic.call_failed", label=label, model=model, error=str(e))
            raise AnthropicError(f"Anthropic {label} call failed: {e}") from e

        latency_ms = int((time.perf_counter() - start) * 1000)
        text = _extract_text(msg)
        log.info(
            "anthropic.call_ok",
            label=label,
            model=model,
            latency_ms=latency_ms,
            input_tokens=msg.usage.input_tokens,
            output_tokens=msg.usage.output_tokens,
        )
        return _parse_json_strict(text, label=label)


def _extract_text(msg: Message) -> str:
    """Concatenate the text blocks from a Claude response."""
    parts = [block.text for block in msg.content if getattr(block, "type", None) == "text"]
    return "".join(parts)


def _parse_json_strict(text: str, *, label: str) -> dict[str, Any]:
    """Parse JSON, tolerating ```json fences if Claude wraps the response.

    Defensive: even though prompts say "return strict JSON, no prose", an
    occasional model will hedge with markdown fences. We strip those, then
    fail loudly if the result still isn't a JSON object.
    """
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
        cleaned = cleaned.strip()
    try:
        result = json.loads(cleaned)
    except json.JSONDecodeError as e:
        log.error("anthropic.json_parse_failed", label=label, raw=text[:500])
        raise AnthropicError(f"Anthropic {label} returned non-JSON: {e}") from e
    if not isinstance(result, dict):
        raise AnthropicError(f"Anthropic {label} returned non-object JSON: {type(result).__name__}")
    return result
