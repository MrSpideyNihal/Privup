"""Is this rule set a sensible thing to run against this document?

PrivUp does not restrict which rule set runs against which target. Someone
testing an edge case, or writing rules for an app that fits no category
cleanly, is doing something legitimate, and a tool that blocks them is a tool
they will fork or abandon.

But a confident Deny on the wrong grounds is worse than no answer. Run the
``loan_app`` set against a messaging app and it reports critical findings for
contacts and message access, which is exactly correct for a lender and
completely wrong for a messenger. A user who picked the wrong dropdown entry
gets told, in the tool's most emphatic voice, something untrue. Trust is the
only thing this project has.

So: a soft notice, never a block. The findings are still produced, still
scored, still shown. The notice sits alongside them and says the rules may
not fit.

The signals are rule-set data, declared in the JSON, not logic here. A rule
set that declares no ``relevance`` block never produces a notice, which is
correct for ``generic``: it is meant to apply to anything.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

from core.models import Clause
from core.tags.rules import RuleSet

__all__ = ["RelevanceCheck", "check_relevance"]


class RelevanceCheck:
	"""Whether a rule set looks applicable, and what to say if it does not."""

	__slots__ = ("applies", "notice", "matched", "required")

	def __init__(
		self,
		applies: bool,
		notice: str | None,
		matched: Sequence[str],
		required: int,
	) -> None:
		self.applies = applies
		self.notice = notice
		self.matched = list(matched)
		self.required = required

	def to_dict(self) -> dict[str, Any]:
		return {
			"applies": self.applies,
			"notice": self.notice,
			"matched_signals": self.matched,
			"required_signals": self.required,
		}

	def __repr__(self) -> str:
		return f"RelevanceCheck(applies={self.applies}, matched={self.matched})"


_APPLIES = RelevanceCheck(applies=True, notice=None, matched=[], required=0)


# Below this many words there is not enough vocabulary to judge, and the
# honest answer is silence. Someone pasting a single clause out of a consent
# dialog is a normal thing to do, and telling them "this does not look like a
# lending app" because one sentence lacks the word "borrower" is crying wolf.
DEFAULT_MIN_WORDS = 120


def _config(declared: Mapping[str, Any]) -> tuple[list[str], int, int, str]:
	raw = declared.get("signals") or []
	signals = [str(s).lower() for s in raw if str(s).strip()]
	minimum = int(declared.get("min_signals", 3))
	min_words = int(declared.get("min_words", DEFAULT_MIN_WORDS))
	notice = str(
		declared.get("notice")
		or "This document may not be the kind these rules were written for."
	)
	return signals, minimum, min_words, notice


def check_relevance(clauses: Iterable[Clause], rule_set: RuleSet) -> RelevanceCheck:
	"""Decide whether ``rule_set`` looks like it fits this document.

	Counts how many distinct declared signal phrases appear anywhere in the
	document. Distinct phrases rather than total occurrences, so one heavily
	repeated word cannot carry the decision on its own.

	A rule set with no ``relevance`` block always applies.
	"""
	declared = rule_set.metadata.get("relevance")
	if not isinstance(declared, Mapping):
		return _APPLIES

	signals, minimum, min_words, notice = _config(declared)
	if not signals:
		return _APPLIES

	haystack = "\n".join(clause.text for clause in clauses).lower()
	if not haystack.strip():
		# Nothing was read. The empty-document warning already covers this,
		# and adding "these rules may not apply" on top would just be noise.
		return _APPLIES

	if len(haystack.split()) < min_words:
		# Too little text to draw a conclusion from. Saying nothing is more
		# honest than guessing, and a false notice trains people to ignore
		# the real ones.
		return _APPLIES

	matched = sorted({signal for signal in signals if signal in haystack})
	if len(matched) >= minimum:
		return RelevanceCheck(True, None, matched, minimum)

	return RelevanceCheck(False, notice, matched, minimum)
