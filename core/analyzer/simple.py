"""Deterministic rule matching. No model, no scoring, no verdict.

The matching order is the interesting part, and it is the order it is in
because of what real policies do.

	1. A pattern has to hit at all.
	2. Every ``requires`` pattern has to hit too. This is how a rule says
	   "the word SMS only counts when something is being done to it".
	3. A ``numeric`` check, if the rule has one, has to trip. A clause
	   quoting 12% interest does not fire a rule about expensive credit.
	4. If any ``negation`` hits, the match is dropped entirely. This is the
	   step that stops PrivUp flagging Kissht for the sentence "We also do
	   not access your mobile phone resources such as contact list, call
	   logs, telephony Functions".
	5. If any ``hedge`` hits, the finding is still produced, at the rule's
	   hedge severity and with its hedge wording. LazyPay's "we ideally
	   restrain from accessing" is neither a denial nor an admission, and
	   both suppressing it and reporting it at full severity would be wrong.

Then, once every clause has been seen, document-scoped rules fire for things
the document never said at all.
"""

from __future__ import annotations

import re
from importlib import import_module
from typing import Any, Callable, Pattern

from core.analyzer import numeric
from core.analyzer.base import BaseAnalyzer
from core.models import Clause, Finding, Severity
from core.tags import Rule, RuleSet, Scope

__all__ = ["RuleAnalyzer"]

# Placeholder in a rule's reason line, e.g. "{matched}" or "{annualised}".
_PLACEHOLDER = re.compile(r"\{(\w+)\}")

# Clause used to carry a document-scoped finding. Index -1 marks it as not
# corresponding to any real sentence, so a front end can render it as a note
# about the document rather than quoting text that was never written.
_ABSENCE_INDEX = -1


def _first_match(patterns: tuple[Pattern[str], ...], text: str) -> str | None:
	for pattern in patterns:
		found = pattern.search(text)
		if found:
			return found.group(0)
	return None


def _all_match(patterns: tuple[Pattern[str], ...], text: str) -> bool:
	return all(pattern.search(text) for pattern in patterns)


def _fill(template: str, values: dict[str, Any]) -> str:
	"""Substitute {placeholders}, leaving unknown ones as written.

	A rule author who mistypes a placeholder gets a visible ``{typo}`` in the
	output rather than a crash in front of a user mid-consent-dialog.
	"""
	def replace(match: re.Match[str]) -> str:
		key = match.group(1)
		if key not in values:
			return match.group(0)
		value = values[key]
		if isinstance(value, float):
			return f"{value:.6g}"
		return str(value)

	return _PLACEHOLDER.sub(replace, template)


class RuleAnalyzer(BaseAnalyzer):
	"""Match clauses against a rule set, deterministically and offline."""

	def classify(
		self,
		clauses: list[Clause],
		rule_set: RuleSet,
		origin: str = "",
	) -> list[Finding]:
		hook_result = self._run_directory_hook(rule_set, origin)

		findings: list[Finding] = []
		matched_rule_ids: set[str] = set()

		# A rule firing on the same sentence twice is one fact, not two. Real
		# pages repeat: a schedule of charges has one column per loan tenure,
		# so "Daily charges of up to 0.2% of the overdue principal amount"
		# appears three times identically and produced three findings and
		# three identical lines in the verdict. Deduplicated on the rule and
		# the sentence, not the clause index, so repeats in different table
		# cells collapse while the same rule firing on genuinely different
		# sentences is kept.
		seen: set[tuple[str, str]] = set()

		for clause in clauses:
			for rule in rule_set.clause_rules:
				finding = self._match(rule, clause, rule_set, hook_result)
				if finding is None:
					continue
				key = (rule.rule_id, " ".join(clause.text.split()).casefold())
				matched_rule_ids.add(rule.rule_id)
				if key in seen:
					continue
				seen.add(key)
				findings.append(finding)

		findings.extend(
			self._absences(clauses, rule_set, matched_rule_ids, hook_result)
		)
		return findings

	def _match(
		self,
		rule: Rule,
		clause: Clause,
		rule_set: RuleSet,
		hook_result: Any,
	) -> Finding | None:
		text = clause.text

		matched_text = _first_match(rule.patterns, text)
		if matched_text is None:
			return None

		if rule.requires and not _all_match(rule.requires, text):
			return None

		values: dict[str, Any] = {"matched": matched_text}
		if rule.numeric is not None:
			rate = numeric.extract(rule.numeric.kind, text)
			if rate is None or not rule.numeric.holds(rate.annualised):
				return None
			matched_text = rate.text
			values.update(
				matched=rate.text,
				value=rate.value,
				annualised=round(rate.annualised, 1),
			)

		# Negation before hedging: an outright denial beats a soft one.
		if _first_match(rule.negations, text) is not None:
			return None

		severity = rule.severity
		reason_template = rule.reason
		hedge = _first_match(rule.hedges, text) if rule.hedges else None
		if hedge is not None and rule.hedge_severity is not None:
			severity = rule.hedge_severity
			reason_template = rule.hedge_reason or rule.reason
			values["hedge"] = hedge

		metadata = dict(rule.metadata)
		if hedge is not None:
			metadata["hedged_by"] = hedge
		if rule_set.metadata.get("dla_directory") is not None:
			metadata["dla_directory"] = hook_result

		return Finding(
			rule_id=rule.rule_id,
			rule_set=rule_set.name,
			category=rule.category,
			severity=severity,
			reason=_fill(reason_template, values),
			clause=clause,
			matched_text=matched_text,
			confidence=rule.confidence,
			reference=rule.reference,
			metadata=metadata,
		)

	def _absences(
		self,
		clauses: list[Clause],
		rule_set: RuleSet,
		matched_rule_ids: set[str],
		hook_result: Any,
	) -> list[Finding]:
		"""Fire rules whose finding is that the document never said something.

		Skipped entirely for an empty document. "This policy never mentions
		how to opt out" is a claim about a policy, and there is no policy
		here to make it about.
		"""
		if not clauses:
			return []

		findings: list[Finding] = []
		for rule in rule_set.absence_rules:
			if any(_first_match(rule.patterns, c.text) for c in clauses):
				continue

			metadata = dict(rule.metadata)
			metadata["scope"] = Scope.DOCUMENT_ABSENT
			if rule_set.metadata.get("dla_directory") is not None:
				metadata["dla_directory"] = hook_result

			findings.append(
				Finding(
					rule_id=rule.rule_id,
					rule_set=rule_set.name,
					category=rule.category,
					severity=rule.severity,
					reason=rule.reason,
					clause=Clause(
						text=(
							"No clause anywhere in this document covers this. "
							"The finding is the absence."
						),
						index=_ABSENCE_INDEX,
						heading=None,
					),
					matched_text="",
					confidence=rule.confidence,
					reference=rule.reference,
					metadata=metadata,
				)
			)
		return findings

	@staticmethod
	def _run_directory_hook(rule_set: RuleSet, origin: str) -> Any:
		"""Call the external lookup a rule set declares, if it declares one.

		The hook is named by the rule set as a dotted path and resolved here,
		so the analyzer holds no hardcoded knowledge of RBI or of any other
		regulator's directory. A rule set that declares no hook costs nothing.

		A hook that raises is treated as "not checked". A lookup failing is
		not evidence about the lender, and must not be allowed to look like
		it is.
		"""
		declared = rule_set.metadata.get("dla_directory")
		if not isinstance(declared, dict):
			return None

		path = declared.get("hook")
		if not path or not origin:
			return None

		module_name, _, attribute = str(path).rpartition(".")
		if not module_name:
			return None

		try:
			hook: Callable[[str], Any] = getattr(import_module(module_name), attribute)
			return hook(origin)
		except Exception:
			return None
