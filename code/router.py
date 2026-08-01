"""The routing decision: builds the prompt, calls the model, parses the result.

Few-shot examples and the reason catalogue are both derived from
`sample_messages.csv` at run time. That file is supplied precisely to convey
the expected output format and style, and reading it keeps the house voice
consistent without any decision being hard-coded.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import config
from data_loader import ACTIONS, MESSAGE_TYPES, Dataset, Message
from context import MessageContext
from llm import GeminiClient, QuotaExhausted
from retrieval import normalise
from rapidfuzz import fuzz
from risk import RiskVerdict

SYSTEM_PROMPT = (config.PROMPT_DIR / "router.md").read_text(encoding="utf-8")

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "key_signals": {
            "type": "array",
            "items": {"type": "string"},
            "description": "The two or three facts that decided this, most important first.",
        },
        "message_type": {"type": "string", "enum": list(MESSAGE_TYPES)},
        "action": {"type": "string", "enum": list(ACTIONS)},
        "reason": {"type": "string", "description": "One sentence explaining the decision for this user."},
        "confidence": {"type": "number"},
        "evidence_message_ids": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Ids taken from the candidate history; empty if none apply.",
        },
    },
    "required": ["key_signals", "message_type", "action", "reason", "confidence", "evidence_message_ids"],
}


@dataclass
class Decision:
    """A routing decision before post-processing guardrails run."""

    action: str
    message_type: str
    reason: str
    confidence: float
    evidence_message_ids: list[str] = field(default_factory=list)
    key_signals: list[str] = field(default_factory=list)
    source: str = "model"


def build_reason_catalogue(dataset: Dataset, exclude_id: str = "") -> dict[str, list[str]]:
    """Group the sample reasons by action so the prompt can offer the right ones.

    `exclude_id` drops the row being routed. It matters only while evaluating,
    where a message drawn from the sample pool would otherwise be offered its
    own gold reason back as a suggestion.
    """
    catalogue: dict[str, list[str]] = {action: [] for action in ACTIONS}
    for sample in dataset.samples:
        if sample.message_id == exclude_id:
            continue
        if sample.action in catalogue and sample.reason:
            if sample.reason not in catalogue[sample.action]:
                catalogue[sample.action].append(sample.reason)
    return catalogue


def render_catalogue(catalogue: dict[str, list[str]]) -> str:
    lines = ["# Reason catalogue (reuse verbatim when one fits)"]
    for action in ACTIONS:
        entries = catalogue.get(action) or []
        if not entries:
            continue
        lines.append(f"\nWhen the action is `{action}`:")
        lines += [f'- "{entry}"' for entry in entries]
    return "\n".join(lines)


def select_examples(dataset: Dataset, message: Message, limit: int = 4) -> list[Message]:
    """Pick the labelled samples closest to this message.

    Matching the conversation and media shape first means a voice note is
    shown voice-note examples, which is what keeps the style consistent
    across very different message kinds.

    The message being routed is excluded. It only ever appears in the sample
    pool while evaluating, and showing the model its own answer would make
    every dev-set score meaningless.
    """
    query = normalise(message.message_text)
    scored: list[tuple[float, str, Message]] = []
    for sample in dataset.samples:
        if sample.message_id == message.message_id:
            continue
        score = 0.0
        if sample.conversation_type == message.conversation_type:
            score += 0.4
        if sample.media_type == message.media_type:
            score += 0.3
        if query and sample.message_text:
            score += 0.3 * (fuzz.token_set_ratio(query, normalise(sample.message_text)) / 100.0)
        scored.append((score, sample.message_id, sample))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [sample for _, _, sample in scored[:limit]]


def render_examples(examples: list[Message]) -> str:
    """Show worked examples as compact input/output pairs."""
    blocks = ["# Worked examples from this system"]
    for sample in examples:
        body = " ".join((sample.message_text or f"[{sample.media_type} attachment]").split())
        if len(body) > 240:
            body = body[:237] + "..."
        payload = {
            "action": sample.action,
            "message_type": sample.message_type,
            "reason": sample.reason,
            "confidence": sample.confidence,
        }
        blocks.append(
            f"\n{sample.conversation_type} message"
            + (f" with {sample.media_type}" if sample.media_type else "")
            + f': "{body}"\n-> {json.dumps(payload)}'
        )
    return "\n".join(blocks)


class Router:
    """Routes messages, holding the shared client and prompt fragments."""

    def __init__(self, dataset: Dataset, client: GeminiClient | None = None, model: str | None = None):
        self.dataset = dataset
        self._client = client
        self.model = model or config.ROUTER_MODEL
        # An explicitly requested model is honoured alone, so model comparison
        # in the evaluation measures that model rather than a silent chain.
        self._spare_models = [] if model else [m for m in config.ROUTER_FALLBACK_MODELS if m != self.model]
        self._catalogues: dict[str, str] = {}

    def catalogue_for(self, exclude_id: str = "") -> str:
        if exclude_id not in self._catalogues:
            self._catalogues[exclude_id] = render_catalogue(
                build_reason_catalogue(self.dataset, exclude_id)
            )
        return self._catalogues[exclude_id]

    @property
    def client(self) -> GeminiClient:
        if self._client is None:
            self._client = GeminiClient()
        return self._client

    def build_prompt(self, ctx: MessageContext, verdict: RiskVerdict) -> str:
        candidates = [item.message_id for item in ctx.evidence] or ["none available"]
        sections = [
            self.catalogue_for(ctx.message.message_id),
            render_examples(select_examples(self.dataset, ctx.message)),
            "# Safety layer verdict",
            verdict.render()
            + (
                "\n\nThis verdict is binding: the action must be `mute`."
                if verdict.forces_mute
                else "\n\nThis is advisory. Weigh it against the rest of the context."
            ),
            "# Context card",
            ctx.render(),
            "# Your task",
            f"Route message {ctx.message.message_id}. "
            f"Choose evidence ids only from: {', '.join(candidates)}. "
            "Respond with the JSON object described by the schema.",
        ]
        return "\n\n".join(sections)

    def route(self, ctx: MessageContext, verdict: RiskVerdict, temperature: float | None = None) -> Decision | None:
        """Ask the model to route one message. Returns None if the call failed.

        Raises `QuotaExhausted` only once every configured model is spent; until
        then it moves to the next one and keeps going.
        """
        prompt = f"{SYSTEM_PROMPT}\n\n{self.build_prompt(ctx, verdict)}"

        raw = None
        while raw is None:
            try:
                raw = self.client.generate_json(
                    model=self.model, prompt=prompt, schema=RESPONSE_SCHEMA, temperature=temperature
                )
                break
            except QuotaExhausted:
                if not self._spare_models:
                    raise
                self.model = self._spare_models.pop(0)
                print(f"  ! switching router model to {self.model}", flush=True)

        if raw is None:
            return None

        try:
            confidence = float(raw.get("confidence", 0.8))
        except (TypeError, ValueError):
            confidence = 0.8

        return Decision(
            action=str(raw.get("action", "")).strip().lower(),
            message_type=str(raw.get("message_type", "")).strip().lower(),
            reason=str(raw.get("reason", "")).strip(),
            confidence=confidence,
            evidence_message_ids=[str(x).strip() for x in (raw.get("evidence_message_ids") or []) if str(x).strip()],
            key_signals=[str(x).strip() for x in (raw.get("key_signals") or []) if str(x).strip()],
        )
