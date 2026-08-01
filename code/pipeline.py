"""Wires the stages together: perceive -> assemble -> assess risk -> route -> guard."""

from __future__ import annotations

import csv
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import config
import risk
from context import MessageContext, build_context
from data_loader import Dataset, Message
from perception import MediaFacts, MediaPerceiver
from postprocess import Routed, finalise
from router import Router

OUTPUT_COLUMNS = ["message_id", "action", "message_type", "reason", "confidence", "evidence_message_ids"]


@dataclass
class RunOptions:
    use_model: bool = True
    apply_quiet_hours: bool = True
    model: str | None = None
    workers: int = config.MAX_CONCURRENCY
    quiet: bool = False


class Pipeline:
    def __init__(self, dataset: Dataset, options: RunOptions | None = None):
        self.dataset = dataset
        self.options = options or RunOptions()
        self.perceiver = MediaPerceiver()
        self._router: Router | None = None

    @property
    def router(self) -> Router:
        if self._router is None:
            self._router = Router(self.dataset, model=self.options.model)
        return self._router

    def perceive_all(self, messages: list[Message]) -> dict[str, MediaFacts]:
        """Describe every distinct media file referenced by the batch.

        Done up front and de-duplicated by media id: several messages share the
        same attachment, and each file should cost at most one model call.
        """
        wanted: dict[str, str] = {}
        for message in messages:
            if message.is_media:
                wanted[message.media_id] = message.media_type

        facts: dict[str, MediaFacts] = {}
        pending = []
        for media_id, media_type in sorted(wanted.items()):
            path = self.dataset.media_path(media_type, media_id)
            pending.append((media_id, media_type, path))

        if not pending:
            return facts

        if not self.options.quiet:
            print(f"Perceiving {len(pending)} media file(s)...")

        def work(item):
            media_id, media_type, path = item
            return media_id, self.perceiver.perceive(media_id, media_type, path)

        with ThreadPoolExecutor(max_workers=self.options.workers) as pool:
            for media_id, result in pool.map(work, pending):
                facts[media_id] = result
        self.perceiver.save()
        return facts

    def prepare(self, messages: list[Message]) -> list[MessageContext]:
        media = self.perceive_all(messages)
        return [
            build_context(self.dataset, message, media.get(message.media_id) if message.is_media else None)
            for message in messages
        ]

    def route_one(self, ctx: MessageContext) -> Routed:
        verdict = risk.assess(ctx)
        decision = self.router.route(ctx, verdict) if self.options.use_model else None
        return finalise(ctx, verdict, decision, apply_quiet_hours=self.options.apply_quiet_hours)

    def run(self, messages: list[Message]) -> list[Routed]:
        contexts = self.prepare(messages)
        if not self.options.use_model:
            return [self.route_one(ctx) for ctx in contexts]

        if not self.options.quiet:
            print(f"Routing {len(contexts)} message(s) with {self.router.model}...")
        results: list[Routed] = [None] * len(contexts)  # type: ignore[list-item]
        with ThreadPoolExecutor(max_workers=self.options.workers) as pool:
            for index, routed in zip(
                range(len(contexts)), pool.map(self.route_one, contexts)
            ):
                results[index] = routed
                if not self.options.quiet:
                    print(f"  [{index + 1}/{len(contexts)}] {routed.message_id}: {routed.action}/{routed.message_type}")
        return results


def write_output(rows: list[Routed], path: Path) -> None:
    """Write predictions in the exact submission schema."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(OUTPUT_COLUMNS)
        for row in rows:
            writer.writerow(
                [row.message_id, row.action, row.message_type, row.reason, row.confidence, row.evidence_message_ids]
            )
