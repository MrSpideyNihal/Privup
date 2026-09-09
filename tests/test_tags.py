"""Rule-set loading, validation, and the shipped rule sets themselves."""

from __future__ import annotations

import json

import pytest

from core.models import Severity
from core.tags import (
	RULESET_DIR,
	RuleSetError,
	Scope,
	UnknownTagSetError,
	available_tag_sets,
	describe_tag_sets,
	get_tag_set,
	load_rule_set,
	parse_rule_set,
	register_tag_set,
)
from core.tags.dla_directory import IMPLEMENTED, lookup
from core.tags.rules import NumericCheck


def minimal_rule(**overrides):
	rule = {
		"id": "test.rule",
		"category": "testing",
		"severity": "medium",
		"reason": "A thing happened.",
		"patterns": ["\\bthing\\b"],
	}
	rule.update(overrides)
	return rule


def minimal_set(**overrides):
	data = {"name": "test_set", "description": "d", "rules": [minimal_rule()]}
	data.update(overrides)
	return data


class TestDiscovery:
	def test_both_shipped_rule_sets_are_found(self):
		assert set(available_tag_sets()) >= {"generic", "loan_app"}

	def test_discovery_is_by_globbing_not_by_a_hardcoded_list(self):
		"""Adding a rule set must mean adding a file, nothing else."""
		on_disk = {json.loads(p.read_text(encoding="utf-8"))["name"] for p in RULESET_DIR.glob("*.json")}
		assert on_disk <= set(available_tag_sets())

	def test_describe_reports_a_rule_count(self):
		described = {name: count for name, _, count in describe_tag_sets()}
		assert described["loan_app"] > 5
		assert described["generic"] > 5

	def test_unknown_rule_set_names_the_ones_that_exist(self):
		with pytest.raises(UnknownTagSetError) as caught:
			get_tag_set("nope")
		assert "loan_app" in str(caught.value)

	def test_a_rule_set_can_be_registered_from_python(self):
		register_tag_set(minimal_set(name="registered_test"))
		assert get_tag_set("registered_test").name == "registered_test"


class TestValidation:
	@pytest.mark.parametrize("bad,message", [
		({"id": "", "category": "c", "severity": "low", "reason": "r", "patterns": ["x"]}, "id"),
		(minimal_rule(severity="catastrophic"), "severity"),
		(minimal_rule(patterns=[]), "patterns"),
		(minimal_rule(patterns=["(unclosed"]), "bad regex"),
		(minimal_rule(category=""), "category"),
		(minimal_rule(scope="sideways"), "scope"),
	])
	def test_a_malformed_rule_is_rejected_with_a_useful_message(self, bad, message):
		with pytest.raises(RuleSetError, match=message):
			parse_rule_set({"name": "t", "rules": [bad]}, source="t.json")

	def test_hedges_without_hedge_wording_are_rejected(self):
		"""A hedged match with nothing to report is a silent dropped finding."""
		with pytest.raises(RuleSetError, match="hedge_severity"):
			parse_rule_set(
				{"name": "t", "rules": [minimal_rule(hedges=["\\bideally\\b"])]},
				source="t.json",
			)

	def test_duplicate_rule_ids_are_rejected(self):
		with pytest.raises(RuleSetError, match="duplicate"):
			parse_rule_set({"name": "t", "rules": [minimal_rule(), minimal_rule()]}, source="t.json")

	def test_a_rule_set_needs_a_name_and_rules(self):
		with pytest.raises(RuleSetError, match="name"):
			parse_rule_set({"rules": [minimal_rule()]}, source="t.json")
		with pytest.raises(RuleSetError, match="rules"):
			parse_rule_set({"name": "t", "rules": []}, source="t.json")

	def test_invalid_json_names_the_file(self, tmp_path):
		path = tmp_path / "broken.json"
		path.write_text("{not json", encoding="utf-8")
		with pytest.raises(RuleSetError, match="broken.json"):
			load_rule_set(path)

	@pytest.mark.parametrize("bad,message", [
		({"kind": "percent_weekly", "threshold": 1}, "kind"),
		({"kind": "percent_annual", "operator": "~=", "threshold": 1}, "operator"),
		({"kind": "percent_annual"}, "threshold"),
	])
	def test_malformed_numeric_checks_are_rejected(self, bad, message):
		with pytest.raises(RuleSetError, match=message):
			NumericCheck.from_dict(bad, where="t:r")

	def test_numeric_comparison_operators(self):
		assert NumericCheck("percent_annual", ">=", 24).holds(24)
		assert not NumericCheck("percent_annual", ">", 24).holds(24)
		assert NumericCheck("percent_annual", "<", 24).holds(23)


class TestShippedRuleSets:
	@pytest.mark.parametrize("name", ["generic", "loan_app"])
	def test_every_rule_is_usable(self, name):
		for rule in get_tag_set(name):
			assert rule.patterns, rule.rule_id
			assert rule.reason.strip(), rule.rule_id
			assert rule.category.strip(), rule.rule_id
			assert isinstance(rule.severity, Severity), rule.rule_id

	@pytest.mark.parametrize("name", ["generic", "loan_app"])
	def test_every_rule_explains_itself(self, name):
		"""A rule nobody can justify later is a rule nobody can maintain."""
		for rule in get_tag_set(name):
			assert rule.note.strip() or rule.reference, rule.rule_id

	def test_loan_app_cites_the_regulation(self):
		rule_set = get_tag_set("loan_app")
		assert "Digital Lending" in (rule_set.reference or "")
		permission_rules = [r for r in rule_set if r.category == "disallowed_permission"]
		assert permission_rules
		assert all("RBI" in (r.reference or "") for r in permission_rules)

	def test_loan_app_treats_disallowed_permissions_as_critical(self):
		"""Deny hinges on critical, so this is the rule set's whole point."""
		rules = [r for r in get_tag_set("loan_app") if r.category == "disallowed_permission"]
		assert any(r.severity is Severity.CRITICAL for r in rules)

	def test_loan_app_covers_the_resources_rbi_names(self):
		blob = json.dumps(
			json.loads((RULESET_DIR / "loan_app.json").read_text(encoding="utf-8"))
		).lower()
		for resource in ["contact", "call log", "sms", "media"]:
			assert resource in blob, resource

	def test_permission_rules_can_be_negated(self):
		"""Real policies mention permissions in order to disclaim them."""
		for rule in get_tag_set("loan_app"):
			if rule.category == "disallowed_permission":
				assert rule.negations, rule.rule_id

	def test_generic_covers_the_four_required_red_flags(self):
		categories = set(get_tag_set("generic").categories())
		assert {"data_retention", "third_party_sharing", "tracking_profiling", "consent"} <= categories

	def test_each_set_has_document_scoped_rules_for_what_is_missing(self):
		for name in ["generic", "loan_app"]:
			assert get_tag_set(name).absence_rules, name

	def test_clause_and_absence_rules_partition_the_set(self):
		for name in ["generic", "loan_app"]:
			rule_set = get_tag_set(name)
			assert len(rule_set.clause_rules) + len(rule_set.absence_rules) == len(rule_set)

	def test_scope_values_are_known(self):
		for name in ["generic", "loan_app"]:
			assert all(r.scope in Scope.ALL for r in get_tag_set(name))


class TestDlaDirectoryStub:
	def test_is_declared_as_a_stub(self):
		assert IMPLEMENTED is False

	def test_returns_none_meaning_not_checked(self):
		"""None must never be read as 'this lender is not in the directory'."""
		assert lookup("https://example.com") is None

	def test_the_loan_app_rule_set_declares_the_hook(self):
		hook = get_tag_set("loan_app").metadata["dla_directory"]
		assert hook["status"] == "stub"
		assert hook["hook"] == "core.tags.dla_directory.lookup"
