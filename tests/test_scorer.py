"""Verdict generation."""

from __future__ import annotations

import pytest

from core.models import Clause, Decision, Finding, Severity
from core.scorer import SEVERITY_WEIGHTS, Scorer


def finding(severity: Severity, reason: str = "Something happened.", index: int = 0, **kwargs) -> Finding:
	defaults = dict(
		rule_id=f"test.{severity.value}.{index}",
		rule_set="generic",
		category="testing",
		severity=severity,
		reason=reason,
		clause=Clause(text="A clause.", index=index),
	)
	defaults.update(kwargs)
	return Finding(**defaults)


def score(findings, clauses=10):
	return Scorer().score(findings, rule_set="generic", origin="test", clauses_analyzed=clauses)


class TestDecision:
	def test_no_findings_is_allow(self):
		verdict = score([])
		assert verdict.decision is Decision.ALLOW
		assert verdict.reasons == ()
		assert verdict.risk_score == 0.0

	@pytest.mark.parametrize("severity", [Severity.INFO, Severity.LOW, Severity.MEDIUM, Severity.HIGH])
	def test_anything_below_critical_is_a_warning(self, severity):
		assert score([finding(severity)]).decision is Decision.WARNING

	def test_a_critical_finding_denies(self):
		assert score([finding(Severity.CRITICAL)]).decision is Decision.DENY

	def test_one_critical_denies_even_among_mild_findings(self):
		verdict = score([finding(Severity.LOW, index=0), finding(Severity.CRITICAL, index=1)])
		assert verdict.decision is Decision.DENY

	def test_volume_alone_never_denies(self):
		"""Escalating on count would let a rule set with many weak rules
		out-vote one with few precise ones."""
		verdict = score([finding(Severity.HIGH, reason=f"r{i}", index=i) for i in range(12)])
		assert verdict.decision is Decision.WARNING

	def test_is_blocking_matches_the_decision(self):
		assert score([finding(Severity.CRITICAL)]).is_blocking is True
		assert score([finding(Severity.HIGH)]).is_blocking is False


class TestEmptyDocument:
	def test_nothing_read_is_a_warning_not_an_allow(self):
		"""A confident green light for a page nobody read would be the worst
		bug this project could ship."""
		verdict = score([], clauses=0)
		assert verdict.decision is Decision.WARNING
		assert verdict.metadata["empty_document"] is True

	def test_says_plainly_that_it_is_not_an_all_clear(self):
		verdict = score([], clauses=0)
		assert len(verdict.reasons) == 1
		assert "not an all-clear" in verdict.reasons[0]

	def test_a_document_that_was_read_and_was_clean_is_an_allow(self):
		verdict = score([], clauses=40)
		assert verdict.decision is Decision.ALLOW
		assert not verdict.metadata.get("empty_document")


class TestReasons:
	def test_worst_findings_come_first(self):
		verdict = score([
			finding(Severity.LOW, "low reason", index=0),
			finding(Severity.CRITICAL, "critical reason", index=1),
			finding(Severity.MEDIUM, "medium reason", index=2),
		])
		assert verdict.reasons[0] == "critical reason"
		assert verdict.reasons[-1] == "low reason"

	def test_findings_are_ordered_the_same_way_as_reasons(self):
		verdict = score([
			finding(Severity.LOW, "low reason", index=0),
			finding(Severity.CRITICAL, "critical reason", index=1),
		])
		assert [f.reason for f in verdict.findings] == list(verdict.reasons)

	def test_equal_severity_keeps_document_order(self):
		verdict = score([
			finding(Severity.HIGH, "second", index=5),
			finding(Severity.HIGH, "first", index=1),
		])
		assert verdict.reasons == ("first", "second")

	def test_identical_reasons_are_shown_once_but_evidence_is_kept(self):
		verdict = score([
			finding(Severity.HIGH, "same reason", index=0),
			finding(Severity.HIGH, "same reason", index=1),
		])
		assert verdict.reasons == ("same reason",)
		assert len(verdict.findings) == 2


class TestRiskScore:
	def test_is_derived_from_severity_weights(self):
		verdict = score([finding(Severity.MEDIUM)])
		assert verdict.risk_score == SEVERITY_WEIGHTS[Severity.MEDIUM]

	def test_is_capped_at_100(self):
		verdict = score([finding(Severity.CRITICAL, f"r{i}", index=i) for i in range(10)])
		assert verdict.risk_score == 100.0

	def test_a_worse_finding_scores_higher(self):
		assert score([finding(Severity.CRITICAL)]).risk_score > score([finding(Severity.LOW)]).risk_score

	def test_is_not_the_verdict(self):
		"""A high score with no critical finding is still a Warning."""
		verdict = score([finding(Severity.HIGH, f"r{i}", index=i) for i in range(6)])
		assert verdict.risk_score == 100.0
		assert verdict.decision is Decision.WARNING


class TestMetadata:
	def test_counts_findings_by_severity(self):
		verdict = score([
			finding(Severity.HIGH, "a", index=0),
			finding(Severity.HIGH, "b", index=1),
			finding(Severity.LOW, "c", index=2),
		])
		assert verdict.metadata["severity_counts"] == {"high": 2, "low": 1}
		assert verdict.metadata["worst_severity"] == "high"

	def test_lists_categories(self):
		verdict = score([
			finding(Severity.HIGH, "a", index=0, category="retention"),
			finding(Severity.LOW, "b", index=1, category="sharing"),
		])
		assert verdict.metadata["categories"] == ["retention", "sharing"]

	def test_carries_the_rule_set_and_clause_count(self):
		verdict = score([finding(Severity.LOW)], clauses=37)
		assert verdict.rule_set == "generic"
		assert verdict.clauses_analyzed == 37
