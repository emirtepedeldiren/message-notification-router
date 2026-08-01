"""Entry point: route dataset/messages.csv into output.csv.

    python code/main.py                      # full run, writes output.csv
    python code/main.py --no-llm             # rules-only baseline, no API key needed
    python code/main.py --limit 10 --verbose  # quick smoke run
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402
from data_loader import DATASET_DIR, load_dataset, load_messages  # noqa: E402
from pipeline import Pipeline, RunOptions, write_output  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Route WhatsApp messages to notify / digest / mute.")
    parser.add_argument("--input", type=Path, default=DATASET_DIR / "messages.csv", help="messages to route")
    parser.add_argument("--output", type=Path, default=config.REPO_ROOT / "output.csv", help="where to write predictions")
    parser.add_argument("--limit", type=int, help="route only the first N messages")
    parser.add_argument("--only", help="comma-separated message ids to route")
    parser.add_argument("--no-llm", action="store_true", help="rules-only baseline; makes no API calls")
    parser.add_argument("--no-quiet-hours", action="store_true", help="disable the do-not-disturb guardrail")
    parser.add_argument("--model", help=f"router model (default {config.ROUTER_MODEL})")
    parser.add_argument("--workers", type=int, default=config.MAX_CONCURRENCY)
    parser.add_argument("--verbose", action="store_true", help="print the guardrails that fired")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if not args.no_llm and not config.has_api_key():
        print(
            "GEMINI_API_KEY is not set.\n"
            "  Copy .env.example to .env and add a key from https://aistudio.google.com/apikey,\n"
            "  or run with --no-llm for the rules-only baseline.",
            file=sys.stderr,
        )
        return 2

    dataset = load_dataset()
    messages = load_messages(args.input)
    if args.only:
        wanted = {m.strip() for m in args.only.split(",") if m.strip()}
        messages = [m for m in messages if m.message_id in wanted]
    if args.limit:
        messages = messages[: args.limit]

    if not messages:
        print("No messages to route.", file=sys.stderr)
        return 1

    options = RunOptions(
        use_model=not args.no_llm,
        apply_quiet_hours=not args.no_quiet_hours,
        model=args.model,
        workers=args.workers,
    )
    rows = Pipeline(dataset, options).run(messages)
    write_output(rows, args.output)

    counts: dict[str, int] = {}
    for row in rows:
        counts[row.action] = counts.get(row.action, 0) + 1
    print(f"\nWrote {len(rows)} rows to {args.output}")
    print("  " + ", ".join(f"{action}: {counts.get(action, 0)}" for action in ("notify", "digest", "mute")))

    if args.verbose:
        adjusted = [r for r in rows if r.adjustments]
        print(f"\nGuardrails fired on {len(adjusted)} message(s):")
        for row in adjusted:
            for adjustment in row.adjustments:
                print(f"  {row.message_id}: [{adjustment.rule}] {adjustment.detail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
