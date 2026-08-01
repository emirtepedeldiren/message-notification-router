"""Loads the dataset CSVs into indexed, query-friendly structures.

Everything downstream (features, retrieval, routing) reads from the `Dataset`
object built here, so the CSV layout is parsed in exactly one place.
"""

from __future__ import annotations

import csv
import os
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time
from functools import cached_property
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATASET_DIR = Path(os.environ.get("DATASET_DIR", REPO_ROOT / "dataset"))

ACTIONS = ("notify", "digest", "mute")
MESSAGE_TYPES = (
    "personal",
    "urgent",
    "event",
    "payment",
    "business_update",
    "promotion",
    "greeting",
    "forward",
    "spam",
    "scam",
    "unknown",
)


def _read(path: Path) -> list[dict[str, str]]:
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _int(value: str | None, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _bool(value: str | None) -> bool:
    return str(value).strip() in {"1", "true", "True", "yes"}


def _dt(value: str | None) -> datetime | None:
    """Parse the dataset's timestamp formats; returns None for blanks."""
    raw = (value or "").strip()
    if not raw:
        return None
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def _parse_window(raw: str | None) -> tuple[time, time] | None:
    """Parse a "22:00-07:00" do-not-disturb window into a (start, end) pair."""
    raw = (raw or "").strip()
    if "-" not in raw:
        return None
    start_s, _, end_s = raw.partition("-")
    try:
        start_h, start_m = (int(x) for x in start_s.strip().split(":"))
        end_h, end_m = (int(x) for x in end_s.strip().split(":"))
    except ValueError:
        return None
    return time(start_h, start_m), time(end_h, end_m)


@dataclass(frozen=True)
class Message:
    """One message row — shape is shared by messages, history, and samples."""

    message_id: str
    user_id: str
    conversation_type: str
    group_id: str
    business_id: str
    sender_user_id: str
    created_at: datetime | None
    message_text: str
    media_type: str
    media_id: str
    forwarded_count: int
    # Present only on sample_messages.csv rows.
    action: str = ""
    message_type: str = ""
    reason: str = ""
    confidence: float = 0.0
    evidence_message_ids: str = ""

    @property
    def is_media(self) -> bool:
        return bool(self.media_type and self.media_id)

    @property
    def channel_key(self) -> tuple[str, str]:
        """Identifies the conversation this message arrived through.

        Used by retrieval to prefer history from the same channel, and by
        features to describe who the counterparty is.
        """
        if self.business_id:
            return ("business", self.business_id)
        if self.group_id:
            return ("group", self.group_id)
        if self.sender_user_id:
            return ("sender", self.sender_user_id)
        return ("unknown", "")

    @classmethod
    def from_row(cls, row: dict[str, str]) -> "Message":
        return cls(
            message_id=row["message_id"].strip(),
            user_id=row["user_id"].strip(),
            conversation_type=row.get("conversation_type", "").strip(),
            group_id=row.get("group_id", "").strip(),
            business_id=row.get("business_id", "").strip(),
            sender_user_id=row.get("sender_user_id", "").strip(),
            created_at=_dt(row.get("created_at")),
            message_text=(row.get("message_text") or "").strip(),
            media_type=(row.get("media_type") or "").strip(),
            media_id=(row.get("media_id") or "").strip(),
            forwarded_count=_int(row.get("forwarded_count")),
            action=(row.get("action") or "").strip(),
            message_type=(row.get("message_type") or "").strip(),
            reason=(row.get("reason") or "").strip(),
            confidence=float(row["confidence"]) if row.get("confidence") else 0.0,
            evidence_message_ids=(row.get("evidence_message_ids") or "").strip(),
        )


@dataclass(frozen=True)
class Event:
    """How a user reacted to a historical message."""

    user_id: str
    message_id: str
    opened: bool
    replied: bool
    reaction_time_minutes: int
    dismissed: bool
    muted_after: bool
    reported: bool

    @property
    def is_negative(self) -> bool:
        """True when the user actively pushed the message away."""
        return self.dismissed or self.muted_after or self.reported

    @property
    def is_positive(self) -> bool:
        return self.opened or self.replied

    def describe(self) -> str:
        """Short human-readable outcome, used in prompts and reasons."""
        parts = []
        if self.replied:
            parts.append("replied")
        elif self.opened:
            parts.append("opened")
        if self.dismissed:
            parts.append("dismissed")
        if self.muted_after:
            parts.append("muted the chat after it")
        if self.reported:
            parts.append("reported it")
        if not parts:
            parts.append("ignored")
        return ", ".join(parts)


@dataclass(frozen=True)
class User:
    user_id: str
    dnd_window: tuple[time, time] | None
    messages_opened_30d: int
    messages_replied_30d: int
    notifications_dismissed_30d: int
    messages_reported_30d: int

    def in_quiet_hours(self, when: datetime | None) -> bool:
        """Whether `when` falls inside the user's DND window.

        Windows normally wrap past midnight (22:00-07:00), so the comparison
        splits into the wrapping and non-wrapping cases.
        """
        if when is None or self.dnd_window is None:
            return False
        start, end = self.dnd_window
        now = when.time()
        if start <= end:
            return start <= now < end
        return now >= start or now < end

    @property
    def dismissal_rate_30d(self) -> float:
        seen = self.messages_opened_30d + self.notifications_dismissed_30d
        return self.notifications_dismissed_30d / seen if seen else 0.0


@dataclass(frozen=True)
class Group:
    group_id: str
    group_name: str
    group_type: str
    member_count: int
    admin_count: int
    created_at: date | None
    messages_30d: int


@dataclass(frozen=True)
class Membership:
    group_id: str
    user_id: str
    role: str
    joined_at: date | None
    messages_sent_30d: int
    messages_read_30d: int
    replies_sent_30d: int
    notifications_dismissed_30d: int
    muted: bool

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def engagement_rate(self) -> float:
        """Share of this user's activity in the group that is positive."""
        pos = self.messages_read_30d + self.replies_sent_30d
        total = pos + self.notifications_dismissed_30d
        return pos / total if total else 0.0


@dataclass(frozen=True)
class Business:
    business_id: str
    display_name: str
    brand_name: str
    category: str
    verified: bool
    official_domain: str
    domain_used_by_sender: str
    account_age_days: int
    messages_sent_30d: int
    user_reports_30d: int
    domain_used_by_sender_age_days: int

    @property
    def domain_mismatch(self) -> bool:
        """Sender is messaging from a domain other than the brand's official one.

        This is the single strongest impersonation signal in the dataset.
        """
        if not self.official_domain or not self.domain_used_by_sender:
            return False
        return self.official_domain.lower() != self.domain_used_by_sender.lower()


@dataclass(frozen=True)
class BusinessRelationship:
    user_id: str
    business_id: str
    why_user_knows_account: str
    last_activity_at: datetime | None
    allows_promotions: bool
    promotions_opted_out_at: datetime | None
    activity_count_180d: int
    messages_opened_30d: int
    messages_dismissed_30d: int
    messages_replied_30d: int
    last_reply_at: datetime | None

    @property
    def opted_out(self) -> bool:
        return self.promotions_opted_out_at is not None or not self.allows_promotions

    @property
    def dismissal_rate_30d(self) -> float:
        seen = self.messages_opened_30d + self.messages_dismissed_30d
        return self.messages_dismissed_30d / seen if seen else 0.0

    @property
    def is_active_relationship(self) -> bool:
        """User has genuinely transacted with this business recently."""
        return self.activity_count_180d > 0 or self.messages_replied_30d > 0


@dataclass
class Dataset:
    users: dict[str, User]
    groups: dict[str, Group]
    memberships: dict[tuple[str, str], Membership]
    businesses: dict[str, Business]
    relationships: dict[tuple[str, str], BusinessRelationship]
    history: dict[str, Message]
    events: dict[tuple[str, str], Event]
    images: dict[str, str]
    voice_notes: dict[str, str]
    notification_load: dict[str, list[tuple[date, int, int]]]
    samples: list[Message] = field(default_factory=list)

    @cached_property
    def history_by_user(self) -> dict[str, list[Message]]:
        by_user: dict[str, list[Message]] = defaultdict(list)
        for msg in self.history.values():
            by_user[msg.user_id].append(msg)
        for msgs in by_user.values():
            msgs.sort(key=lambda m: m.created_at or datetime.min)
        return dict(by_user)

    def event_for(self, user_id: str, message_id: str) -> Event | None:
        return self.events.get((user_id, message_id))

    def media_path(self, media_type: str, media_id: str) -> Path | None:
        """Absolute path to a media file, or None if the id is unknown."""
        table = self.images if media_type == "image" else self.voice_notes
        rel = table.get(media_id)
        return DATASET_DIR / rel if rel else None

    def notification_pressure(self, user_id: str, on: date | None = None) -> float:
        """Share of recent notifications the user dismissed (0.0 - 1.0).

        High pressure means the user is already swamped, which argues for
        holding borderline messages back into the digest.
        """
        rows = self.notification_load.get(user_id) or []
        if on is not None:
            rows = [r for r in rows if r[0] <= on][-7:]
        else:
            rows = rows[-7:]
        sent = sum(r[1] for r in rows)
        dismissed = sum(r[2] for r in rows)
        return dismissed / sent if sent else 0.0


def load_dataset(dataset_dir: Path | None = None) -> Dataset:
    """Read every CSV in the dataset directory into a `Dataset`."""
    root = Path(dataset_dir or DATASET_DIR)

    users = {}
    for row in _read(root / "users.csv"):
        users[row["user_id"]] = User(
            user_id=row["user_id"],
            dnd_window=_parse_window(row.get("do_not_disturb_window")),
            messages_opened_30d=_int(row.get("messages_opened_30d")),
            messages_replied_30d=_int(row.get("messages_replied_30d")),
            notifications_dismissed_30d=_int(row.get("notifications_dismissed_30d")),
            messages_reported_30d=_int(row.get("messages_reported_30d")),
        )

    groups = {}
    for row in _read(root / "groups.csv"):
        created = _dt(row.get("created_at"))
        groups[row["group_id"]] = Group(
            group_id=row["group_id"],
            group_name=row.get("group_name", ""),
            group_type=row.get("group_type", ""),
            member_count=_int(row.get("member_count")),
            admin_count=_int(row.get("admin_count")),
            created_at=created.date() if created else None,
            messages_30d=_int(row.get("messages_30d")),
        )

    memberships = {}
    for row in _read(root / "group_members.csv"):
        joined = _dt(row.get("joined_at"))
        memberships[(row["group_id"], row["user_id"])] = Membership(
            group_id=row["group_id"],
            user_id=row["user_id"],
            role=row.get("role", ""),
            joined_at=joined.date() if joined else None,
            messages_sent_30d=_int(row.get("messages_sent_30d")),
            messages_read_30d=_int(row.get("messages_read_30d")),
            replies_sent_30d=_int(row.get("replies_sent_30d")),
            notifications_dismissed_30d=_int(row.get("notifications_dismissed_30d")),
            muted=_bool(row.get("group_muted_by_user")),
        )

    businesses = {}
    for row in _read(root / "business_accounts.csv"):
        businesses[row["business_id"]] = Business(
            business_id=row["business_id"],
            display_name=row.get("display_name", ""),
            brand_name=row.get("brand_name", ""),
            category=row.get("category", ""),
            verified=_bool(row.get("verified")),
            official_domain=row.get("official_domain", "").strip(),
            domain_used_by_sender=row.get("domain_used_by_sender", "").strip(),
            account_age_days=_int(row.get("account_age_days")),
            messages_sent_30d=_int(row.get("messages_sent_30d")),
            user_reports_30d=_int(row.get("user_reports_30d")),
            domain_used_by_sender_age_days=_int(row.get("domain_used_by_sender_age_days")),
        )

    relationships = {}
    for row in _read(root / "user_business_history.csv"):
        relationships[(row["user_id"], row["business_id"])] = BusinessRelationship(
            user_id=row["user_id"],
            business_id=row["business_id"],
            why_user_knows_account=row.get("why_user_knows_account", ""),
            last_activity_at=_dt(row.get("last_activity_at")),
            allows_promotions=_bool(row.get("allows_promotions")),
            promotions_opted_out_at=_dt(row.get("promotions_opted_out_at")),
            activity_count_180d=_int(row.get("activity_count_180d")),
            messages_opened_30d=_int(row.get("messages_opened_30d")),
            messages_dismissed_30d=_int(row.get("messages_dismissed_30d")),
            messages_replied_30d=_int(row.get("messages_replied_30d")),
            last_reply_at=_dt(row.get("last_reply_at")),
        )

    history = {r["message_id"]: Message.from_row(r) for r in _read(root / "message_history.csv")}

    events = {}
    for row in _read(root / "message_events.csv"):
        events[(row["user_id"], row["message_id"])] = Event(
            user_id=row["user_id"],
            message_id=row["message_id"],
            opened=_bool(row.get("message_opened")),
            replied=_bool(row.get("message_replied")),
            reaction_time_minutes=_int(row.get("reaction_time_minutes"), -1),
            dismissed=_bool(row.get("notification_dismissed")),
            muted_after=_bool(row.get("muted_after_message")),
            reported=_bool(row.get("message_reported")),
        )

    images = {r["image_id"]: r["file_path"] for r in _read(root / "images.csv")}
    voice_notes = {r["voice_note_id"]: r["file_path"] for r in _read(root / "voice_notes.csv")}

    load: dict[str, list[tuple[date, int, int]]] = defaultdict(list)
    for row in _read(root / "daily_notification_summary.csv"):
        day = _dt(row.get("date"))
        if day is None:
            continue
        load[row["user_id"]].append(
            (day.date(), _int(row.get("notifications_sent")), _int(row.get("notifications_dismissed")))
        )
    for rows in load.values():
        rows.sort()

    samples = [Message.from_row(r) for r in _read(root / "sample_messages.csv")]

    return Dataset(
        users=users,
        groups=groups,
        memberships=memberships,
        businesses=businesses,
        relationships=relationships,
        history=history,
        events=events,
        images=images,
        voice_notes=voice_notes,
        notification_load=dict(load),
        samples=samples,
    )


def load_messages(path: Path | None = None) -> list[Message]:
    """Read the messages that need predictions."""
    return [Message.from_row(r) for r in _read(Path(path or DATASET_DIR / "messages.csv"))]
