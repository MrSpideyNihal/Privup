"""Showing a verdict in the user's language.

Two kinds of test. Catalog tests keep every translation complete and
consistent with the rule sets, so adding a rule in English tells you exactly
which languages now need a line. Behaviour tests check that translation
changes what the user reads and nothing else: never the decision, never the
policy text.
"""

from __future__ import annotations

import json
import re

import pytest

from core.main import run
from core.models import Decision
from core.scorer.scorer import Scorer, generate_headline
from core.tags import available_tag_sets, get_tag_set
from core.translator import (
	LOCALE_DIR,
	SOURCE_LANGUAGE,
	UnknownLanguageError,
	available_languages,
	get_catalog,
	message,
	translate,
)
from tests.fixtures import load_text

_PLACEHOLDER = re.compile(r"\{(\w+)\}")

TRANSLATED = [code for code in available_languages() if code != SOURCE_LANGUAGE]

LENDER_TEXT = (
	"We access your contact list and call logs to assess creditworthiness. "
	"Daily charges of up to 0.2% of the overdue principal amount apply to your loan. "
	"Rate of Interest Up to 36% p.a. for every borrower."
)


def placeholders(text: str) -> set[str]:
	return set(_PLACEHOLDER.findall(text))


def all_rules():
	for name in available_tag_sets():
		for rule in get_tag_set(name):
			yield name, rule


# ---------------------------------------------------------------- catalogs


class TestCatalogs:
	def test_hindi_and_marathi_ship(self):
		assert {"en", "hi", "mr"} <= set(available_languages())

	def test_every_locale_file_is_valid_json_named_for_its_language(self):
		for path in LOCALE_DIR.glob("*.json"):
			data = json.loads(path.read_text(encoding="utf-8"))
			assert data["language"] == path.stem

	@pytest.mark.parametrize("code", TRANSLATED)
	def test_has_every_message_and_no_strays(self, code):
		source = set(get_catalog(SOURCE_LANGUAGE).messages)
		target = set(get_catalog(code).messages)
		assert source - target == set(), f"{code} is missing messages"
		assert target - source == set(), f"{code} has messages en.json does not define"

	@pytest.mark.parametrize("code", TRANSLATED)
	def test_has_every_rule(self, code):
		catalog = get_catalog(code)
		missing = []
		for name, rule in all_rules():
			entry = catalog.rules.get(rule.rule_id) or {}
			needed = ["label", "reason"] + (["hedge_reason"] if rule.hedge_reason else [])
			missing += [f"{rule.rule_id}.{key}" for key in needed if not entry.get(key)]
		assert missing == [], f"{code} needs translations for: {missing}"

	@pytest.mark.parametrize("code", TRANSLATED)
	def test_has_no_rules_that_no_longer_exist(self, code):
		known = {rule.rule_id for _, rule in all_rules()}
		assert set(get_catalog(code).rules) - known == set()

	@pytest.mark.parametrize("code", TRANSLATED)
	def test_rule_placeholders_survive_translation(self, code):
		"""A dropped {annualised} would hide the one number that matters."""
		catalog = get_catalog(code)
		for _, rule in all_rules():
			for variant, english in (("reason", rule.reason), ("hedge_reason", rule.hedge_reason)):
				translated = catalog.rule_text(rule.rule_id, variant)
				if english and translated:
					assert placeholders(translated) == placeholders(english), (
						f"{code} {rule.rule_id}.{variant}"
					)

	@pytest.mark.parametrize("code", TRANSLATED)
	def test_message_placeholders_survive_translation(self, code):
		source = get_catalog(SOURCE_LANGUAGE).messages
		for key, translated in get_catalog(code).messages.items():
			assert placeholders(translated) == placeholders(source[key]), f"{code} {key}"

	@pytest.mark.parametrize("code", TRANSLATED)
	def test_every_relevance_notice_is_translated(self, code):
		for name in available_tag_sets():
			if (get_tag_set(name).metadata.get("relevance") or {}).get("notice"):
				assert (get_catalog(code).rule_sets.get(name) or {}).get("relevance_notice")


class TestEnglishMatchesTheScorer:
	"""en.json restates strings the scorer writes. If they drift, a front end
	reading the catalog and one reading the verdict say different things."""

	def test_empty_document(self):
		verdict = Scorer().score([], "generic", "x", clauses_analyzed=0)
		assert verdict.reasons == (message("en", "verdict.empty_document"),)
		assert verdict.metadata["headline"] == message("en", "headline.empty_document")

	def test_clean_document(self):
		verdict = Scorer().score([], "generic", "x", clauses_analyzed=5)
		assert verdict.metadata["headline"] == message("en", "headline.clean")


# ---------------------------------------------------------------- behaviour


@pytest.fixture
def lender_en():
	return run("raw_text", LENDER_TEXT, "loan_app")


class TestTranslate:
	def test_english_is_returned_unchanged(self, lender_en):
		assert translate(lender_en, "en") is lender_en

	def test_unknown_language_is_refused(self, lender_en):
		with pytest.raises(UnknownLanguageError):
			translate(lender_en, "xx")

	@pytest.mark.parametrize("code", TRANSLATED)
	def test_never_changes_the_decision_or_the_evidence(self, lender_en, code):
		translated = translate(lender_en, code)

		assert translated.decision is lender_en.decision
		assert translated.risk_score == lender_en.risk_score
		assert translated.language == code
		for before, after in zip(lender_en.findings, translated.findings):
			assert after.rule_id == before.rule_id
			assert after.severity is before.severity
			assert after.clause == before.clause
			assert after.matched_text == before.matched_text
			assert after.reference == before.reference
			assert after.metadata["source_reason"] == before.reason

	def test_reasons_come_from_the_catalog(self, lender_en):
		translated = translate(lender_en, "mr")
		contacts = next(f for f in translated.findings if f.rule_id == "rbi.permission.contacts")
		assert contacts.reason == get_catalog("mr").rule_text("rbi.permission.contacts", "reason")
		assert contacts.reason in translated.reasons
		assert translated.metadata["translation"] == {
			"language": "mr", "reviewed": False, "complete": True, "fallback": [],
		}

	def test_numbers_are_the_same_numbers(self):
		"""0.2% a day is about 73% a year in every language."""
		english = run("raw_text", load_text("loan_charges_kissht_tou.txt"), "loan_app")
		penal = next(f for f in english.findings if f.rule_id == "rbi.charges.penal_daily")
		figure = str(penal.metadata["reason_values"]["annualised"]).removesuffix(".0")
		assert f"{figure}%" in penal.reason

		for code in TRANSLATED:
			translated = translate(english, code)
			same = next(f for f in translated.findings if f.rule_id == "rbi.charges.penal_daily")
			assert f"{figure}%" in same.reason
			assert "{" not in same.reason

	def test_a_hedged_finding_uses_the_hedged_wording(self):
		english = run("raw_text", load_text("loan_hedged_lazypay.txt"), "loan_app")
		hedged = [f for f in english.findings if f.metadata.get("reason_variant") == "hedge_reason"]
		assert hedged, "fixture no longer produces a hedged finding"

		translated = translate(english, "hi")
		for before in hedged:
			after = next(f for f in translated.findings if f.clause == before.clause and f.rule_id == before.rule_id)
			assert after.reason == get_catalog("hi").rule_text(before.rule_id, "hedge_reason")

	def test_a_rule_with_no_translation_stays_in_english_and_is_reported(self, lender_en):
		catalog = get_catalog("mr")
		saved = dict(catalog.rules)
		try:
			catalog.rules.pop("rbi.permission.contacts")  # type: ignore[attr-defined]
			translated = translate(lender_en, "mr")
		finally:
			catalog.rules.clear()  # type: ignore[attr-defined]
			catalog.rules.update(saved)  # type: ignore[attr-defined]

		contacts = next(f for f in translated.findings if f.rule_id == "rbi.permission.contacts")
		english = next(f for f in lender_en.findings if f.rule_id == "rbi.permission.contacts")
		assert contacts.reason == english.reason
		assert translated.metadata["translation"]["complete"] is False
		assert "rules.rbi.permission.contacts.reason" in translated.metadata["translation"]["fallback"]
		# One missing label keeps the whole headline English rather than mixed.
		assert translated.metadata["headline"] == lender_en.metadata["headline"]

	def test_empty_document(self):
		english = Scorer().score([], "generic", "x", clauses_analyzed=0)
		translated = translate(english, "mr")
		assert translated.decision is Decision.WARNING
		assert translated.reasons == (message("mr", "verdict.empty_document"),)
		assert translated.metadata["headline"] == message("mr", "headline.empty_document")

	def test_relevance_notice_is_translated(self):
		english = run("raw_text", load_text("generic_signal.txt"), "loan_app")
		assert english.metadata.get("relevance"), "fixture should not look like a lender"
		translated = translate(english, "mr")
		assert translated.metadata["relevance"]["notice"] == (
			get_catalog("mr").rule_sets["loan_app"]["relevance_notice"]
		)
		assert translated.metadata["relevance"]["matched_signals"] == (
			english.metadata["relevance"]["matched_signals"]
		)


class TestHeadline:
	def test_english_templates_reproduce_the_scorer(self, lender_en):
		"""The English templates are the scorer's grammar, written as data."""
		assert lender_en.metadata["headline"] == generate_headline(list(lender_en.findings))

	@pytest.mark.parametrize("code", TRANSLATED)
	def test_is_built_from_translated_labels(self, lender_en, code):
		translated = translate(lender_en, code)
		headline = translated.metadata["headline"]
		catalog = get_catalog(code)
		first = catalog.rule_text(lender_en.findings[0].rule_id, "label")
		assert first in headline
		assert not re.search(r"[A-Za-z]{4,}", headline.replace("RBI", "").replace("SMS", "")), headline

	def test_counts_topics_past_three(self, lender_en):
		labels = {catalog_label for catalog_label in (
			get_catalog("mr").rule_text(f.rule_id, "label") for f in lender_en.findings
		)}
		translated = translate(lender_en, "mr")
		if len(labels) > 3:
			assert f"+आणखी {len(labels) - 3}" in translated.metadata["headline"]


class TestPipeline:
	@pytest.mark.parametrize("code", TRANSLATED)
	def test_run_takes_a_language(self, code):
		english = run("raw_text", LENDER_TEXT, "loan_app")
		translated = run("raw_text", LENDER_TEXT, "loan_app", language=code)
		assert translated.decision is english.decision
		assert translated.language == code
		assert translated.reasons != english.reasons

	def test_run_refuses_an_unknown_language_before_doing_any_work(self):
		with pytest.raises(UnknownLanguageError):
			run("raw_text", LENDER_TEXT, "loan_app", language="xx")

	def test_round_trips_through_json(self):
		translated = run("raw_text", LENDER_TEXT, "loan_app", language="mr")
		from core.models import Verdict
		assert Verdict.from_dict(json.loads(json.dumps(translated.to_dict()))) == translated


class TestMessage:
	def test_falls_back_to_english_then_to_the_key(self):
		assert message("mr", "ui.risk") == "धोका"
		assert message("xx", "ui.risk") == "Risk"
		assert message("mr", "no.such.key") == "no.such.key"

	def test_fills_values(self):
		assert message("en", "ui.findings.many", n=4) == "4 findings"


class TestCli:
	def test_lang_flag(self, capsys):
		from cli.main import EXIT_DENY, main
		status = main(["scan", LENDER_TEXT, "--tags", "loan_app", "--lang", "mr"])
		out = capsys.readouterr().out
		assert status == EXIT_DENY
		assert message("mr", "decision.deny") in out
		assert "फोनमधील संपर्क" in out

	def test_list_languages(self, capsys):
		from cli.main import EXIT_OK, main
		assert main(["--list-languages"]) == EXIT_OK
		out = capsys.readouterr().out
		assert "मराठी" in out and "हिन्दी" in out
