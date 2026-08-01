"""Guardrails applied after the model has spoken.

Three jobs: enforce the safety verdict, keep decisions internally coherent,
and make sure every field is something the output schema accepts. Each
adjustment is recorded so the evaluation can show what the rules changed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import config
from context import MessageContext
from data_loader import ACTIONS, MESSAGE_TYPES
from retrieval import format_evidence_ids
from risk import RiskVerdict
from router import Decision

# Types that describe unwanted or hostile content: these are never delivered.
SUPPRESSED_TYPES = {"scam", "spam"}

# A chain forward is by nature not worth an interruption.
NEVER_NOTIFY_TYPES = {"scam", "spam", "forward"}


@dataclass
class Adjustment:
    rule: str
    detail: str


@dataclass
class Routed:
    """A finished decision plus the trail of guardrails that shaped it."""

    message_id: str
    action: str
    message_type: str
    reason: str
    confidence: float
    evidence_message_ids: str
    adjustments: list[Adjustment] = field(default_factory=list)
    key_signals: list[str] = field(default_factory=list)
    source: str = "model"


def _fallback_decision(ctx: MessageContext, verdict: RiskVerdict) -> Decision:
    """Rule-only decision, used when the model is unavailable or unparsable.

    Also serves as the rules-only baseline in the evaluation ablations.
    """
    sig = ctx.text_signals
    if verdict.forces_mute:
        return Decision(
            action="mute",
            message_type=verdict.message_type or "scam",
            reason="The message shows scam or safety-risk patterns and is suppressed regardless of usual engagement.",
            confidence=0.88,
            source="rules",
        )

    negative = sum(1 for e in ctx.evidence if e.event and e.event.is_negative)
    positive = sum(1 for e in ctx.evidence if e.event and e.event.is_positive)

    if sig.promotional:
        opted_out = ctx.relationship.opted_out if ctx.relationship else False
        if opted_out or negative > positive:
            return Decision(
                action="mute",
                message_type="promotion",
                reason="The user has opted out of or repeatedly dismissed similar marketing messages.",
                confidence=0.80,
                source="rules",
            )
        return Decision(
            action="digest",
            message_type="promotion",
            reason="The offer is potentially relevant, but it does not need immediate attention.",
            confidence=0.78,
            source="rules",
        )

    if sig.greeting or ctx.message.forwarded_count >= 5:
        kind = "forward" if ctx.message.forwarded_count >= 5 else "greeting"
        action = "mute" if (ctx.group_muted or negative) else "digest"
        return Decision(
            action=action,
            message_type=kind,
            reason="The sender has a pattern of repeated forwards or greetings that the user usually ignores."
            if action == "mute"
            else "The message is a harmless greeting that can be read later.",
            confidence=0.79,
            source="rules",
        )

    if ctx.directly_mentioned:
        return Decision(
            action="notify",
            message_type="personal",
            reason="The sender directly asks this user for a response or action.",
            confidence=0.84,
            source="rules",
        )

    if ctx.business is not None:
        return Decision(
            action="digest",
            message_type="business_update",
            reason="A verified business is sending a legitimate but non-urgent update.",
            confidence=0.78,
            source="rules",
        )

    return Decision(
        action="digest",
        message_type="personal",
        reason="The sender is trusted, but the message has no urgent action or safety relevance.",
        confidence=0.78,
        source="rules",
    )


def _valid_evidence(ctx: MessageContext, ids: list[str]) -> list[str]:
    """Keep only ids that exist in this user's history and were offered."""
    offered = {item.message_id for item in ctx.evidence}
    seen: list[str] = []
    for raw in ids:
        mid = raw.strip()
        if mid and mid != "none" and mid in offered and mid not in seen:
            seen.append(mid)
    return seen[:2]


def finalise(
    ctx: MessageContext,
    verdict: RiskVerdict,
    decision: Decision | None,
    apply_quiet_hours: bool = True,
) -> Routed:
    """Apply every guardrail and produce the row that goes into output.csv."""
    adjustments: list[Adjustment] = []

    if decision is None:
        decision = _fallback_decision(ctx, verdict)
        adjustments.append(Adjustment("fallback", "model unavailable; used rule-based decision"))

    action = decision.action if decision.action in ACTIONS else ""
    message_type = decision.message_type if decision.message_type in MESSAGE_TYPES else ""
    if not action:
        action = _fallback_decision(ctx, verdict).action
        adjustments.append(Adjustment("schema", f"model returned an invalid action; used {action}"))
    if not message_type:
        message_type = "unknown"
        adjustments.append(Adjustment("schema", "model returned an invalid message_type; used unknown"))

    reason = decision.reason
    confidence = decision.confidence

    # 1. Safety verdict is binding.
    if verdict.forces_mute:
        if action != "mute":
            adjustments.append(Adjustment("safety", f"safety gate overrode {action} -> mute"))
            action = "mute"
        if message_type not in SUPPRESSED_TYPES:
            new_type = verdict.message_type or "scam"
            adjustments.append(Adjustment("safety", f"message_type {message_type} -> {new_type}"))
            message_type = new_type
        if not reason:
            reason = "The message shows scam patterns and is suppressed regardless of the user's usual engagement."

    # 2. Unwanted content is never delivered, whatever the model chose.
    if message_type in SUPPRESSED_TYPES and action != "mute":
        adjustments.append(Adjustment("coherence", f"{message_type} cannot be {action}; forced mute"))
        action = "mute"
    if message_type in NEVER_NOTIFY_TYPES and action == "notify":
        adjustments.append(Adjustment("coherence", f"{message_type} cannot notify; downgraded to digest"))
        action = "digest"

    # 3. Marketing never interrupts. Even a well-targeted offer is something
    # the user can read later, and every labelled promotion is digest or mute.
    if action == "notify" and message_type == "promotion":
        adjustments.append(Adjustment("coherence", "promotional content does not warrant an interruption"))
        action = "digest"

    # 4. A one-to-one conversation is not silenced on engagement history alone.
    # Muting a person the user actually talks to risks losing a direct question
    # — "can you collect it by 6, tell me honestly if you can't" — because
    # their earlier sale posts went unread. Risk findings still override this.
    if (
        action == "mute"
        and not verdict.forces_mute
        and ctx.message.conversation_type == "personal"
        and message_type not in SUPPRESSED_TYPES
        and message_type not in {"promotion", "forward", "greeting"}
    ):
        adjustments.append(Adjustment("one-to-one", "direct conversation held back rather than silenced"))
        action = "digest"

    # 5. A promotion from a business the user opted out of is unwanted by definition.
    if (
        action != "mute"
        and message_type == "promotion"
        and ctx.relationship is not None
        and ctx.relationship.opted_out
    ):
        adjustments.append(Adjustment("opt-out", "user opted out of promotions from this business"))
        action = "mute"

    # 6. A muted group only breaks through for a direct address or a real emergency.
    if action == "notify" and ctx.group_muted and not ctx.directly_mentioned and message_type != "urgent":
        adjustments.append(Adjustment("muted-group", "user muted this group and was not addressed directly"))
        action = "digest"

    # 7. Do-not-disturb hours.
    # No labelled example falls inside a DND window, so this stays deliberately
    # narrow: genuinely urgent, directly addressed, and personal messages still
    # interrupt. Ablated in the evaluation as `quiet_hours`.
    if (
        apply_quiet_hours
        and action == "notify"
        and ctx.in_quiet_hours
        and message_type not in {"urgent", "payment"}
        and not ctx.directly_mentioned
        and ctx.message.conversation_type != "personal"
    ):
        adjustments.append(Adjustment("quiet-hours", "arrives inside the user's do-not-disturb window"))
        action = "digest"

    # 8. Evidence must point at real history this user actually has.
    evidence_ids = _valid_evidence(ctx, decision.evidence_message_ids)
    if not evidence_ids and ctx.evidence:
        fallback = format_evidence_ids(ctx.evidence)
        if fallback != "none":
            evidence_ids = fallback.split(";")
            adjustments.append(Adjustment("evidence", "model gave no usable ids; used top retrieval hit"))
    evidence = ";".join(evidence_ids) if evidence_ids else "none"

    # 9. Calibration. Agreement between the rule layer and the model earns
    # confidence; disagreement costs it.
    if verdict.forces_mute and decision.source == "model":
        confidence = max(confidence, 0.85)
    if adjustments and not verdict.forces_mute:
        confidence -= 0.03 * len([a for a in adjustments if a.rule in {"coherence", "schema", "fallback"}])
    if not ctx.evidence:
        confidence -= 0.02
    confidence = round(min(config.CONFIDENCE_CEILING, max(config.CONFIDENCE_FLOOR, confidence)), 2)

    if not reason:
        reason = "Routed from the available sender, content and history signals."

    return Routed(
        message_id=ctx.message.message_id,
        action=action,
        message_type=message_type,
        reason=" ".join(reason.split()),
        confidence=confidence,
        evidence_message_ids=evidence,
        adjustments=adjustments,
        key_signals=decision.key_signals,
        source=decision.source,
    )
