"""Wires the stages together: perceive -> assemble -> assess risk -> route -> guard."""

from __future__ import annotations

import csv
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import config
import risk
from context import MessageContext, build_context
from data_loader import Dataset, Message
from llm import QuotaExhausted
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
    checkpoint: Path | None = None
    # Ablation switches. Turning one off removes that evidence from the
    # context card so the evaluation can price what it contributes.
    use_media: bool = True
    use_retrieval: bool = True


class Checkpoint:
    """Persists finished rows so an interrupted run can resume.

    Free-tier quota can run out mid-run, and re-routing messages that already
    have answers would spend the remaining allowance on work already done.
    """

    def __init__(self, path: Path | None):
        self.path = path
        self._lock = threading.Lock()
        self._rows: dict[str, dict] = {}
        if path and path.exists():
            self._rows = json.loads(path.read_text(encoding="utf-8"))

    def get(self, message_id: str, accept_rules: bool = True) -> Routed | None:
        """Return a stored row, if one can be reused.

        A row produced by the rule fallback is a placeholder left behind when
        quota ran out, not a finished answer. With a working model available,
        resuming should redo those rather than keep the degraded verdict.
        """
        stored = self._rows.get(message_id)
        if stored is None:
            return None
        if not accept_rules and stored.get("source") != "model":
            return None
        return Routed(**{**stored, "adjustments": []})

    def put(self, row: Routed) -> None:
        if self.path is None:
            return
        with self._lock:
            self._rows[row.message_id] = {
                "message_id": row.message_id,
                "action": row.action,
                "message_type": row.message_type,
                "reason": row.reason,
                "confidence": row.confidence,
                "evidence_message_ids": row.evidence_message_ids,
                "key_signals": row.key_signals,
                "source": row.source,
            }
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self._rows, indent=2, ensure_ascii=False), encoding="utf-8")


class Pipeline:
    def __init__(self, dataset: Dataset, options: RunOptions | None = None):
        self.dataset = dataset
        self.options = options or RunOptions()
        self.perceiver = MediaPerceiver()
        self.checkpoint = Checkpoint(self.options.checkpoint)
        self._router: Router | None = None
        self._quota_gone = False

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
        media = self.perceive_all(messages) if self.options.use_media else {}
        # Everything described so far, including media attached to historical
        # messages, so retrieval can match those on content too.
        history_media = self.perceiver.cached_text() if self.options.use_media else {}

        contexts = [
            build_context(
                self.dataset,
                message,
                media.get(message.media_id) if message.is_media else None,
                media_text=history_media,
            )
            for message in messages
        ]
        if not self.options.use_retrieval:
            for ctx in contexts:
                ctx.evidence = []
        return contexts

    def route_one(self, ctx: MessageContext) -> Routed:
        cached = self.checkpoint.get(
            ctx.message.message_id,
            accept_rules=not self.options.use_model or self._quota_gone,
        )
        if cached is not None:
            return cached

        verdict = risk.assess(ctx)
        decision = None
        if self.options.use_model and not self._quota_gone:
            try:
                decision = self.router.route(ctx, verdict)
            except QuotaExhausted as exc:
                # Keep going on rules alone rather than abandoning the run: a
                # complete output with a degraded tail beats a partial file.
                self._quota_gone = True
                print(f"  ! {exc}; routing the remainder on rules alone", flush=True)

        row = finalise(ctx, verdict, decision, apply_quiet_hours=self.options.apply_quiet_hours)
        self.checkpoint.put(row)
        return row

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
