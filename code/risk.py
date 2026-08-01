"""The safety gate: deterministic rules the language model cannot overrule.

The brief is explicit that clear scam or safety risk must be muted regardless
of how the user usually engages. Leaving that to a model is the wrong shape of
decision — it is exactly the part an attacker will try to talk their way past,
and this dataset contains messages that try. So risk is decided by rules here,
and `postprocess` enforces the verdict after the model has spoken.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import signals
from context import MessageContext

CRITICAL = "critical"
ELEVATED = "elevated"
CLEAR = "clear"


@dataclass
class RiskVerdict:
    """The safety layer's finding for one message."""

    level: str = CLEAR
    message_type: str = ""
    reasons: list[str] = field(default_factory=list)

    @property
    def forces_mute(self) -> bool:
        return self.level == CRITICAL

    def render(self) -> str:
        if self.level == CLEAR:
            return "No safety rule fired."
        header = {
            CRITICAL: "CRITICAL — this message must be muted for safety.",
            ELEVATED: "ELEVATED — treat with suspicion; strong lean towards mute.",
        }[self.level]
        return header + "\n" + "\n".join(f"- {r}" for r in self.reasons)


def assess(ctx: MessageContext) -> RiskVerdict:
    """Apply the safety rules to an assembled context."""
    sig = ctx.text_signals
    reasons: list[str] = []
    critical = False
    elevated = False
    kind = ""

    # 1. Attempted manipulation of the router itself.
    # A real message addresses the person, never the routing system. Anything
    # that issues instructions to the classifier is hostile by construction,
    # and in this dataset it always wraps a credential or payment lure.
    if sig.injection_attempt:
        critical = True
        kind = "scam"
        snippet = sig.injection_snippets[0] if sig.injection_snippets else "routing instruction"
        reasons.append(f'contains instructions aimed at the routing system ("{snippet.strip()[:80]}")')

    # 2. Any request for an OTP, PIN or password.
    # No legitimate sender on this platform asks a user to hand these over, so
    # this stands on its own rather than depending on sender reputation.
    if sig.asks_credentials:
        critical = True
        kind = kind or "scam"
        reasons.append("asks the user to share an OTP, PIN, password or login code")

    # 3. Impersonation: the sender is not on the brand's own domain.
    if ctx.business is not None and ctx.business.domain_mismatch:
        detail = (
            f"sender uses {ctx.business.domain_used_by_sender} while "
            f"{ctx.business.brand_name}'s official domain is {ctx.business.official_domain}"
        )
        if sig.sensitive_request or sig.threatens_account:
            critical = True
            kind = kind or "scam"
            reasons.append(f"{detail}, and the message pressures the user to pay or verify")
        else:
            elevated = True
            reasons.append(detail)

    # 4. A lookalike domain in the body, paired with a request.
    brand_domain = ctx.business.official_domain if ctx.business else ""
    lookalikes = [d for d in sig.domains if signals.looks_like_lookalike(d, brand_domain)]
    if lookalikes and (sig.sensitive_request or sig.threatens_account):
        critical = True
        kind = kind or "scam"
        reasons.append(f"points to a lookalike verification domain ({lookalikes[0]})")

    # 5. Payment demanded under threat by someone the user cannot vouch for.
    if sig.asks_payment and sig.threatens_account and ctx.trust.is_untrusted:
        critical = True
        kind = kind or "scam"
        reasons.append("demands payment under threat of account or access loss from an untrusted sender")

    # 6. A stranger's first contact asking for money or credentials.
    if sig.sensitive_request and not ctx.evidence and ctx.trust.is_untrusted:
        critical = True
        kind = kind or "scam"
        reasons.append("first contact from an unknown sender and it asks for payment or verification")

    # --- elevated-only patterns -------------------------------------------

    if ctx.business is not None:
        b = ctx.business
        if b.user_reports_30d >= 30:
            elevated = True
            reasons.append(f"business has {b.user_reports_30d} user reports in the last 30 days")
        if not b.verified and b.account_age_days < 60 and sig.promotional:
            elevated = True
            kind = kind or "spam"
            reasons.append(f"unverified account only {b.account_age_days} days old sending promotions")

    if sig.shortened_link and sig.pressure and not ctx.trust.is_established:
        elevated = True
        reasons.append("shortened link combined with urgency from a sender the user does not know well")

    if ctx.message.forwarded_count >= 5 and not sig.sensitive_request:
        elevated = True
        kind = kind or "spam"
        reasons.append(f"forwarded {ctx.message.forwarded_count} times — chain-forward content")

    if critical:
        return RiskVerdict(level=CRITICAL, message_type=kind or "scam", reasons=reasons)
    if elevated:
        return RiskVerdict(level=ELEVATED, message_type=kind, reasons=reasons)
    return RiskVerdict(level=CLEAR, reasons=[])
