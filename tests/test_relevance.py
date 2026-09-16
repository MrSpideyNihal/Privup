"""Rule-set relevance: warn on a mismatch, never block one.

PrivUp does not police which rule set runs against which target. Someone
testing an edge case, or writing rules for an app that fits no category, is
doing something legitimate. But a confident Deny on the wrong grounds costs
the tool the only thing it has, which is trust. So: a notice alongside the
findings, and the findings unchanged.
"""

from __future__ import annotations

import pytest

from core.main import run
from core.models import Clause
from core.summarizer import SimpleSummarizer
from core.scraper import get_driver
from core.tags import get_tag_set, parse_rule_set
from core.tags.relevance import check_relevance
from tests.fixtures import load_text


def clauses(text: str) -> list[Clause]:
	return SimpleSummarizer().clean(get_driver("raw_text").fetch(text))


LOAN_APP = lambda: get_tag_set("loan_app")  # noqa: E731


class TestFitsTheDocument:
	@pytest.mark.parametrize("fixture", [
		"loan_permissive_truebalance.txt",
		"loan_compliant_kissht.txt",
		"loan_hedged_lazypay.txt",
		"loan_charges_kissht_tou.txt",
	])
	def test_real_lending_documents_are_recognised(self, fixture):
		result = check_relevance(clauses(load_text(fixture)), LOAN_APP())
		assert result.applies is True
		assert result.notice is None

	@pytest.mark.parametrize("fixture", ["generic_signal.txt", "generic_mozilla.txt"])
	def test_a_non_lending_document_gets_a_notice(self, fixture):
		result = check_relevance(clauses(load_text(fixture)), LOAN_APP())
		assert result.applies is False
		assert "may not apply well here" in result.notice

	def test_the_generic_rule_set_never_produces_a_notice(self):
		"""It is meant to apply to anything, so it declares no signals."""
		for fixture in ["generic_signal.txt", "loan_charges_kissht_tou.txt"]:
			result = check_relevance(clauses(load_text(fixture)), get_tag_set("generic"))
			assert result.applies is True

	def test_an_empty_document_gets_no_notice(self):
		"""The empty-document warning already covers this; piling a second
		notice on top would just be noise."""
		assert check_relevance([], LOAN_APP()).applies is True


class TestSignalPrecision:
	def test_ordinary_privacy_language_is_not_mistaken_for_lending(self):
		"""'legitimate interest', 'interest-based advertising' and 'credit
		card' appear all over ordinary policies, which is why bare 'interest'
		and bare 'credit' are excluded as signals."""
		text = (
			"We process data under our legitimate interest. We use interest-based "
			"advertising to personalise the ads you see. You may pay by credit card. "
			"We share data with third parties and retain it as long as necessary. "
		) * 6
		assert len(text.split()) >= 120
		assert check_relevance(clauses(text), LOAN_APP()).applies is False

	def test_genuine_credit_language_is_recognised(self):
		text = (
			"The borrower shall repay the loan in equal instalments. "
			"Rate of interest is 24% p.a. and we assess your creditworthiness "
			"before disbursement of the principal amount. "
		) * 6
		assert check_relevance(clauses(text), LOAN_APP()).applies is True

	def test_one_repeated_word_cannot_carry_the_decision(self):
		"""Distinct phrases are counted, not occurrences."""
		text = "This loan is a loan about a loan. " * 40
		result = check_relevance(clauses(text), LOAN_APP())
		assert result.matched == ["loan"]
		assert result.applies is False


class TestTooShortToJudge:
	"""A false notice trains people to ignore the real ones."""

	def test_a_short_paste_gets_no_notice(self):
		"""Pasting one clause out of a consent dialog is a normal thing to
		do, and one sentence lacking the word 'borrower' proves nothing."""
		text = "We access your contact list to assess creditworthiness."
		assert check_relevance(clauses(text), LOAN_APP()).applies is True

	def test_the_same_text_at_length_does_get_a_notice(self):
		text = (
			"We may collect your personal information when you register. "
			"We share it with our partners and retain it as long as necessary. "
		) * 8
		assert len(text.split()) >= 120
		assert check_relevance(clauses(text), LOAN_APP()).applies is False

	def test_the_floor_is_configurable(self):
		rule_set = parse_rule_set(
			{
				"name": "eager",
				"metadata": {"relevance": {
					"signals": ["zeta"], "min_signals": 1,
					"min_words": 0, "notice": "No zeta here.",
				}},
				"rules": [{
					"id": "e.r", "category": "c", "severity": "low",
					"reason": "r", "patterns": ["\\bthing\\b"],
				}],
			},
			source="t.json",
		)
		assert not check_relevance(clauses("A short sentence without it."), rule_set).applies


class TestConfiguration:
	def test_a_rule_set_without_a_relevance_block_always_applies(self):
		rule_set = parse_rule_set(
			{"name": "bare", "rules": [{
				"id": "b.r", "category": "c", "severity": "low",
				"reason": "r", "patterns": ["\\bthing\\b"],
			}]},
			source="t.json",
		)
		assert check_relevance(clauses("A thing happened here today."), rule_set).applies

	def test_the_threshold_is_declared_by_the_rule_set(self):
		rule_set = parse_rule_set(
			{
				"name": "picky",
				"metadata": {"relevance": {
					"signals": ["alpha", "beta", "gamma"],
					"min_signals": 2,
					"min_words": 0,
					"notice": "Not a match.",
				}},
				"rules": [{
					"id": "p.r", "category": "c", "severity": "low",
					"reason": "r", "patterns": ["\\bthing\\b"],
				}],
			},
			source="t.json",
		)
		assert check_relevance(clauses("alpha and beta appear in this sentence."), rule_set).applies
		assert not check_relevance(clauses("only alpha appears in this sentence."), rule_set).applies


class TestEndToEnd:
	def test_the_notice_rides_along_on_the_verdict(self):
		verdict = run("raw_text", load_text("generic_signal.txt"), "loan_app")
		assert verdict.metadata["relevance"]["applies"] is False
		assert verdict.metadata["relevance"]["notice"]

	def test_the_verdict_itself_is_not_softened(self):
		"""A notice explains a verdict. It must never quietly change one."""
		verdict = run("raw_text", load_text("generic_signal.txt"), "loan_app")
		assert verdict.findings
		assert verdict.decision.value == "deny"
		assert verdict.risk_score > 0

	def test_a_matching_document_carries_no_relevance_metadata(self):
		verdict = run("raw_text", load_text("loan_charges_kissht_tou.txt"), "loan_app")
		assert "relevance" not in verdict.metadata

	def test_the_notice_survives_json(self):
		verdict = run("raw_text", load_text("generic_mozilla.txt"), "loan_app")
		assert verdict.to_dict()["metadata"]["relevance"]["notice"]
