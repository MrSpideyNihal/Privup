"""Classification contract.

A classifier takes the clauses a summarizer produced and the rule set the
caller asked for, and says which clauses matched which rules and why. It
contains no policy knowledge of its own; every judgement lives in the rule
set, which is data.

There is more than one way to decide a clause matters, and regex is only the
cheapest. Matching surface forms has a hard ceiling: policy text is written by
lawyers who paraphrase indefinitely, and Google's "We keep some data until you
delete your Google Account" is a retention clause containing none of the
retention vocabulary any sane pattern list would hold. Adding patterns does
not fix that, it just moves along a precision/recall curve while adding a
false positive each time.

So classification is a composition, not a single implementation. Every
classifier emits the same ``Finding``, so ``core/scorer``, ``core/main.py``,
``cli/`` and ``ui/`` cannot tell which one produced what. A model-backed
classifier is a new class here and nothing else changes, which is the same
property drivers and rule sets already have.

``Finding.confidence`` is what makes the mix legible: a deterministic rule
match reports 1.0, and anything less says a judgement was involved.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

from core.models import Clause, Finding
from core.tags import RuleSet

__all__ = ["BaseAnalyzer", "Classifier"]


class Classifier(ABC):
	"""One way of deciding which clauses matter."""

	#: Registry key, and the value recorded on every finding this produces so
	#: a reader can tell what judged them.
	name: ClassVar[str] = ""

	#: One line for the CLI listing.
	description: ClassVar[str] = ""

	#: False when a classifier needs an optional dependency or model file that
	#: is not present. An unavailable classifier is skipped rather than
	#: crashing the pipeline, so the rule-only path always works.
	@property
	def available(self) -> bool:
		return True

	@abstractmethod
	def classify(
		self,
		clauses: list[Clause],
		rule_set: RuleSet,
		origin: str = "",
	) -> list[Finding]:
		"""Return the findings for ``clauses`` under ``rule_set``.

		``origin`` is passed through for rule sets that declare an external
		lookup hook, such as ``loan_app`` and RBI's DLA directory. Classifiers
		must not use it for anything else, and must never fetch anything with
		it: the network belongs to drivers.

		Must be deterministic given the same inputs. A verdict a user cannot
		reproduce is a verdict they cannot check.
		"""
		raise NotImplementedError


#: The original name for this contract, kept so existing code and any
#: contributor's in-progress branch keeps working.
BaseAnalyzer = Classifier
