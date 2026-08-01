"""Text-level signal detection: what is this message actually asking for?

Keyword matching alone misfires badly on this dataset. A verified courier
writing "no payment or OTP is required for this delivery" trips every naive
credential filter while being entirely legitimate, so requests are only
counted when they are not inside a negated, advisory phrasing.

Scam text here is bilingual (English and Hinglish), so both are covered.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# --- request detection -------------------------------------------------------

CREDENTIAL_TERMS = re.compile(
    r"""\b(
        otp | o\.t\.p | one[\s-]?time[\s-]?(?:password|code|pin)
      | \d\s*digit\s+(?:login\s+)?code | login\s+code | verification\s+code
      | security\s+code | cvv | atm\s+pin | upi\s+pin | wallet\s+pin
      | password | passcode | credentials
      | verification\s+code | auth\s+code
    )\b""",
    re.IGNORECASE | re.VERBOSE,
)

# A bare "PIN" only counts as a credential ask when something is being done
# with it — "confirm your PIN" is a request, "PIN code area" is not.
CREDENTIAL_BARE_PIN = re.compile(
    r"\b(confirm|share|enter|provide|send|verify|submit|update)\s+(?:your\s+|the\s+)?(?:\w+\s+){0,2}pin\b",
    re.IGNORECASE,
)

# Hinglish credential asks: "OTP batao", "code daal do", "verification confirm karo".
CREDENTIAL_HINGLISH = re.compile(
    r"(otp|code|password|pin)\s+\w{0,12}\s*(batao|bhejo|daal|dalo|share\s+kar|confirm\s+kar|bata\s+do)",
    re.IGNORECASE,
)

PAYMENT_TERMS = re.compile(
    r"""\b(
        pay\s+(?:now|immediately|the|small|this|before|through)
      | make\s+(?:the\s+)?payment | complete\s+(?:the\s+)?payment
      | clearance\s+amount | reattempt\s+(?:charge|fee) | pending\s+(?:charge|dues|amount)
      | scan\s+(?:this\s+)?qr | transfer\s+(?:the\s+)?(?:amount|money)
      | penalty | late\s+fee | processing\s+fee | release\s+the\s+(?:amount|package|parcel)
      | wallet\s+(?:details|verification) | card\s+details | bank\s+details
      | paisa\s+bhejo | payment\s+karo
    )\b""",
    re.IGNORECASE | re.VERBOSE,
)

ACCOUNT_THREAT = re.compile(
    r"""(
        (?:account|profile|access|card|wallet|workspace)\s+(?:\w+\s+){0,3}
        (?:blocked|block|suspended|restricted|locked|closed|closure|deactivat\w*|expire\w*)
      | will\s+expire\s+today | permanent\s+block | temporarily\s+blocked
      | band\s+ho\s+jayega | block\s+ho\s+jayega | hold\s+pe\s+chala
      | before\s+(?:midnight|6\s*(?:pm|baje)) | final\s+reminder
      | failed\s+login\s+attempts | verification\s+(?:is\s+)?pending
    )""",
    re.IGNORECASE | re.VERBOSE,
)

URGENCY_TERMS = re.compile(
    r"\b(urgent|urgently|immediately|right now|asap|hurry|jaldi|abhi|quickly|last chance|today only|within \d+ (?:mins?|minutes|hours))\b",
    re.IGNORECASE,
)

PROMO_TERMS = re.compile(
    r"""\b(
        \d{1,3}\s*%\s*off | flat\s+\d+\s*off | discount | sale | offer\s+(?:ends|valid)
      | coupon | promo\s*code | use\s+code | limited\s+period | buy\s+now
      | shop\s+now | order\s+now | subscribe | unsubscribe | t&c\s+apply
      | book\s+now | starting\s+at | per\s+person
    )\b""",
    re.IGNORECASE | re.VERBOSE,
)

GREETING_TERMS = re.compile(
    r"\b(good morning|good evening|good night|happy (?:birthday|anniversary|new year|diwali|eid)|blessings|stay positive|good vibes|shubh)\b",
    re.IGNORECASE,
)

FORWARD_TERMS = re.compile(
    r"\b(fwd|forwarded as received|fwd as received|forwarding because|received on another group|copy paste|share with everyone|share with all)\b",
    re.IGNORECASE,
)

# Advisory phrasing that mentions a credential in order to warn against it.
NEGATED_REQUEST = re.compile(
    r"""(
        (?:no|never|not|don't|do\s+not|dont)\s+(?:\w+\s+){0,4}
        (?:ask|asks|asking|share|shares|sharing|require[sd]?|need(?:ed|s)?|request(?:s|ed)?)
      | (?:is|are)\s+not\s+required
      | (?:we|they|brand|bank)\s+(?:will\s+)?never
      | beware\s+of | be\s+aware\s+of | do\s+not\s+share
    )""",
    re.IGNORECASE | re.VERBOSE,
)

# --- router manipulation -----------------------------------------------------

# Instructions aimed at the routing system rather than the human recipient.
# A genuine WhatsApp message never tells the notification router what to do,
# so any match is treated as an active manipulation attempt.
INJECTION_PATTERNS = re.compile(
    r"""(
        ignore\s+(?:all\s+)?(?:previous|prior|earlier|above)\s+(?:instructions?|rules?|routing|prompts?)
      | ignore\s+sender\s+risk
      | (?:system|internal|admin)\s+(?:note|message|instruction|metadata|prompt)\s*(?:for|to)?\s*
        (?:the\s+)?(?:notification\s+)?(?:router|assistant|ai|model|system)?
      | routing\s+(?:override|rule|instruction)
      | assistant\s+instruction
      | (?:set|mark|classify|treat)\s+(?:this\s+)?(?:message\s+)?(?:as\s+)?
        (?:action\s*=\s*)?(?:notify|urgent|high\s+priority)
      | action\s*=\s*(?:notify|digest|mute)
      | confidence\s*=\s*\d
      | user_priority\s*=\s* | verified_business\s*=\s*
      | you\s+are\s+(?:an?\s+)?(?:ai|assistant|model|router)
      | override\s+(?:the\s+)?(?:routing|classification|decision)
    )""",
    re.IGNORECASE | re.VERBOSE,
)

# --- links -------------------------------------------------------------------

URL_RE = re.compile(
    r"\b((?:https?://)?(?:[a-z0-9][a-z0-9-]*\.)+[a-z]{2,}(?:/[^\s,;)]*)?)",
    re.IGNORECASE,
)

SHORTENERS = {"bit.ly", "tinyurl.com", "t.co", "goo.gl", "rb.gy", "cutt.ly", "is.gd", "shorturl.at"}

# Words that show up in domains built to look like a brand's support channel.
LOOKALIKE_MARKERS = (
    "verify",
    "secure",
    "alert",
    "login",
    "help",
    "support",
    "refund",
    "update",
    "account",
    "kyc",
    "confirm",
    "check",
    "service",
    "care",
)

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")


def extract_domains(text: str) -> list[str]:
    """Domains referenced in the text, lowercased and de-duplicated."""
    seen: list[str] = []
    for match in URL_RE.finditer(text or ""):
        raw = match.group(1)
        host = raw.split("://")[-1].split("/")[0].lower().strip(".")
        # Skip bare sentence fragments like "e.g" that survive the URL regex.
        if "." not in host or len(host.rsplit(".", 1)[-1]) < 2:
            continue
        if host not in seen:
            seen.append(host)
    return seen


def registrable(domain: str) -> str:
    """Approximate the registrable part, keeping two labels (three for ccSLDs)."""
    parts = domain.lower().split(".")
    if len(parts) <= 2:
        return domain.lower()
    if parts[-2] in {"co", "com", "net", "org", "gov", "ac"} and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def looks_like_lookalike(domain: str, brand_domain: str = "") -> bool:
    """Whether a domain is dressed up as a brand's official channel.

    Two independent tells. The stronger one is a brand name embedded in a
    domain that is not the brand's own — "amazonpay-delivery.in" against an
    official "amazon.in". The weaker one, used when no brand is known, is a
    domain built out of support vocabulary such as "account-login.in".
    """
    host = registrable(domain)
    if brand_domain:
        official = registrable(brand_domain)
        if host == official:
            return False
        brand = official.split(".")[0]
        if brand and brand in host:
            return True
    return any(marker in host for marker in LOOKALIKE_MARKERS)


def _requested(text: str, pattern: re.Pattern[str]) -> bool:
    """True when the pattern matches in a sentence that is not an advisory.

    Checking per sentence keeps "your refund is ready, we never ask for OTP"
    from cancelling a genuine request elsewhere in a longer message.
    """
    for sentence in _SENTENCE_SPLIT.split(text or ""):
        if pattern.search(sentence) and not NEGATED_REQUEST.search(sentence):
            return True
    return False


@dataclass
class TextSignals:
    """What the wording of a message asks for and how hard it pushes."""

    asks_credentials: bool = False
    asks_payment: bool = False
    threatens_account: bool = False
    urgent_language: bool = False
    promotional: bool = False
    greeting: bool = False
    forwarded_chain: bool = False
    injection_attempt: bool = False
    safety_advisory: bool = False
    domains: list[str] = field(default_factory=list)
    shortened_link: bool = False
    injection_snippets: list[str] = field(default_factory=list)

    @property
    def sensitive_request(self) -> bool:
        """Asks for something a scammer would want: credentials or money."""
        return self.asks_credentials or self.asks_payment

    @property
    def pressure(self) -> bool:
        """Manufactured urgency — the standard scam accelerant."""
        return self.threatens_account or self.urgent_language

    def summary(self) -> list[str]:
        """Human-readable flags for the prompt and for reason strings."""
        labels = [
            ("asks for OTP/credentials", self.asks_credentials),
            ("asks for payment", self.asks_payment),
            ("threatens account block/expiry", self.threatens_account),
            ("uses urgency language", self.urgent_language),
            ("promotional wording", self.promotional),
            ("greeting/well-wishing", self.greeting),
            ("forwarded-chain wording", self.forwarded_chain),
            ("tries to instruct the routing system", self.injection_attempt),
            ("safety advisory warning against sharing details", self.safety_advisory),
            ("uses a link shortener", self.shortened_link),
        ]
        return [name for name, on in labels if on]


def analyse(text: str) -> TextSignals:
    """Extract request, pressure and manipulation signals from message text."""
    text = text or ""
    domains = extract_domains(text)
    credentials = (
        _requested(text, CREDENTIAL_TERMS)
        or _requested(text, CREDENTIAL_BARE_PIN)
        or bool(CREDENTIAL_HINGLISH.search(text))
    )
    injections = [m.group(0).strip() for m in INJECTION_PATTERNS.finditer(text)]

    return TextSignals(
        asks_credentials=credentials,
        asks_payment=_requested(text, PAYMENT_TERMS),
        threatens_account=bool(ACCOUNT_THREAT.search(text)),
        urgent_language=bool(URGENCY_TERMS.search(text)),
        promotional=bool(PROMO_TERMS.search(text)),
        greeting=bool(GREETING_TERMS.search(text)),
        forwarded_chain=bool(FORWARD_TERMS.search(text)),
        injection_attempt=bool(injections),
        safety_advisory=bool(NEGATED_REQUEST.search(text)) and not credentials,
        domains=domains,
        shortened_link=any(registrable(d) in SHORTENERS for d in domains),
        injection_snippets=injections[:3],
    )
