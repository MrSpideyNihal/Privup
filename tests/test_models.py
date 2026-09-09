"""Schemas: the contract every other stage depends on."""

from __future__ import annotations

import dataclasses
import json
from datetime import datetime, timezone

import pytest

from core.models import Clause, Decision, DriverResult, Finding, Severity, Verdict


def make_clause(index: int = 7, text: str = "We share your data with partners.") -> Clause:
	return Clause(text=text, index=index, heading="Disclosures", char_start=0, char_end=len(text))


def make_finding(severity: Severity = Severity.HIGH, **kwargs) -> Finding:
	defaults = dict(
		rule_id="test.rule",
		rule_set="generic",
		category="third_party_sharing",
		severity=severity,
		reason="Your data goes to third parties.",
		clause=make_clause(),
	)
	defaults.update(kwargs)
	return Finding(**defaults)


class TestSeverity:
	def test_orders_from_info_to_critical(self):
		ordered = sorted([Severity.CRITICAL, Severity.INFO, Severity.HIGH, Severity.LOW, Severity.MEDIUM])
		assert ordered == [
			Severity.INFO, Severity.LOW, Severity.MEDIUM, Severity.HIGH, Severity.CRITICAL
		]

	def test_comparisons(self):
		assert Severity.CRITICAL > Severity.HIGH
		assert Severity.LOW < Severity.MEDIUM
		assert Severity.HIGH >= Severity.HIGH
		assert max([Severity.LOW, Severity.CRITICAL, Severity.MEDIUM]) is Severity.CRITICAL

	def test_serializes_as_its_string_value(self):
		assert json.dumps({"s": Severity.HIGH.value}) == '{"s": "high"}'

	def test_comparison_with_other_types_is_not_implemented(self):
		with pytest.raises(TypeError):
			_ = Severity.HIGH < 3


class TestClause:
	def test_clause_id_is_derived_and_zero_padded(self):
		assert make_clause(index=7).clause_id == "c0007"
		assert make_clause(index=1234).clause_id == "c1234"

	def test_round_trips(self):
		clause = make_clause()
		assert Clause.from_dict(clause.to_dict()) == clause

	def test_clause_id_is_exported_for_consumers(self):
		assert make_clause(index=3).to_dict()["clause_id"] == "c0003"


class TestDriverResult:
	def test_is_empty_detects_whitespace_only(self):
		base = dict(origin="x", driver="raw_text")
		assert DriverResult(raw_text="   \n\t ", **base).is_empty
		assert not DriverResult(raw_text="policy", **base).is_empty

	def test_defaults_to_plain_text_and_now(self):
		result = DriverResult(raw_text="a", origin="x", driver="raw_text")
		assert result.content_type == "text/plain"
		assert result.fetched_at.tzinfo is timezone.utc

	def test_round_trips_through_json(self):
		result = DriverResult(
			raw_text="text", origin="https://x/p", driver="url",
			content_type="text/html", metadata={"status": 200},
		)
		assert DriverResult.from_dict(json.loads(json.dumps(result.to_dict()))) == result


class TestFinding:
	def test_embeds_its_clause_so_it_is_self_contained(self):
		finding = make_finding()
		assert finding.to_dict()["clause"]["text"] == finding.clause.text

	def test_round_trips_through_json(self):
		finding = make_finding(
			matched_text="third parties",
			reference="GDPR Art. 13(1)(e)",
			metadata={"android_permission": "READ_SMS"},
		)
		assert Finding.from_dict(json.loads(json.dumps(finding.to_dict()))) == finding


class TestVerdict:
	def test_coerces_lists_to_tuples_so_frozen_means_frozen(self):
		verdict = Verdict(
			decision=Decision.WARNING, rule_set="generic", origin="x",
			reasons=["a"], findings=[make_finding()],
		)
		assert isinstance(verdict.reasons, tuple)
		assert isinstance(verdict.findings, tuple)

	def test_is_immutable(self):
		verdict = Verdict(decision=Decision.ALLOW, rule_set="generic", origin="x")
		with pytest.raises(dataclasses.FrozenInstanceError):
			verdict.decision = Decision.DENY  # type: ignore[misc]

	def test_is_blocking_only_on_deny(self):
		for decision, blocking in [
			(Decision.ALLOW, False), (Decision.WARNING, False), (Decision.DENY, True)
		]:
			verdict = Verdict(decision=decision, rule_set="generic", origin="x")
			assert verdict.is_blocking is blocking

	def test_highest_severity_is_none_without_findings(self):
		assert Verdict(decision=Decision.ALLOW, rule_set="g", origin="x").highest_severity is None

	def test_highest_severity_picks_the_worst(self):
		verdict = Verdict(
			decision=Decision.DENY, rule_set="g", origin="x",
			findings=[make_finding(Severity.LOW), make_finding(Severity.CRITICAL),
					  make_finding(Severity.MEDIUM)],
		)
		assert verdict.highest_severity is Severity.CRITICAL

	def test_groups_findings_by_category(self):
		verdict = Verdict(
			decision=Decision.WARNING, rule_set="g", origin="x",
			findings=[make_finding(category="a"), make_finding(category="b"),
					  make_finding(category="a")],
		)
		grouped = verdict.findings_by_category()
		assert sorted(grouped) == ["a", "b"]
		assert len(grouped["a"]) == 2

	def test_round_trips_through_json(self):
		verdict = Verdict(
			decision=Decision.DENY, rule_set="loan_app", origin="raw_text",
			reasons=["Reads your contacts."], findings=[make_finding(Severity.CRITICAL)],
			risk_score=92.0, clauses_analyzed=41, metadata={"worst_severity": "critical"},
		)
		assert Verdict.from_dict(json.loads(json.dumps(verdict.to_dict()))) == verdict

	def test_with_reasons_translates_without_touching_the_original(self):
		original = Verdict(
			decision=Decision.DENY, rule_set="loan_app", origin="x",
			reasons=["Reads your contacts."], findings=[make_finding()],
		)
		translated = original.with_reasons(["Aapke contacts padhta hai."], "hi")

		assert translated.language == "hi"
		assert translated.reasons == ("Aapke contacts padhta hai.",)
		assert original.language == "en"
		assert original.reasons == ("Reads your contacts.",)

	def test_translation_leaves_clause_text_in_its_source_language(self):
		"""A mistranslated reason is a bad explanation. A mistranslated clause
		would change what the user believes the policy says."""
		original = Verdict(
			decision=Decision.DENY, rule_set="loan_app", origin="x",
			reasons=["r"], findings=[make_finding()],
		)
		translated = original.with_reasons(["translated"], "hi")
		assert translated.findings[0].clause.text == original.findings[0].clause.text

	def test_parses_an_iso_timestamp_from_a_dict(self):
		when = datetime(2026, 9, 9, 12, 0, tzinfo=timezone.utc)
		verdict = Verdict.from_dict({
			"decision": "allow", "rule_set": "generic", "origin": "x",
			"analyzed_at": when.isoformat(),
		})
		assert verdict.analyzed_at == when

	def test_tolerates_a_minimal_dict(self):
		verdict = Verdict.from_dict({"decision": "allow", "rule_set": "generic", "origin": "x"})
		assert verdict.findings == () and verdict.reasons == ()
