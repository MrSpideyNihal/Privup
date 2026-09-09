"""Classification contract.

An analyzer takes the clauses a summarizer produced and the rule set the
caller asked for, and says which clauses matched which rules and why.

It contains no policy knowledge of its own. Every judgement lives in the rule
set, which is data. That split is what lets someone add a rule for, say, the
EU AI Act by writing a JSON file, without reading a line of this package.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from core.models import Clause, Finding
from core.tags import RuleSet

__all__ = ["BaseAnalyzer"]


class BaseAnalyzer(ABC):
	"""Match clauses against a rule set."""

	@abstractmethod
	def classify(
		self,
		clauses: list[Clause],
		rule_set: RuleSet,
		origin: str = "",
	) -> list[Finding]:
		"""Return the findings for ``clauses`` under ``rule_set``.

		``origin`` is passed through for rule sets that declare an external
		lookup hook, such as ``loan_app`` and RBI's DLA directory. Analyzers
		must not use it for anything else, and must never fetch anything with
		it: the network belongs to drivers.
		"""
		raise NotImplementedError
