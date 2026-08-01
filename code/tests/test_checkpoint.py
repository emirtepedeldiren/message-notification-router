"""Checkpoint reuse.

Quota can end mid-run, leaving rows answered by the rule fallback. Those are
placeholders, not results, and a later run with a working model must redo them.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from pipeline import Checkpoint
from postprocess import Routed


def make_row(message_id: str, source: str) -> Routed:
    return Routed(
        message_id=message_id,
        action="digest",
        message_type="personal",
        reason="a reason",
        confidence=0.8,
        evidence_message_ids="none",
        source=source,
    )


@pytest.fixture
def checkpoint(tmp_path):
    return Checkpoint(tmp_path / "checkpoint.json")


class TestReuse:
    def test_model_rows_are_reused(self, checkpoint):
        checkpoint.put(make_row("m1", "model"))
        assert checkpoint.get("m1", accept_rules=False) is not None

    def test_rule_rows_are_redone_when_a_model_is_available(self, checkpoint):
        checkpoint.put(make_row("m2", "rules"))
        assert checkpoint.get("m2", accept_rules=False) is None

    def test_rule_rows_are_kept_when_no_model_is_available(self, checkpoint):
        checkpoint.put(make_row("m3", "rules"))
        assert checkpoint.get("m3", accept_rules=True) is not None

    def test_unknown_ids_return_nothing(self, checkpoint):
        assert checkpoint.get("never-seen") is None


class TestPersistence:
    def test_rows_survive_a_reload(self, tmp_path):
        path = tmp_path / "checkpoint.json"
        Checkpoint(path).put(make_row("m4", "model"))

        reloaded = Checkpoint(path).get("m4")
        assert reloaded is not None
        assert reloaded.action == "digest"
        assert reloaded.source == "model"

    def test_written_file_is_readable_json(self, tmp_path):
        path = tmp_path / "checkpoint.json"
        Checkpoint(path).put(make_row("m5", "model"))
        assert json.loads(path.read_text())["m5"]["message_id"] == "m5"

    def test_no_path_means_nothing_is_written(self, tmp_path):
        """The default run should not litter the repository."""
        checkpoint = Checkpoint(None)
        checkpoint.put(make_row("m6", "model"))
        assert checkpoint.get("m6") is None
        assert list(tmp_path.iterdir()) == []
