"""Composing classifiers, and what happens when they disagree."""

from __future__ import annotations

import pytest

from core.analyzer import Classifier, CompositeAnalyzer, RuleAnalyzer, default_analyzer
from core.main import run
from core.models import Clause, Finding, Severity
from core.tags import get_tag_set

RETENTION = "We keep some data until you delete your Google Account and never before."
CONTACTS = "We access your contact list to assess creditworthiness before disbursement."


def clause(text: str, index: int = 0) -> Clause:
	return Clause(text=text, index=index)


class Stub(Classifier):
	"""Stands in for a model-backed classifier: a judgement, not a match."""

	def __init__(self, name, category, confidence=0.7, severity=Severity.MEDIUM, available=True):
		self.name = name
		self._category = category
		self._confidence = confidence
		self._severity = severity
		self._available = available
		self.calls = 0

	@property
	def available(self) -> bool:
		return self._available

	def classify(self, clauses, rule_set, origin=""):
		self.calls += 1
		return [
			Finding(
				rule_id=f"{self.name}.rule",
				rule_set=rule_set.name,
				category=self._category,
				severity=self._severity,
				reason=f"{self.name} thinks so.",
				clause=c,
				confidence=self._confidence,
			)
			for c in clauses
		]


def run_composite(classifiers, text, rule_set="generic"):
	return CompositeAnalyzer(classifiers).classify(
		[clause(text)], get_tag_set(rule_set), origin="test"
	)


class TestComposition:
	def test_needs_at_least_one_classifier(self):
		with pytest.raises(ValueError):
			CompositeAnalyzer([])

	def test_default_is_the_rule_matcher_alone(self):
		assert isinstance(default_analyzer(), RuleAnalyzer)

	def test_default_composes_when_given_extras(self):
		assert isinstance(default_analyzer([Stub("m", "x")]), CompositeAnalyzer)

	def test_findings_from_every_classifier_are_kept(self):
		findings = run_composite(
			[RuleAnalyzer(), Stub("model", "cross_border_transfer")], RETENTION
		)
		assert {"data_retention", "cross_border_transfer"} <= {f.category for f in findings}

	def test_each_finding_records_what_produced_it(self):
		findings = run_composite([RuleAnalyzer(), Stub("model", "security")], RETENTION)
		producers = {f.metadata.get("classifier") for f in findings}
		assert producers == {"rules", "model"}

	def test_an_unavailable_classifier_is_skipped_not_fatal(self):
		"""The rule-only path must keep working when an optional model file
		or dependency is missing."""
		absent = Stub("missing_model", "security", available=False)
		findings = run_composite([RuleAnalyzer(), absent], RETENTION)
		assert absent.calls == 0
		assert findings

	def test_a_composite_is_available_if_any_member_is(self):
		assert CompositeAnalyzer([Stub("a", "x", available=False), Stub("b", "y")]).available
		assert not CompositeAnalyzer([Stub("a", "x", available=False)]).available


class TestReconcilingOverlap:
	"""One finding per clause per category. Telling a user the same thing
	twice in different words reads as noise."""

	def test_the_same_clause_and_category_is_reported_once(self):
		findings = run_composite(
			[Stub("a", "data_retention", 0.6), Stub("b", "data_retention", 0.9)], RETENTION
		)
		retention = [f for f in findings if f.category == "data_retention"]
		assert len(retention) == 1

	def test_the_surer_classifier_wins(self):
		findings = run_composite(
			[Stub("unsure", "security", 0.4), Stub("sure", "security", 0.95)], RETENTION
		)
		assert findings[0].metadata["classifier"] == "sure"

	def test_a_citable_rule_wins_when_everything_else_ties(self):
		"""Dead even on confidence and severity, keep the finding a reader
		can check."""
		findings = run_composite(
			[RuleAnalyzer(), Stub("model", "data_retention", confidence=1.0, severity=Severity.LOW)],
			RETENTION,
		)
		retention = next(f for f in findings if f.category == "data_retention")
		assert retention.metadata["classifier"] == "rules"
		assert retention.reference

	def test_a_more_severe_reading_wins_at_equal_confidence(self):
		"""The scorer decides the verdict from the worst finding, so quietly
		keeping the milder reading could turn a Warning into an Allow."""
		findings = run_composite(
			[RuleAnalyzer(), Stub("model", "data_retention", confidence=1.0, severity=Severity.HIGH)],
			RETENTION,
		)
		retention = next(f for f in findings if f.category == "data_retention")
		assert retention.severity is Severity.HIGH

	def test_confidence_outranks_severity(self):
		"""Otherwise a barely-confident model shouts down a certain rule just
		by calling something critical."""
		findings = run_composite(
			[Stub("sure", "security", 0.95, Severity.LOW),
			 Stub("guessing", "security", 0.30, Severity.CRITICAL)],
			RETENTION,
		)
		assert findings[0].metadata["classifier"] == "sure"

	def test_the_loser_is_recorded_rather_than_discarded(self):
		"""An evaluation run still needs to see that both fired."""
		findings = run_composite(
			[RuleAnalyzer(), Stub("model", "data_retention", 0.5)], RETENTION
		)
		retention = next(f for f in findings if f.category == "data_retention")
		assert any("model" in entry for entry in retention.metadata["also_flagged_by"])

	def test_different_clauses_are_not_merged(self):
		findings = CompositeAnalyzer([Stub("m", "security")]).classify(
			[clause("first clause here", 0), clause("second clause here", 1)],
			get_tag_set("generic"), origin="t",
		)
		assert len(findings) == 2


class TestPipelineIntegration:
	def test_the_pipeline_still_defaults_to_rules_only(self):
		from_default = run("raw_text", CONTACTS, "loan_app")
		from_explicit = run("raw_text", CONTACTS, "loan_app", analyzer=RuleAnalyzer())
		assert from_default.to_dict()["findings"] == from_explicit.to_dict()["findings"]

	def test_an_extra_classifier_reaches_the_verdict_unchanged_downstream(self):
		"""The seam's whole claim: scorer, cli and ui cannot tell the
		difference."""
		verdict = run(
			"raw_text", RETENTION, "generic",
			analyzer=CompositeAnalyzer([RuleAnalyzer(), Stub("model", "security", severity=Severity.HIGH)]),
		)
		assert "security" in {f.category for f in verdict.findings}
		assert verdict.decision.value in {"allow", "warning", "deny"}
		assert verdict.reasons

	def test_a_critical_model_finding_can_deny(self):
		verdict = run(
			"raw_text", "Some ordinary sentence about nothing in particular here.", "generic",
			analyzer=CompositeAnalyzer([RuleAnalyzer(), Stub("model", "security", 0.9, Severity.CRITICAL)]),
		)
		assert verdict.decision.value == "deny"

	def test_confidence_survives_to_the_verdict(self):
		"""A reader needs to be able to tell a match from a judgement."""
		verdict = run(
			"raw_text", RETENTION, "generic",
			analyzer=CompositeAnalyzer([RuleAnalyzer(), Stub("model", "security", 0.62)]),
		)
		model_finding = next(f for f in verdict.findings if f.category == "security")
		assert model_finding.confidence == pytest.approx(0.62)
