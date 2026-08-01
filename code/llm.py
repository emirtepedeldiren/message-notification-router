"""Thin wrapper around the Gemini API: JSON-schema calls, rate limits, retries.

Kept deliberately small so the routing logic never touches SDK details, and so
evaluation can swap in a different model by name alone.
"""

from __future__ import annotations

import json
import random
import threading
import time

import config


class RateLimiter:
    """Spaces requests out to stay under a requests-per-minute ceiling."""

    def __init__(self, per_minute: int):
        self._interval = 60.0 / max(per_minute, 1)
        self._lock = threading.Lock()
        self._next_slot = 0.0

    def acquire(self) -> None:
        with self._lock:
            now = time.monotonic()
            wait = max(0.0, self._next_slot - now)
            self._next_slot = max(now, self._next_slot) + self._interval
        if wait:
            time.sleep(wait)


class GeminiClient:
    """Generates schema-constrained JSON, retrying on transient failures."""

    def __init__(self, api_key: str | None = None, per_minute: int | None = None):
        from google import genai  # imported lazily so --help works without the SDK

        self._genai = genai
        self._client = genai.Client(api_key=api_key or config.require_api_key())
        self._limiter = RateLimiter(per_minute or config.REQUESTS_PER_MINUTE)
        self.calls = 0
        self._lock = threading.Lock()

    def generate_json(
        self,
        model: str,
        prompt: str,
        schema: dict,
        media: tuple[bytes, str] | None = None,
        temperature: float | None = None,
    ) -> dict | None:
        """Return the parsed JSON response, or None if every attempt failed."""
        from google.genai import types

        parts: list = []
        if media is not None:
            payload, mime = media
            parts.append(types.Part.from_bytes(data=payload, mime_type=mime))
        parts.append(prompt)

        cfg = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=schema,
            temperature=config.TEMPERATURE if temperature is None else temperature,
        )

        last_error: Exception | None = None
        for attempt in range(config.MAX_RETRIES):
            self._limiter.acquire()
            try:
                response = self._client.models.generate_content(
                    model=model, contents=parts, config=cfg
                )
                with self._lock:
                    self.calls += 1
                text = (response.text or "").strip()
                if not text:
                    raise ValueError("empty response")
                return json.loads(text)
            except Exception as exc:  # noqa: BLE001 - retry on anything transient
                last_error = exc
                if attempt == config.MAX_RETRIES - 1:
                    break
                # Exponential backoff with jitter; quota errors need the longest wait.
                delay = (2**attempt) + random.uniform(0, 1)
                if "RESOURCE_EXHAUSTED" in str(exc) or "429" in str(exc):
                    delay = max(delay, 20.0)
                time.sleep(delay)

        print(f"  ! model call failed after {config.MAX_RETRIES} attempts: {last_error}")
        return None
