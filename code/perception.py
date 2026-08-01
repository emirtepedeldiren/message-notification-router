"""Turns image and voice-note files into structured facts the router can read.

Media messages carry the decisive content: a poster's fine print, a voice
note's tone and deadline, a screenshot's payment link. The router is a text
model, so each media file is described once into a JSON record and cached by
file hash. The cache is committed, which keeps runs reproducible and lets the
pipeline finish without any API calls once the media has been seen.
"""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path

import config
from llm import GeminiClient

CACHE_PATH = config.CACHE_DIR / "media_facts.json"

# Bump when a prompt or schema changes so stale descriptions are re-derived.
PROMPT_VERSION = "v1"

IMAGE_PROMPT = """You are analysing an image attached to a WhatsApp message.

Transcribe and describe it factually. Do not judge whether the user should be
notified — another component decides that. Report only what the image shows.

Pay particular attention to:
- all readable text, including small print, URLs, phone numbers and amounts
- whether it asks the viewer to pay, share an OTP/PIN, or open a link
- which brand or organisation it claims to be from
- whether it is a photograph, a designed poster, or a screenshot of an app or chat
"""

AUDIO_PROMPT = """You are analysing a WhatsApp voice note.

Transcribe it and describe how it was said. Do not judge whether the user
should be notified — another component decides that. Report only what the
recording contains.

Pay particular attention to:
- a faithful transcript, translating to English if the speaker uses another language
- whether the speaker asks for money, credentials, or an OTP
- any deadline, time pressure, or explicit request directed at the listener
- whether it sounds like a personal message or a recorded marketing broadcast
"""

IMAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "One or two sentences on what the image shows."},
        "extracted_text": {"type": "string", "description": "All readable text, verbatim."},
        "kind": {"type": "string", "enum": ["photo", "poster", "screenshot", "document", "other"]},
        "claimed_brand": {"type": "string", "description": "Brand or organisation shown, else empty."},
        "urls": {"type": "array", "items": {"type": "string"}},
        "asks_for_payment": {"type": "boolean"},
        "asks_for_credentials": {"type": "boolean"},
        "is_promotional": {"type": "boolean"},
        "urgency_cues": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "summary",
        "extracted_text",
        "kind",
        "claimed_brand",
        "urls",
        "asks_for_payment",
        "asks_for_credentials",
        "is_promotional",
        "urgency_cues",
    ],
}

AUDIO_SCHEMA = {
    "type": "object",
    "properties": {
        "transcript": {"type": "string", "description": "Faithful transcript in English."},
        "language": {"type": "string"},
        "summary": {"type": "string"},
        "delivery": {"type": "string", "enum": ["personal", "broadcast", "automated", "unclear"]},
        "tone": {"type": "string", "description": "e.g. calm, worried, rushed, cheerful, salesy."},
        "asks_for_payment": {"type": "boolean"},
        "asks_for_credentials": {"type": "boolean"},
        "is_promotional": {"type": "boolean"},
        "has_deadline": {"type": "boolean"},
        "direct_request": {"type": "string", "description": "What the speaker asks the listener to do, else empty."},
        "urgency_cues": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "transcript",
        "language",
        "summary",
        "delivery",
        "tone",
        "asks_for_payment",
        "asks_for_credentials",
        "is_promotional",
        "has_deadline",
        "direct_request",
        "urgency_cues",
    ],
}

MIME_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".mp3": "audio/mp3",
    ".wav": "audio/wav",
    ".ogg": "audio/ogg",
    ".m4a": "audio/mp4",
}


@dataclass
class MediaFacts:
    """What a media file contains, as far as the perception model can tell."""

    media_id: str
    media_type: str
    summary: str = ""
    text: str = ""
    asks_for_payment: bool = False
    asks_for_credentials: bool = False
    is_promotional: bool = False
    urgency_cues: list[str] = field(default_factory=list)
    urls: list[str] = field(default_factory=list)
    claimed_brand: str = ""
    kind: str = ""
    tone: str = ""
    delivery: str = ""
    has_deadline: bool = False
    direct_request: str = ""
    available: bool = True

    @property
    def query_text(self) -> str:
        """Text used to match this message against the user's history."""
        return " ".join(p for p in (self.text, self.summary, self.direct_request) if p).strip()

    def render(self) -> str:
        """Compact block describing the media inside the router prompt."""
        if not self.available:
            return f"[{self.media_type} attachment {self.media_id}: could not be analysed]"
        lines = [f"Attached {self.media_type} ({self.media_id}):", f"  Summary: {self.summary}"]
        if self.kind:
            lines.append(f"  Kind: {self.kind}")
        if self.delivery:
            lines.append(f"  Delivery: {self.delivery} (tone: {self.tone})")
        if self.text:
            body = " ".join(self.text.split())
            lines.append(f"  Text content: \"{body[:900]}\"")
        if self.claimed_brand:
            lines.append(f"  Claims to be from: {self.claimed_brand}")
        if self.urls:
            lines.append(f"  Links shown: {', '.join(self.urls[:5])}")
        if self.direct_request:
            lines.append(f"  Asks the listener to: {self.direct_request}")
        flags = [
            name
            for name, on in (
                ("requests payment", self.asks_for_payment),
                ("requests credentials or OTP", self.asks_for_credentials),
                ("promotional", self.is_promotional),
                ("states a deadline", self.has_deadline),
            )
            if on
        ]
        if flags:
            lines.append(f"  Flags: {', '.join(flags)}")
        if self.urgency_cues:
            lines.append(f"  Urgency cues: {', '.join(self.urgency_cues[:5])}")
        return "\n".join(lines)


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


class MediaPerceiver:
    """Describes media files, memoised on disk by content hash."""

    def __init__(self, client: GeminiClient | None = None, cache_path: Path = CACHE_PATH):
        self._client = client
        self._cache_path = cache_path
        self._lock = threading.Lock()
        self._cache: dict[str, dict] = {}
        if cache_path.exists():
            self._cache = json.loads(cache_path.read_text(encoding="utf-8"))

    @property
    def client(self) -> GeminiClient:
        if self._client is None:
            self._client = GeminiClient()
        return self._client

    def _cache_key(self, media_id: str, path: Path) -> str:
        return f"{PROMPT_VERSION}:{media_id}:{_digest(path)}"

    def save(self) -> None:
        with self._lock:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            self._cache_path.write_text(
                json.dumps(self._cache, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

    def perceive(self, media_id: str, media_type: str, path: Path | None) -> MediaFacts:
        """Return facts for one media file, calling the model only on a miss."""
        if path is None or not path.exists():
            return MediaFacts(media_id=media_id, media_type=media_type, available=False)

        key = self._cache_key(media_id, path)
        with self._lock:
            cached = self._cache.get(key)
        if cached is not None:
            return MediaFacts(**cached)

        # Without a key the pipeline still runs; media messages simply route on
        # their caption, sender and history alone.
        if not config.has_api_key():
            return MediaFacts(media_id=media_id, media_type=media_type, available=False)

        facts = self._describe(media_id, media_type, path)
        with self._lock:
            self._cache[key] = asdict(facts)
        return facts

    def _describe(self, media_id: str, media_type: str, path: Path) -> MediaFacts:
        mime = MIME_TYPES.get(path.suffix.lower())
        if mime is None:
            return MediaFacts(media_id=media_id, media_type=media_type, available=False)

        is_image = media_type == "image"
        raw = self.client.generate_json(
            model=config.PERCEPTION_MODEL,
            prompt=IMAGE_PROMPT if is_image else AUDIO_PROMPT,
            schema=IMAGE_SCHEMA if is_image else AUDIO_SCHEMA,
            media=(path.read_bytes(), mime),
        )
        if raw is None:
            return MediaFacts(media_id=media_id, media_type=media_type, available=False)

        if is_image:
            return MediaFacts(
                media_id=media_id,
                media_type=media_type,
                summary=raw.get("summary", ""),
                text=raw.get("extracted_text", ""),
                kind=raw.get("kind", ""),
                claimed_brand=raw.get("claimed_brand", ""),
                urls=list(raw.get("urls") or []),
                asks_for_payment=bool(raw.get("asks_for_payment")),
                asks_for_credentials=bool(raw.get("asks_for_credentials")),
                is_promotional=bool(raw.get("is_promotional")),
                urgency_cues=list(raw.get("urgency_cues") or []),
            )
        return MediaFacts(
            media_id=media_id,
            media_type=media_type,
            summary=raw.get("summary", ""),
            text=raw.get("transcript", ""),
            delivery=raw.get("delivery", ""),
            tone=raw.get("tone", ""),
            asks_for_payment=bool(raw.get("asks_for_payment")),
            asks_for_credentials=bool(raw.get("asks_for_credentials")),
            is_promotional=bool(raw.get("is_promotional")),
            has_deadline=bool(raw.get("has_deadline")),
            direct_request=raw.get("direct_request", ""),
            urgency_cues=list(raw.get("urgency_cues") or []),
        )
