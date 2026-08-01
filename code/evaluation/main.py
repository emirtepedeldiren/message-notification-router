"""Evaluation workflow: score the router against the labelled samples.

    python code/evaluation/main.py                  # score the default configuration
    python code/evaluation/main.py --ablations      # add rules-only and feature ablations
    python code/evaluation/main.py --compare gemini-2.5-flash gemini-2.5-flash-lite
    python code/evaluation/main.py --report code/evaluation/report.md

The dev set is `dataset/sample_messages.csv` — 30 labelled rows. That is small
enough that a single accuracy number carries roughly +/-9 points of noise, so
the report leads with per-class behaviour, safety, and calibration rather than
one headline figure.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
from data_loader import ACTIONS, MESSAGE_TYPES, Message, load_dataset  # noqa: E402
from evaluation.metrics import (  # noqa: E402
    score_calibration,
    score_evidence,
    score_labels,
    score_safety,
)
from pipeline import Pipeline, RunOptions  # noqa: E402
from postprocess import Routed  # noqa: E402


@dataclass
class RunResult:
    name: str
    rows: list[Routed]
    samples: list[Message]

    @property
    def gold_actions(self) -> list[str]:
        return [s.action for s in self.samples]

    @property
    def gold_types(self) -> list[str]:
        return [s.message_type for s in self.samples]

    @property
    def pred_actions(self) -> list[str]:
        return [r.action for r in self.rows]

    @property
    def pred_types(self) -> list[str]:
        return [r.message_type for r in self.rows]


def run_configuration(dataset, samples: list[Message], name: str, options: RunOptions) -> RunResult:
    print(f"\n--- {name} ---")
    rows = Pipeline(dataset, options).run(samples)
    return RunResult(name=name, rows=rows, samples=samples)


def render_report(result: RunResult, verbose: bool = False) -> str:
    action_report = score_labels(result.gold_actions, result.pred_actions)
    type_report = score_labels(result.gold_types, result.pred_types)
    evidence = score_evidence(
        [s.evidence_message_ids for s in result.samples],
        [r.evidence_message_ids for r in result.rows],
    )
    correct = [g == p for g, p in zip(result.gold_actions, result.pred_actions)]
    calibration = score_calibration(correct, [r.confidence for r in result.rows])
    safety = score_safety(result.gold_actions, result.gold_types, result.pred_actions)

    # Quota can cut a run short, leaving some rows on the rule baseline. Mixing
    # those into one number hides which component is actually being measured.
    modelled = [i for i, r in enumerate(result.rows) if r.source == "model"]
    fell_back = [i for i, r in enumerate(result.rows) if r.source != "model"]

    lines = [
        f"## {result.name}",
        "",
        f"- action accuracy: **{action_report.accuracy:.0%}** ({sum(correct)}/{len(correct)}), "
        f"macro-F1 {action_report.macro_f1:.2f}",]
    if fell_back and modelled:
        model_acc = sum(correct[i] for i in modelled) / len(modelled)
        rule_acc = sum(correct[i] for i in fell_back) / len(fell_back)
        lines.append(
            f"- coverage: {len(modelled)}/{len(result.rows)} rows answered by the model "
            f"({model_acc:.0%} accurate); {len(fell_back)} fell back to rules ({rule_acc:.0%} accurate)"
        )
    lines += [
        f"- message_type accuracy: **{type_report.accuracy:.0%}**, macro-F1 {type_report.macro_f1:.2f}",
        f"- safety: {safety.unsafe_muted}/{safety.unsafe_total} risky messages muted "
        f"(recall {safety.recall:.0%}), {safety.unsafe_notified} reached notify",
        f"- over-suppression: {safety.false_mutes} message(s) the user wanted were muted",
        f"- evidence: {evidence.exact:.0%} overlap with gold ids, "
        f"proposed evidence on {evidence.predicted_any:.0%} of rows",
        f"- calibration: ECE {calibration.ece:.3f}, mean confidence {calibration.mean_confidence:.2f} "
        f"vs accuracy {calibration.accuracy:.2f} (gap {calibration.overconfidence:+.2f})",
        "",
        "### Action confusion",
        "```",
        action_report.confusion_table(list(ACTIONS)),
        "```",
    ]

    if verbose:
        lines += ["", "### message_type confusion", "```", type_report.confusion_table(list(MESSAGE_TYPES)), "```"]
        lines += ["", "### Per-action detail", "", "| action | precision | recall | F1 | support |", "|---|---|---|---|---|"]
        for label in ACTIONS:
            m = action_report.per_class.get(label)
            if m:
                lines.append(
                    f"| {label} | {m['precision']:.2f} | {m['recall']:.2f} | {m['f1']:.2f} | {int(m['support'])} |"
                )
        lines += ["", "### Calibration bins", "", "| confidence | n | mean conf | accuracy |", "|---|---|---|---|"]
        for edge, count, conf, acc in calibration.bins:
            lines.append(f"| {edge} | {count} | {conf:.2f} | {acc:.2f} |")

        mistakes = [
            (s, r) for s, r in zip(result.samples, result.rows) if s.action != r.action or s.message_type != r.message_type
        ]
        if mistakes:
            lines += ["", "### Disagreements", ""]
            for sample, row in mistakes:
                body = " ".join((sample.message_text or f"[{sample.media_type}]").split())[:90]
                lines.append(
                    f"- `{sample.message_id}` gold **{sample.action}/{sample.message_type}** "
                    f"vs predicted **{row.action}/{row.message_type}** — \"{body}\""
                )
                if row.adjustments:
                    lines.append(f"  - guardrails: {', '.join(a.rule for a in row.adjustments)}")
    return "\n".join(lines)


def summary_row(result: RunResult) -> tuple[str, float, float, float, float]:
    action = score_labels(result.gold_actions, result.pred_actions)
    types = score_labels(result.gold_types, result.pred_types)
    safety = score_safety(result.gold_actions, result.gold_types, result.pred_actions)
    evidence = score_evidence(
        [s.evidence_message_ids for s in result.samples], [r.evidence_message_ids for r in result.rows]
    )
    return (result.name, action.accuracy, types.accuracy, safety.recall, evidence.exact)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate the notification router on the labelled samples.")
    parser.add_argument("--ablations", action="store_true", help="also run rules-only and guardrail ablations")
    parser.add_argument("--compare", nargs="*", metavar="MODEL", help="score several router models")
    parser.add_argument("--report", type=Path, help="write the full markdown report here")
    parser.add_argument("--limit", type=int, help="use only the first N samples")
    parser.add_argument("--verbose", action="store_true", help="include confusion detail and disagreements")
    parser.add_argument("--no-llm", action="store_true", help="score the rules-only baseline alone")
    args = parser.parse_args(argv)

    dataset = load_dataset()
    samples = dataset.samples[: args.limit] if args.limit else dataset.samples
    print(f"Dev set: {len(samples)} labelled samples")

    results: list[RunResult] = []
    have_key = config.has_api_key()

    if args.no_llm or not have_key:
        if not have_key and not args.no_llm:
            print("No GEMINI_API_KEY set — scoring the rules-only baseline.")
        results.append(
            run_configuration(dataset, samples, "rules only (no model)", RunOptions(use_model=False, quiet=True))
        )
    else:
        models = args.compare if args.compare else [config.ROUTER_MODEL]
        for model in models:
            results.append(
                run_configuration(dataset, samples, f"hybrid: {model}", RunOptions(model=model, quiet=True))
            )
        if args.ablations:
            results.append(
                run_configuration(dataset, samples, "rules only (no model)", RunOptions(use_model=False, quiet=True))
            )
            results.append(
                run_configuration(
                    dataset,
                    samples,
                    "hybrid without the quiet-hours guardrail",
                    RunOptions(apply_quiet_hours=False, quiet=True),
                )
            )

    sections = [render_report(result, verbose=args.verbose) for result in results]

    if len(results) > 1:
        table = [
            "## Comparison",
            "",
            "| configuration | action acc | type acc | safety recall | evidence overlap |",
            "|---|---|---|---|---|",
        ]
        for name, action, types, safety, evidence in (summary_row(r) for r in results):
            table.append(f"| {name} | {action:.0%} | {types:.0%} | {safety:.0%} | {evidence:.0%} |")
        sections.insert(0, "\n".join(table))

    report = "# Evaluation report\n\n" + "\n\n".join(sections) + "\n"
    print("\n" + report)

    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(report, encoding="utf-8")
        print(f"Wrote {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
