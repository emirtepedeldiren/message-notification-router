"""Finds the historical messages that justify a routing decision.

The dataset's own labelled examples show that the evidence for a decision is
the user's most similar past message, and that the *outcome* of that past
message (opened / dismissed / muted) is what makes two users receiving the
same text get different actions. So retrieval feeds both the
`evidence_message_ids` column and the personalisation signal in the prompt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from rapidfuzz import fuzz

from data_loader import Dataset, Event, Message

# Scoring weights. Channel match dominates because "the same business kept
# messaging me" is a stronger evidence link than loose wording overlap.
W_SAME_BUSINESS = 0.40
W_SAME_GROUP = 0.22
W_SAME_SENDER = 0.30
W_TEXT = 0.55
W_RECENCY = 0.12
W_MEDIA_MATCH = 0.06
W_MENTION_MATCH = 0.10

MIN_SCORE = 0.18
_TOKEN_RE = re.compile(r"[a-z0-9]+")


def mentions_user(text: str, user_id: str) -> bool:
    """Whether `text` directly @-mentions this user."""
    return bool(user_id) and f"@{user_id}" in (text or "")


def normalise(text: str) -> str:
    """Lowercase and strip punctuation so wording differences don't dominate."""
    return " ".join(_TOKEN_RE.findall(text.lower()))


@dataclass
class Evidence:
    """A retrieved historical message plus how the user reacted to it."""

    message: Message
    event: Event | None
    score: float
    channel_match: str

    @property
    def message_id(self) -> str:
        return self.message.message_id

    def describe(self) -> str:
        """One line for the prompt: what it was and what the user did."""
        when = self.message.created_at.strftime("%Y-%m-%d") if self.message.created_at else "unknown date"
        body = self.message.message_text or f"[{self.message.media_type} message]"
        body = " ".join(body.split())
        if len(body) > 180:
            body = body[:177] + "..."
        outcome = self.event.describe() if self.event else "no recorded reaction"
        return f"{self.message_id} ({when}, {self.channel_match}): \"{body}\" -> user {outcome}"


def _recency_score(candidate: datetime | None, reference: datetime | None) -> float:
    """1.0 for same-day, decaying to 0 over roughly three months."""
    if candidate is None or reference is None:
        return 0.0
    days = abs((reference - candidate).days)
    return max(0.0, 1.0 - days / 90.0)


def _channel_score(message: Message, candidate: Message) -> tuple[float, str]:
    if message.business_id and candidate.business_id == message.business_id:
        return W_SAME_BUSINESS, "same business"
    if message.sender_user_id and candidate.sender_user_id == message.sender_user_id:
        # Same person, whether or not it was the same group.
        if message.group_id and candidate.group_id == message.group_id:
            return W_SAME_SENDER + W_SAME_GROUP, "same sender in this group"
        return W_SAME_SENDER, "same sender"
    if message.group_id and candidate.group_id == message.group_id:
        return W_SAME_GROUP, "same group"
    return 0.0, "other conversation"


def retrieve(
    dataset: Dataset,
    message: Message,
    query_text: str | None = None,
    limit: int = 4,
) -> list[Evidence]:
    """Rank the user's history against this message, best evidence first.

    `query_text` lets callers substitute a richer query — a voice-note
    transcript or an image's extracted text — for media messages whose own
    `message_text` is empty.
    """
    history = dataset.history_by_user.get(message.user_id, [])
    if not history:
        return []

    query = normalise(query_text if query_text is not None else message.message_text)
    scored: list[Evidence] = []

    for candidate in history:
        if candidate.message_id == message.message_id:
            continue

        channel, label = _channel_score(message, candidate)
        text_score = 0.0
        if query:
            candidate_text = normalise(candidate.message_text)
            if candidate_text:
                text_score = W_TEXT * (fuzz.token_set_ratio(query, candidate_text) / 100.0) ** 2

        recency = W_RECENCY * _recency_score(candidate.created_at, message.created_at)
        media_bonus = W_MEDIA_MATCH if candidate.media_type == message.media_type and message.media_type else 0.0
        # A past message that also addressed this user directly is a closer
        # analogue than a broadcast to the whole group.
        mention_bonus = (
            W_MENTION_MATCH
            if mentions_user(message.message_text, message.user_id)
            and mentions_user(candidate.message_text, message.user_id)
            else 0.0
        )

        total = channel + text_score + recency + media_bonus + mention_bonus
        if total < MIN_SCORE:
            continue
        scored.append(
            Evidence(
                message=candidate,
                event=dataset.event_for(message.user_id, candidate.message_id),
                score=total,
                channel_match=label,
            )
        )

    scored.sort(key=lambda e: (-e.score, e.message.message_id))
    return scored[:limit]


def engagement_summary(evidence: list[Evidence]) -> dict[str, int]:
    """Aggregate how the user treated the retrieved messages."""
    summary = {"total": 0, "positive": 0, "negative": 0, "reported": 0, "muted": 0}
    for item in evidence:
        if item.event is None:
            continue
        summary["total"] += 1
        if item.event.is_positive:
            summary["positive"] += 1
        if item.event.is_negative:
            summary["negative"] += 1
        if item.event.reported:
            summary["reported"] += 1
        if item.event.muted_after:
            summary["muted"] += 1
    return summary


def format_evidence_ids(evidence: list[Evidence], keep: int = 1) -> str:
    """Render the `evidence_message_ids` column.

    The labelled examples carry a single id in 25 of 30 rows, so precision
    beats recall here: a close runner-up is only added when it is genuinely
    comparable to the top hit.
    """
    if not evidence:
        return "none"
    chosen = [evidence[0]]
    if keep > 1 and len(evidence) > 1 and evidence[1].score >= 0.92 * evidence[0].score:
        chosen.append(evidence[1])
    return ";".join(item.message_id for item in chosen[:keep])
