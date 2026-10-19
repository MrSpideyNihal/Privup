"""Rewrite a Verdict into the user's language.

Runs after the scorer, so it never influences a decision. It rewrites what
the user reads and nothing else:

	Verdict.reasons, each Finding.reason, the headline, the relevance notice

and leaves alone what the user should be able to check against the source:

	clause text, matched text, headings, legal citations, rule ids

A wrong translation of a reason is a bad explanation. A wrong translation of
a clause would change what the user believes the policy says, so clauses are
never translated here.

Reasons are rebuilt from the rule id, the template variant the analyzer used
and the values it substituted, not by translating the English sentence. That
keeps placeholders like ``{annualised}`` exact and means two rules that say
the same thing in English are still told apart.

The headline is rebuilt from per-language templates because word order
differs: "X, Y, and Z flagged." does not survive being translated in pieces.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from core.models import Finding, Verdict, fill_template
from core.translator.catalog import (
	SOURCE_LANGUAGE,
	Catalog,
	get_catalog,
	message,
)

__all__ = ["translate"]

# Topics shown in a headline before the rest are counted as "+N more".
_HEADLINE_TOPICS = 3


def translate(verdict: Verdict, language: str) -> Verdict:
	"""Return ``verdict`` with everything the user reads in ``language``.

	Raises ``UnknownLanguageError`` for a language with no catalog. Anything
	the catalog does not cover stays in English and is listed under
	``metadata["translation"]["fallback"]``.
	"""
	if language == verdict.language:
		return verdict
	if verdict.language != SOURCE_LANGUAGE:
		raise ValueError(
			f"can only translate from {SOURCE_LANGUAGE!r}, this verdict is in {verdict.language!r}"
		)

	catalog = get_catalog(language)
	missing: set[str] = set()

	findings = tuple(_finding(f, catalog, missing) for f in verdict.findings)
	reasons = _reasons(verdict, findings, catalog, missing)

	metadata: dict[str, Any] = dict(verdict.metadata)
	headline = _headline(verdict, findings, catalog, missing)
	if headline is not None:
		metadata["headline"] = headline

	relevance = metadata.get("relevance")
	if isinstance(relevance, dict) and relevance.get("notice"):
		notice = (catalog.rule_sets.get(verdict.rule_set) or {}).get("relevance_notice")
		if notice:
			metadata["relevance"] = {**relevance, "notice": notice}
		else:
			missing.add(f"rule_sets.{verdict.rule_set}.relevance_notice")

	metadata["translation"] = {
		"language": catalog.language,
		"reviewed": catalog.reviewed,
		"complete": not missing,
		"fallback": sorted(missing),
	}

	return replace(
		verdict,
		reasons=tuple(reasons),
		findings=findings,
		language=catalog.language,
		metadata=metadata,
	)


def _finding(finding: Finding, catalog: Catalog, missing: set[str]) -> Finding:
	variant = finding.metadata.get("reason_variant", "reason")
	template = catalog.rule_text(finding.rule_id, variant)
	if template is None:
		missing.add(f"rules.{finding.rule_id}.{variant}")
		return finding
	reason = fill_template(template, finding.metadata.get("reason_values") or {})
	return replace(
		finding,
		reason=reason,
		metadata={**finding.metadata, "source_reason": finding.reason},
	)


def _reasons(
	verdict: Verdict,
	findings: tuple[Finding, ...],
	catalog: Catalog,
	missing: set[str],
) -> list[str]:
	if verdict.metadata.get("empty_document"):
		return [_message(catalog, "verdict.empty_document", missing)]
	if not findings:
		return list(verdict.reasons)

	# Same rule as the scorer: one line per distinct reason, worst first.
	# Findings are already in that order.
	reasons: list[str] = []
	seen: set[str] = set()
	for finding in findings:
		if finding.reason not in seen:
			seen.add(finding.reason)
			reasons.append(finding.reason)
	return reasons


def _headline(
	verdict: Verdict,
	findings: tuple[Finding, ...],
	catalog: Catalog,
	missing: set[str],
) -> str | None:
	if verdict.metadata.get("headline") is None:
		return None
	if verdict.metadata.get("empty_document"):
		return _message(catalog, "headline.empty_document", missing)
	# An Allow that still lists minor notes says "no red flags", not "flagged".
	if not findings or verdict.metadata.get("notes_only"):
		return _message(catalog, "headline.clean", missing)

	topics: list[str] = []
	for finding in findings:
		label = catalog.rule_text(finding.rule_id, "label")
		if label is None:
			# A headline mixing two languages reads worse than one entirely
			# in English, so one missing label keeps the English headline.
			missing.add(f"rules.{finding.rule_id}.label")
			return verdict.metadata["headline"]
		if label not in topics:
			topics.append(label)

	shown = topics[:_HEADLINE_TOPICS]
	remaining = len(topics) - len(shown)
	more = _message(catalog, "headline.more", missing, n=remaining) if remaining else ""

	if len(shown) == 1:
		text = _message(catalog, "headline.one", missing, a=shown[0])
	elif len(shown) == 2:
		text = _message(catalog, "headline.two", missing, a=shown[0], b=shown[1], more=more)
	else:
		text = _message(
			catalog, "headline.three", missing, a=shown[0], b=shown[1], c=shown[2], more=more
		)
	return text[:1].upper() + text[1:]


def _message(catalog: Catalog, key: str, missing: set[str], **values: Any) -> str:
	if key not in catalog.messages:
		missing.add(f"messages.{key}")
	return message(catalog.language, key, **values)
