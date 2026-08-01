"""Scoring for the routing task.

Reported metrics mirror what the brief says is graded — action, message type,
evidence relevance, confidence calibration — plus a safety metric, because a
scam reaching `notify` is a qualitatively worse failure than a digest/notify
mix-up and should never be averaged away.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field

from data_loader import ACTIONS

# A scam or spam message that interrupts the user is a safety failure.
UNSAFE_TYPES = {"scam", "spam"}


@dataclass
class ClassReport:
    accuracy: float
    macro_f1: float
    per_class: dict[str, dict[str, float]]
    confusion: dict[tuple[str, str], int]

    def confusion_table(self, labels: list[str]) -> str:
        present = [l for l in labels if any(g == l or p == l for g, p in self.confusion)]
        width = max((len(l) for l in present), default=4) + 1
        header = "gold \\ pred".ljust(14) + "".join(l[:width - 1].rjust(width) for l in present)
        rows = [header]
        for gold in present:
            cells = "".join(str(self.confusion.get((gold, pred), 0)).rjust(width) for pred in present)
            rows.append(gold.ljust(14) + cells)
        return "\n".join(rows)


def score_labels(gold: list[str], pred: list[str]) -> ClassReport:
    """Accuracy, per-class precision/recall/F1, macro-F1 and a confusion map."""
    assert len(gold) == len(pred)
    confusion: dict[tuple[str, str], int] = Counter(zip(gold, pred))
    correct = sum(count for (g, p), count in confusion.items() if g == p)
    accuracy = correct / len(gold) if gold else 0.0

    per_class: dict[str, dict[str, float]] = {}
    for label in sorted(set(gold) | set(pred)):
        tp = confusion.get((label, label), 0)
        fp = sum(c for (g, p), c in confusion.items() if p == label and g != label)
        fn = sum(c for (g, p), c in confusion.items() if g == label and p != label)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        per_class[label] = {
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "support": float(sum(c for (g, _), c in confusion.items() if g == label)),
        }

    supported = [m["f1"] for label, m in per_class.items() if m["support"] > 0]
    macro_f1 = sum(supported) / len(supported) if supported else 0.0
    return ClassReport(accuracy=accuracy, macro_f1=macro_f1, per_class=per_class, confusion=dict(confusion))


@dataclass
class EvidenceReport:
    exact: float          # predicted set overlaps the gold set
    predicted_any: float  # fraction where something was proposed
    none_agreement: float # both agreed there was nothing useful
    n: int


def score_evidence(gold: list[str], pred: list[str]) -> EvidenceReport:
    """Compare evidence id sets.

    Exact-match against this dataset's samples understates quality: the sample
    file's gold ids were authored one-to-one with the samples, so a genuinely
    closer historical match counts as a miss. Read alongside the relevance
    proxy in the report.
    """
    hits = nones = proposed = 0
    for g, p in zip(gold, pred):
        gold_set = {x for x in g.split(";") if x and x != "none"}
        pred_set = {x for x in p.split(";") if x and x != "none"}
        if pred_set:
            proposed += 1
        if not gold_set and not pred_set:
            nones += 1
            hits += 1
        elif gold_set & pred_set:
            hits += 1
    n = len(gold)
    gold_none = sum(1 for g in gold if not {x for x in g.split(";") if x and x != "none"})
    return EvidenceReport(
        exact=hits / n if n else 0.0,
        predicted_any=proposed / n if n else 0.0,
        none_agreement=nones / gold_none if gold_none else 1.0,
        n=n,
    )


@dataclass
class CalibrationReport:
    ece: float
    mean_confidence: float
    accuracy: float
    bins: list[tuple[str, int, float, float]] = field(default_factory=list)

    @property
    def overconfidence(self) -> float:
        return self.mean_confidence - self.accuracy


def score_calibration(correct: list[bool], confidence: list[float], bin_count: int = 5) -> CalibrationReport:
    """Expected calibration error over equal-width confidence bins."""
    n = len(correct)
    if n == 0:
        return CalibrationReport(ece=0.0, mean_confidence=0.0, accuracy=0.0)

    buckets: dict[int, list[tuple[bool, float]]] = defaultdict(list)
    lo, hi = min(confidence), max(confidence)
    span = max(hi - lo, 1e-9)
    for is_correct, conf in zip(correct, confidence):
        index = min(bin_count - 1, int((conf - lo) / span * bin_count))
        buckets[index].append((is_correct, conf))

    ece = 0.0
    bins: list[tuple[str, int, float, float]] = []
    for index in sorted(buckets):
        items = buckets[index]
        acc = sum(1 for c, _ in items if c) / len(items)
        avg_conf = sum(c for _, c in items) / len(items)
        ece += len(items) / n * abs(acc - avg_conf)
        edge_lo = lo + span * index / bin_count
        edge_hi = lo + span * (index + 1) / bin_count
        bins.append((f"{edge_lo:.2f}-{edge_hi:.2f}", len(items), avg_conf, acc))

    return CalibrationReport(
        ece=ece,
        mean_confidence=sum(confidence) / n,
        accuracy=sum(1 for c in correct if c) / n,
        bins=bins,
    )


@dataclass
class SafetyReport:
    unsafe_total: int
    unsafe_muted: int
    unsafe_notified: int
    false_mutes: int  # gold notify that we suppressed — the opposite failure

    @property
    def recall(self) -> float:
        return self.unsafe_muted / self.unsafe_total if self.unsafe_total else 1.0


def score_safety(gold_actions: list[str], gold_types: list[str], pred_actions: list[str]) -> SafetyReport:
    """How reliably risky content is suppressed, and what it costs."""
    unsafe = [i for i, t in enumerate(gold_types) if t in UNSAFE_TYPES]
    return SafetyReport(
        unsafe_total=len(unsafe),
        unsafe_muted=sum(1 for i in unsafe if pred_actions[i] == "mute"),
        unsafe_notified=sum(1 for i in unsafe if pred_actions[i] == "notify"),
        false_mutes=sum(
            1 for i, g in enumerate(gold_actions) if g == "notify" and pred_actions[i] == "mute"
        ),
    )


def distribution(values: list[str]) -> str:
    counts = Counter(values)
    return ", ".join(f"{k}: {counts.get(k, 0)}" for k in ACTIONS)
