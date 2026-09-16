"""Rule matching, numeric extraction, and the real-text cases that shaped them.

The negation and hedging tests quote live policies verbatim. That is the
point: these behaviours were not designed in the abstract, they were forced by
what actual lenders write.
"""

from __future__ import annotations

import pytest

from core.analyzer import RuleAnalyzer, extract
from core.analyzer.numeric import DAYS_PER_YEAR
from core.models import Clause, Severity
from core.summarizer import SimpleSummarizer
from core.scraper import get_driver
from core.tags import get_tag_set, parse_rule_set
from tests.fixtures import load_text


def clauses_from(text: str) -> list[Clause]:
	return SimpleSummarizer().clean(get_driver("raw_text").fetch(text))


def findings_for(text: str, rule_set_name: str = "loan_app"):
	return RuleAnalyzer().classify(clauses_from(text), get_tag_set(rule_set_name), origin="test")


def rule_ids(findings) -> set[str]:
	return {f.rule_id for f in findings}


class TestNumericExtraction:
	def test_reads_an_annual_rate(self):
		match = extract("percent_annual", "Rate of Interest (%) | Up to 36% p.a.")
		assert match is not None and match.value == 36.0 and match.annualised == 36.0

	def test_annualises_a_daily_rate(self):
		"""The rule this module exists for. 0.2% a day is not a small number."""
		match = extract("percent_daily", "Daily charges of up to 0.2% of the overdue principal amount")
		assert match is not None
		assert match.annualised == pytest.approx(0.2 * DAYS_PER_YEAR)
		assert match.annualised > 70

	def test_annualises_a_monthly_rate(self):
		match = extract("percent_monthly", "Interest at 3% per month on outstanding dues")
		assert match is not None and match.annualised == pytest.approx(36.0)

	def test_reads_a_bare_percentage(self):
		match = extract("percent_any", "Processing fees | Up to 7% | Up to 7%")
		assert match is not None and match.value == 7.0

	def test_requires_a_period_marker_for_annual(self):
		assert extract("percent_annual", "We may charge 7% of the amount") is None

	def test_returns_none_when_there_is_no_figure(self):
		assert extract("percent_any", "We charge a processing fee.") is None

	def test_picks_the_worst_figure_present(self):
		match = extract("percent_annual", "Rates range from 12% p.a. to 36% p.a.")
		assert match is not None and match.value == 36.0

	def test_unknown_strategy_returns_none(self):
		assert extract("percent_hourly", "5% per hour") is None


class TestNegation:
	def test_a_denial_is_not_a_finding(self):
		"""Kissht's live policy. A keyword rule flags a lender that is
		compliant on exactly the point it is being flagged for."""
		text = (
			"We also do not access your mobile phone resources such as "
			"contact list, call logs, telephony Functions, etc."
		)
		assert "rbi.permission.contacts" not in rule_ids(findings_for(text))
		assert "rbi.permission.call_logs" not in rule_ids(findings_for(text))

	def test_the_same_sentence_without_the_denial_is_a_finding(self):
		text = (
			"We access your mobile phone resources such as "
			"contact list, call logs, telephony Functions, etc."
		)
		assert "rbi.permission.contacts" in rule_ids(findings_for(text))

	def test_desist_from_is_read_as_a_denial(self):
		text = "DLAs shall desist from accessing mobile phone resources like contact list and call logs."
		assert "rbi.permission.contacts" not in rule_ids(findings_for(text))

	def test_a_promise_not_to_sell_is_not_a_finding(self):
		"""Fibe: 'We do not sell, rent, lease your Personal Information to
		anybody and will never do so.'"""
		text = "We do not sell, rent, lease your Personal Information to anybody and will never do so."
		assert "gdpr.sharing.sale" not in rule_ids(findings_for(text, "generic"))

	def test_contact_details_are_not_a_contact_list(self):
		"""TrueBalance. A borrower's own phone number is not their phone book."""
		text = (
			"The e-mail address, contact details provided by you including the contact "
			"details linked to your KYCs may be used to intimate you the due date of payments."
		)
		assert "rbi.permission.contacts" not in rule_ids(findings_for(text))


class TestHedging:
	def test_a_hedged_promise_is_reported_at_reduced_severity(self):
		"""LazyPay. 'Ideally restrain' is neither a denial nor an admission,
		and both suppressing it and reporting it at full severity are wrong."""
		text = (
			"In accordance with applicable laws, we ideally restrain from accessing "
			"mobile phone resources like file and media, contact list, call logs, "
			"telephony functions, etc."
		)
		findings = {f.rule_id: f for f in findings_for(text)}
		contacts = findings["rbi.permission.contacts"]
		assert contacts.severity is Severity.HIGH
		assert contacts.severity < Severity.CRITICAL
		assert "tries" in contacts.reason
		assert contacts.metadata["hedged_by"]

	def test_an_unhedged_admission_stays_critical(self):
		text = "We access your contact list to assess your creditworthiness."
		findings = {f.rule_id: f for f in findings_for(text)}
		assert findings["rbi.permission.contacts"].severity is Severity.CRITICAL

	def test_an_outright_denial_beats_a_hedge(self):
		"""Negation is checked before hedging, so this is suppressed, not
		downgraded."""
		text = "We generally do not access your contact list at any time."
		assert "rbi.permission.contacts" not in rule_ids(findings_for(text))


class TestRequiresAndNumericGating:
	def test_requires_gates_a_broad_pattern(self):
		"""'SMS' alone is not a finding. Something must be done to it."""
		assert "rbi.permission.sms" not in rule_ids(findings_for("We will send you an SMS reminder."))

	def test_a_low_interest_rate_does_not_fire_the_high_interest_rule(self):
		assert "rbi.charges.interest_high" not in rule_ids(
			findings_for("Rate of Interest is 12% p.a. on all personal loans.")
		)

	def test_a_high_interest_rate_does_fire(self):
		findings = {f.rule_id: f for f in findings_for("Rate of Interest (%) Up to 36% p.a.")}
		assert "rbi.charges.interest_high" in findings
		assert "36" in findings["rbi.charges.interest_high"].reason

	def test_the_daily_penal_rate_is_reported_as_a_yearly_figure(self):
		"""Use case: a cost that looks small per day and is not per year."""
		findings = {f.rule_id: f for f in findings_for(
			"Penal Charges: Daily charges of up to 0.2% of the overdue principal amount."
		)}
		finding = findings["rbi.charges.penal_daily"]
		assert finding.severity is Severity.CRITICAL
		assert "73" in finding.reason


class TestDocumentAbsenceRules:
	def test_fires_when_the_document_never_mentions_opting_out(self):
		text = " ".join(["We collect your personal data and share it with partners."] * 6)
		assert "gdpr.optout.absent" in rule_ids(findings_for(text, "generic"))

	def test_stays_silent_when_the_document_does_mention_it(self):
		text = (
			"We collect your personal data and share it with partners. "
			"You may withdraw your consent at any time by writing to us. "
			"You can also request deletion of your personal data."
		)
		assert "gdpr.optout.absent" not in rule_ids(findings_for(text, "generic"))

	def test_does_not_fire_on_an_empty_document(self):
		"""'This policy never mentions X' is a claim about a policy, and
		there is no policy here to make it about."""
		findings = RuleAnalyzer().classify([], get_tag_set("generic"), origin="test")
		assert findings == []

	def test_an_absence_finding_is_marked_as_one(self):
		text = " ".join(["We collect your personal data and share it with partners."] * 6)
		absent = [f for f in findings_for(text, "generic") if f.rule_id == "gdpr.optout.absent"]
		assert absent[0].clause.index == -1
		assert absent[0].metadata["scope"] == "document_absent"


class TestDeduplication:
	def test_the_same_rule_and_sentence_is_reported_once(self):
		"""A schedule of charges has one column per loan tenure, so the same
		penal-rate sentence appears three times identically."""
		row = "Daily charges of up to 0.2% of the overdue principal amount."
		findings = findings_for(f"{row} {row} {row}")
		penal = [f for f in findings if f.rule_id == "rbi.charges.penal_daily"]
		assert len(penal) == 1

	def test_the_same_rule_on_different_sentences_is_kept(self):
		findings = findings_for(
			"We access your contact list for verification. "
			"We upload your contacts to our servers for credit scoring."
		)
		contacts = [f for f in findings if f.rule_id == "rbi.permission.contacts"]
		assert len(contacts) == 2


class TestFindingShape:
	def test_a_finding_carries_its_evidence_and_its_citation(self):
		finding = next(
			f for f in findings_for("We access your contact list.")
			if f.rule_id == "rbi.permission.contacts"
		)
		assert finding.clause.text
		assert finding.matched_text
		assert "RBI" in (finding.reference or "")
		assert finding.rule_set == "loan_app"

	def test_the_directory_hook_result_is_recorded_on_loan_app_findings(self):
		finding = next(
			f for f in findings_for("We access your contact list.")
			if f.rule_id == "rbi.permission.contacts"
		)
		assert "dla_directory" in finding.metadata
		assert finding.metadata["dla_directory"] is None

	def test_a_broken_hook_does_not_take_the_pipeline_down(self):
		"""A failed lookup is not evidence about a lender, and must not look
		like it is."""
		rule_set = parse_rule_set(
			{
				"name": "hooked",
				"metadata": {"dla_directory": {"hook": "nonexistent.module.lookup"}},
				"rules": [{
					"id": "h.r", "category": "c", "severity": "low",
					"reason": "r", "patterns": ["\\bcontact list\\b"],
				}],
			},
			source="t.json",
		)
		findings = RuleAnalyzer().classify(
			clauses_from("We access your contact list here."), rule_set, origin="x"
		)
		assert findings[0].metadata["dla_directory"] is None

	def test_an_unknown_placeholder_survives_as_written(self):
		"""A rule author's typo must not crash in front of a user."""
		rule_set = parse_rule_set(
			{"name": "t", "rules": [{
				"id": "t.r", "category": "c", "severity": "low",
				"reason": "A fee of {typo} applies.", "patterns": ["\\bfee\\b"],
			}]},
			source="t.json",
		)
		findings = RuleAnalyzer().classify(
			clauses_from("There is a fee for this service always."), rule_set, origin="x"
		)
		assert "{typo}" in findings[0].reason


class TestAgainstRealPolicies:
	def test_a_permissive_lender_is_caught(self):
		"""TrueBalance states it will 'access all your SMS'."""
		findings = RuleAnalyzer().classify(
			clauses_from(load_text("loan_permissive_truebalance.txt")),
			get_tag_set("loan_app"), origin="test",
		)
		assert any(f.severity is Severity.CRITICAL for f in findings)
		assert "rbi.permission.sms" in rule_ids(findings)

	def test_a_lenders_own_charge_schedule_is_read(self):
		findings = RuleAnalyzer().classify(
			clauses_from(load_text("loan_charges_kissht_tou.txt")),
			get_tag_set("loan_app"), origin="test",
		)
		found = rule_ids(findings)
		assert {"rbi.charges.interest_high", "rbi.charges.penal_daily",
				"rbi.charges.processing_fee"} <= found

	def test_a_minimal_service_produces_no_critical_findings(self):
		"""Signal, as a negative control. A rule set that fires on everything
		has told the user nothing."""
		findings = RuleAnalyzer().classify(
			clauses_from(load_text("generic_signal.txt")),
			get_tag_set("generic"), origin="test",
		)
		assert not [f for f in findings if f.severity is Severity.CRITICAL]

	def test_a_privacy_forward_vendor_scores_lower_than_a_lender(self):
		def worst(fixture, rule_set):
			findings = RuleAnalyzer().classify(
				clauses_from(load_text(fixture)), get_tag_set(rule_set), origin="t"
			)
			return max((f.severity for f in findings), default=Severity.INFO)

		assert worst("generic_mozilla.txt", "generic") < worst(
			"loan_permissive_truebalance.txt", "loan_app"
		)
