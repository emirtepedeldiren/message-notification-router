"""Show everything the router knows and decided about one message.

    python code/inspect_message.py msg_091
    python code/inspect_message.py --scams
    python code/inspect_message.py --compare msg_030 msg_031

Reads the cached media descriptions and the committed predictions, so it makes
no API calls and can be run freely to check the reasoning behind any row.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402
import risk  # noqa: E402
from context import build_context  # noqa: E402
from data_loader import Message, load_dataset, load_messages  # noqa: E402
from perception import MediaFacts, MediaPerceiver  # noqa: E402

RULE = "─" * 78


def load_predictions(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    with open(path, newline="", encoding="utf-8") as fh:
        return {row["message_id"]: row for row in csv.DictReader(fh)}


def show(message: Message, dataset, perceiver: MediaPerceiver, predictions: dict) -> None:
    facts = None
    if message.is_media:
        cached = perceiver.cached_text()
        path = dataset.media_path(message.media_type, message.media_id)
        facts = perceiver.perceive(message.media_id, message.media_type, path) if config.has_api_key() else None
        if facts is None or not facts.available:
            facts = MediaFacts(
                media_id=message.media_id,
                media_type=message.media_type,
                summary=cached.get(message.media_id, ""),
                text=cached.get(message.media_id, ""),
                available=bool(cached.get(message.media_id)),
            )

    ctx = build_context(dataset, message, facts, media_text=perceiver.cached_text())
    verdict = risk.assess(ctx)

    print(RULE)
    print(f"{message.message_id}  ·  {message.conversation_type}  ·  user {message.user_id}")
    print(RULE)

    body = message.message_text or f"[{message.media_type} attachment, no caption]"
    print("\nMESSAGE")
    for line in body.splitlines() or [""]:
        print(f"  {line}")

    if facts and facts.available:
        print("\nATTACHMENT (from the cached description)")
        for line in facts.render().splitlines()[1:]:
            print(f"  {line.strip()}")

    print(f"\nSENDER TRUST  {ctx.trust.label} ({ctx.trust.score:.2f})")
    for note in ctx.trust.notes:
        print(f"  · {note}")

    flags = ctx.text_signals.summary()
    print("\nCONTENT SIGNALS")
    print("  " + ("\n  ".join(f"· {f}" for f in flags) if flags else "· none"))

    print(f"\nSAFETY GATE  {verdict.level.upper()}")
    for line in verdict.render().splitlines()[1:] or ["  no rule fired"]:
        print(f"  {line.strip()}")

    print("\nWHAT THIS USER DID WITH SIMILAR MESSAGES BEFORE")
    if ctx.evidence:
        for item in ctx.evidence:
            print(f"  · {item.describe()}")
    else:
        print("  · no comparable history")

    context_bits = []
    if ctx.directly_mentioned:
        context_bits.append("mentions this user directly")
    if ctx.group_muted:
        context_bits.append("user has MUTED this group")
    if ctx.in_quiet_hours:
        context_bits.append("arrives inside do-not-disturb hours")
    if ctx.relationship and ctx.relationship.opted_out:
        context_bits.append("user opted out of this business's promotions")
    context_bits.append(f"recent dismissal rate {ctx.notification_pressure:.0%}")
    print("\nPERSONAL CONTEXT")
    for bit in context_bits:
        print(f"  · {bit}")

    row = predictions.get(message.message_id)
    print("\nDECISION")
    if row:
        print(f"  {row['action'].upper()} / {row['message_type']}   confidence {row['confidence']}")
        print(f"  reason:   {row['reason']}")
        print(f"  evidence: {row['evidence_message_ids']}")
    else:
        print("  (not in output.csv — run code/main.py first)")
    print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Explain the routing of one or more messages.")
    parser.add_argument("message_ids", nargs="*", help="message ids to explain")
    parser.add_argument("--scams", action="store_true", help="show every message the safety gate flagged")
    parser.add_argument("--compare", nargs=2, metavar="ID", help="show two messages side by side")
    parser.add_argument("--output", type=Path, default=config.REPO_ROOT / "output.csv")
    args = parser.parse_args(argv)

    dataset = load_dataset()
    messages = {m.message_id: m for m in load_messages()}
    messages.update({m.message_id: m for m in dataset.samples})
    perceiver = MediaPerceiver()
    predictions = load_predictions(args.output)

    wanted: list[str] = list(args.message_ids)
    if args.compare:
        wanted = list(args.compare)
    if args.scams:
        for mid, message in messages.items():
            if mid.startswith("sample_"):
                continue
            ctx = build_context(dataset, message, media_text=perceiver.cached_text())
            if risk.assess(ctx).forces_mute:
                wanted.append(mid)

    if not wanted:
        parser.error("give at least one message id, or use --scams")

    for mid in wanted:
        message = messages.get(mid)
        if message is None:
            print(f"unknown message id: {mid}")
            continue
        show(message, dataset, perceiver, predictions)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
