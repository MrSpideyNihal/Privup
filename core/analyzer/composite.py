"""Run several classifiers and reconcile what they say.

The interesting question is not how to run two classifiers, it is what to do
when both flag the same clause. Reporting it twice means the user reads the
same warning twice in different words, which reads as noise and erodes trust
in the ones that matter.

The rule here: one finding per clause per category, resolved in this order.

	1. Higher confidence wins. A classifier that is surer should be heard.
	2. Then higher severity. Where two readings are equally confident,
	   under-reporting a risk is the worse error, and the scorer decides the
	   verdict from the worst finding, so silently keeping the milder one
	   could turn a Warning into an Allow.
	3. Then whoever ran first, which by convention is the rule matcher. A
	   rule carries a citation a reader can check; a model carries a number.
	   Where they agree exactly, cite the rule.

Confidence outranks severity deliberately. The other way round would let a
barely-confident model shout down a certain rule just by calling something
critical.

The loser is not thrown away. It is recorded on the winner's metadata, so an
evaluation run can still see that both fired and a reviewer can tell agreement
from a lucky single hit.
"""

from __future__ import annotations

from typing import Iterable, Sequence

from core.analyzer.base import Classifier
from core.models import Clause, Finding
from core.tags import RuleSet

__all__ = ["CompositeAnalyzer"]


def _key(finding: Finding) -> tuple[int, str]:
	"""What counts as "the same finding" across classifiers.

	Clause plus category, not clause plus rule id. Two classifiers reaching
	the same conclusion about the same sentence will rarely agree on a rule
	id, and telling the user twice that their contacts are being read is
	still telling them twice.
	"""
	return (finding.clause.index, finding.category)


class CompositeAnalyzer(Classifier):
	"""Run classifiers in order and merge their findings."""

	name = "composite"
	description = "Run several classifiers and reconcile overlapping findings."

	def __init__(self, classifiers: Sequence[Classifier]) -> None:
		if not classifiers:
			raise ValueError("a composite needs at least one classifier")
		self.classifiers = tuple(classifiers)

	@property
	def available(self) -> bool:
		return any(c.available for c in self.classifiers)

	def classify(
		self,
		clauses: list[Clause],
		rule_set: RuleSet,
		origin: str = "",
	) -> list[Finding]:
		best: dict[tuple[int, str], Finding] = {}
		also: dict[tuple[int, str], list[str]] = {}
		order: list[tuple[int, str]] = []

		for position, classifier in enumerate(self.classifiers):
			if not classifier.available:
				continue

			for finding in classifier.classify(clauses, rule_set, origin=origin):
				finding = self._stamp(finding, classifier)
				key = _key(finding)

				if key not in best:
					best[key] = finding
					order.append(key)
					continue

				incumbent = best[key]
				if self._beats(finding, incumbent, position):
					also.setdefault(key, []).append(self._label(incumbent))
					best[key] = finding
				else:
					also.setdefault(key, []).append(self._label(finding))

		return [self._with_agreement(best[key], also.get(key, [])) for key in order]

	@staticmethod
	def _stamp(finding: Finding, classifier: Classifier) -> Finding:
		"""Record which classifier produced this."""
		if finding.metadata.get("classifier") == classifier.name:
			return finding
		return Finding(
			rule_id=finding.rule_id,
			rule_set=finding.rule_set,
			category=finding.category,
			severity=finding.severity,
			reason=finding.reason,
			clause=finding.clause,
			matched_text=finding.matched_text,
			confidence=finding.confidence,
			reference=finding.reference,
			metadata={**finding.metadata, "classifier": classifier.name},
		)

	@staticmethod
	def _label(finding: Finding) -> str:
		return f"{finding.metadata.get('classifier', '?')}:{finding.rule_id}"

	@staticmethod
	def _beats(challenger: Finding, incumbent: Finding, position: int) -> bool:
		"""Confidence, then severity, then order of registration."""
		del position
		if challenger.confidence != incumbent.confidence:
			return challenger.confidence > incumbent.confidence
		if challenger.severity != incumbent.severity:
			return challenger.severity > incumbent.severity
		# Dead even: the incumbent ran first, and by convention that is the
		# rule matcher, whose finding carries a citation.
		return False

	@staticmethod
	def _with_agreement(finding: Finding, others: list[str]) -> Finding:
		if not others:
			return finding
		return Finding(
			rule_id=finding.rule_id,
			rule_set=finding.rule_set,
			category=finding.category,
			severity=finding.severity,
			reason=finding.reason,
			clause=finding.clause,
			matched_text=finding.matched_text,
			confidence=finding.confidence,
			reference=finding.reference,
			metadata={**finding.metadata, "also_flagged_by": sorted(set(others))},
		)


def default_analyzer(extra: Iterable[Classifier] = ()) -> Classifier:
	"""The pipeline's standard classifier stack.

	Rules first, deliberately: they are deterministic and carry citations, so
	where anything else agrees with them the citable finding is the one kept.
	"""
	from core.analyzer.simple import RuleAnalyzer

	classifiers: list[Classifier] = [RuleAnalyzer()]
	classifiers.extend(extra)
	if len(classifiers) == 1:
		return classifiers[0]
	return CompositeAnalyzer(classifiers)
