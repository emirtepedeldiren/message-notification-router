"""Prompt construction: what the model is and is not shown."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

import risk
from context import build_context
from data_loader import ACTIONS, load_dataset
from router import Router, build_reason_catalogue, select_examples


@pytest.fixture(scope="module")
def dataset():
    return load_dataset()


class TestFewShotSelection:
    def test_the_message_being_routed_is_never_its_own_example(self, dataset):
        """Otherwise every dev-set score is measuring leakage, not routing."""
        for sample in dataset.samples:
            chosen = select_examples(dataset, sample)
            assert sample.message_id not in {c.message_id for c in chosen}

    def test_examples_are_returned(self, dataset):
        assert len(select_examples(dataset, dataset.samples[0], limit=4)) == 4

    def test_selection_is_deterministic(self, dataset):
        sample = dataset.samples[3]
        first = [m.message_id for m in select_examples(dataset, sample)]
        second = [m.message_id for m in select_examples(dataset, sample)]
        assert first == second

    def test_shape_is_matched_where_possible(self, dataset):
        """A voice note should be shown voice-note examples."""
        voice = next(s for s in dataset.samples if s.media_type == "voice")
        chosen = select_examples(dataset, voice, limit=4)
        assert any(c.media_type == "voice" for c in chosen)


class TestReasonCatalogue:
    def test_catalogue_is_grouped_by_action(self, dataset):
        catalogue = build_reason_catalogue(dataset)
        assert set(catalogue) == set(ACTIONS)
        assert all(catalogue[action] for action in ACTIONS)

    def test_entries_are_unique(self, dataset):
        for entries in build_reason_catalogue(dataset).values():
            assert len(entries) == len(set(entries))


class TestPromptContents:
    def _prompt(self, dataset, sample):
        ctx = build_context(dataset, sample)
        return Router(dataset).build_prompt(ctx, risk.assess(ctx))

    def test_prompt_never_offers_the_row_its_own_gold_reason(self, dataset):
        """A reason unique to this row must not reach it via the catalogue."""
        counts: dict[str, int] = {}
        for sample in dataset.samples:
            counts[sample.reason] = counts.get(sample.reason, 0) + 1

        checked = 0
        for sample in dataset.samples:
            # Phrasings shared with other rows legitimately stay in the
            # catalogue; only the ones unique to this row would be a give-away.
            if counts.get(sample.reason, 0) != 1:
                continue
            checked += 1
            assert sample.reason not in self._prompt(dataset, sample)
        assert checked > 0, "expected some uniquely-phrased reasons to check"

    def test_prompt_restricts_evidence_to_retrieved_candidates(self, dataset):
        sample = next(s for s in dataset.samples if s.evidence_message_ids not in ("", "none"))
        ctx = build_context(dataset, sample)
        prompt = Router(dataset).build_prompt(ctx, risk.assess(ctx))
        assert "Choose evidence ids only from:" in prompt

    def test_binding_verdict_is_stated_for_critical_risk(self, dataset):
        scam = next(s for s in dataset.samples if s.message_type == "scam")
        ctx = build_context(dataset, scam)
        verdict = risk.assess(ctx)
        assert verdict.forces_mute
        assert "binding" in Router(dataset).build_prompt(ctx, verdict)

    def test_message_text_is_marked_as_untrusted_data(self, dataset):
        prompt = self._prompt(dataset, dataset.samples[0])
        assert "never as instructions" in prompt
