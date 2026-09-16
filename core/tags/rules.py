"""Rule and rule-set types, and the loader that reads them from JSON.

Rules are data. Everything in this module is about *describing* a rule; none
of it decides whether a clause matches. That belongs to ``core/analyzer``, so
that adding a rule set means adding a JSON file and nothing else.

The shape of a rule is driven by what real policy text actually does.

``patterns`` alone is not enough, because policies talk about permissions they
do *not* take. Kissht's policy contains the phrase "contact list, call logs,
telephony Functions" inside the sentence "We also do not access your mobile
phone resources such as ...". A keyword rule flags a lender that is compliant
on exactly that point. Hence ``negations``.

Suppression alone is not enough either, because the interesting case is in
between. LazyPay writes "we ideally restrain from accessing mobile phone
resources like file and media, contact list, call logs". That is not a denial,
it is a hedge, and a borrower deserves to be told that the promise is soft.
Hence ``hedges``, which downgrade a finding rather than delete it.

``numeric`` exists because the worst term in a loan is a number. "Daily
charges of up to 0.2% of the overdue principal amount" is an annualised rate
somewhere north of 70 percent, and no amount of keyword matching notices that.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Pattern

from core.models import Severity

__all__ = [
	"Rule",
	"RuleSet",
	"NumericCheck",
	"RuleSetError",
	"Scope",
	"load_rule_set",
	"parse_rule_set",
]


class RuleSetError(ValueError):
	"""A rule set file is malformed. Raised with the file and rule id."""


class Scope:
	"""How a rule is evaluated against a document."""

	#: Fire once per clause that matches. The normal case.
	CLAUSE = "clause"

	#: Fire once for the whole document if *no* clause matches. Used for
	#: red flags that are about silence rather than about wording, such as a
	#: policy that never mentions how to withdraw consent.
	DOCUMENT_ABSENT = "document_absent"

	ALL = frozenset({CLAUSE, DOCUMENT_ABSENT})


# Numeric extraction strategies the analyzer knows how to run. A rule names
# one; the implementation lives in core/analyzer/numeric.py.
NUMERIC_KINDS = frozenset({
	"percent_annual",   # "36% p.a.", "36 percent per annum"
	"percent_daily",    # "0.2% per day" -> annualised before comparison
	"percent_monthly",  # "3% per month" -> annualised before comparison
	"percent_any",      # any percentage in the clause, used for flat fees
})

_OPERATORS = frozenset({">=", ">", "<=", "<"})


@dataclass(frozen=True, slots=True)
class NumericCheck:
	"""Extract a figure from the clause and compare it against a threshold.

	``kind`` selects how the figure is read and normalised. ``percent_daily``
	annualises before comparing, which is the whole point: 0.2 percent a day
	and 36 percent a year look similar on the page and are not remotely the
	same debt.
	"""

	kind: str
	operator: str
	threshold: float

	@classmethod
	def from_dict(cls, data: Mapping[str, Any], where: str) -> "NumericCheck":
		kind = str(data.get("kind", ""))
		if kind not in NUMERIC_KINDS:
			raise RuleSetError(
				f"{where}: numeric.kind must be one of {sorted(NUMERIC_KINDS)}, got {kind!r}"
			)
		operator = str(data.get("operator", ">="))
		if operator not in _OPERATORS:
			raise RuleSetError(
				f"{where}: numeric.operator must be one of {sorted(_OPERATORS)}, got {operator!r}"
			)
		if "threshold" not in data:
			raise RuleSetError(f"{where}: numeric.threshold is required")
		try:
			threshold = float(data["threshold"])
		except (TypeError, ValueError):
			raise RuleSetError(f"{where}: numeric.threshold must be a number") from None
		return cls(kind=kind, operator=operator, threshold=threshold)

	def holds(self, value: float) -> bool:
		"""True when ``value`` trips this check."""
		if self.operator == ">=":
			return value >= self.threshold
		if self.operator == ">":
			return value > self.threshold
		if self.operator == "<=":
			return value <= self.threshold
		return value < self.threshold


def _compile_all(patterns: Iterable[str], where: str, field_name: str) -> tuple[Pattern[str], ...]:
	compiled = []
	for pattern in patterns:
		try:
			compiled.append(re.compile(pattern, re.IGNORECASE))
		except re.error as exc:
			raise RuleSetError(f"{where}: bad regex in {field_name}: {pattern!r} ({exc})") from None
	return tuple(compiled)


def _severity(value: Any, where: str, field_name: str) -> Severity:
	try:
		return Severity(str(value).lower())
	except ValueError:
		raise RuleSetError(
			f"{where}: {field_name} must be one of "
			f"{[s.value for s in Severity]}, got {value!r}"
		) from None


@dataclass(frozen=True, slots=True)
class Rule:
	"""One thing worth telling a user about, and how to spot it.

	A clause fires this rule when it matches any of ``patterns``, also
	matches every entry in ``requires``, and matches none of ``negations``.
	If it matches a ``hedge``, the finding is still produced but at
	``hedge_severity`` with ``hedge_reason``, because a soft promise is
	itself worth reporting.
	"""

	rule_id: str
	category: str
	severity: Severity
	reason: str
	patterns: tuple[Pattern[str], ...]
	requires: tuple[Pattern[str], ...] = ()
	negations: tuple[Pattern[str], ...] = ()
	hedges: tuple[Pattern[str], ...] = ()
	hedge_severity: Severity | None = None
	hedge_reason: str | None = None
	numeric: NumericCheck | None = None
	scope: str = Scope.CLAUSE
	reference: str | None = None
	note: str = ""
	confidence: float = 1.0
	metadata: Mapping[str, Any] = field(default_factory=dict)

	@classmethod
	def from_dict(cls, data: Mapping[str, Any], source: str) -> "Rule":
		rule_id = str(data.get("id", "")).strip()
		if not rule_id:
			raise RuleSetError(f"{source}: every rule needs a non-empty 'id'")
		where = f"{source}:{rule_id}"

		for required in ("category", "severity", "reason"):
			if not data.get(required):
				raise RuleSetError(f"{where}: '{required}' is required")

		scope = str(data.get("scope", Scope.CLAUSE))
		if scope not in Scope.ALL:
			raise RuleSetError(f"{where}: scope must be one of {sorted(Scope.ALL)}, got {scope!r}")

		patterns = data.get("patterns") or []
		if not patterns:
			raise RuleSetError(f"{where}: at least one entry in 'patterns' is required")

		hedges = _compile_all(data.get("hedges") or [], where, "hedges")
		hedge_severity = data.get("hedge_severity")
		hedge_reason = data.get("hedge_reason")
		if hedges and not (hedge_severity and hedge_reason):
			raise RuleSetError(
				f"{where}: 'hedges' requires both 'hedge_severity' and 'hedge_reason', "
				"otherwise a hedged match has nothing to report"
			)

		numeric_raw = data.get("numeric")

		return cls(
			rule_id=rule_id,
			category=str(data["category"]),
			severity=_severity(data["severity"], where, "severity"),
			reason=str(data["reason"]),
			patterns=_compile_all(patterns, where, "patterns"),
			requires=_compile_all(data.get("requires") or [], where, "requires"),
			negations=_compile_all(data.get("negations") or [], where, "negations"),
			hedges=hedges,
			hedge_severity=(
				_severity(hedge_severity, where, "hedge_severity") if hedges else None
			),
			hedge_reason=str(hedge_reason) if hedges else None,
			numeric=NumericCheck.from_dict(numeric_raw, where) if numeric_raw else None,
			scope=scope,
			reference=data.get("reference"),
			note=str(data.get("note", "")),
			confidence=float(data.get("confidence", 1.0)),
			metadata=dict(data.get("metadata") or {}),
		)


@dataclass(frozen=True, slots=True)
class RuleSet:
	"""A named collection of rules, plus what it is for."""

	name: str
	description: str
	rules: tuple[Rule, ...]
	reference: str | None = None
	metadata: Mapping[str, Any] = field(default_factory=dict)

	def __len__(self) -> int:
		return len(self.rules)

	def __iter__(self):
		return iter(self.rules)

	@property
	def clause_rules(self) -> tuple[Rule, ...]:
		return tuple(r for r in self.rules if r.scope == Scope.CLAUSE)

	@property
	def absence_rules(self) -> tuple[Rule, ...]:
		return tuple(r for r in self.rules if r.scope == Scope.DOCUMENT_ABSENT)

	def categories(self) -> list[str]:
		seen: dict[str, None] = {}
		for rule in self.rules:
			seen.setdefault(rule.category, None)
		return list(seen)


def parse_rule_set(data: Mapping[str, Any], source: str) -> RuleSet:
	"""Build a ``RuleSet`` from already-decoded JSON."""
	name = str(data.get("name", "")).strip()
	if not name:
		raise RuleSetError(f"{source}: rule set needs a non-empty 'name'")

	raw_rules = data.get("rules")
	if not isinstance(raw_rules, list) or not raw_rules:
		raise RuleSetError(f"{source}: rule set needs a non-empty 'rules' list")

	rules: list[Rule] = []
	seen_ids: set[str] = set()
	for entry in raw_rules:
		rule = Rule.from_dict(entry, source)
		if rule.rule_id in seen_ids:
			raise RuleSetError(f"{source}: duplicate rule id {rule.rule_id!r}")
		seen_ids.add(rule.rule_id)
		rules.append(rule)

	return RuleSet(
		name=name,
		description=str(data.get("description", "")),
		rules=tuple(rules),
		reference=data.get("reference"),
		metadata=dict(data.get("metadata") or {}),
	)


def load_rule_set(path: Path) -> RuleSet:
	"""Read and validate a rule set from a JSON file."""
	try:
		data = json.loads(path.read_text(encoding="utf-8"))
	except json.JSONDecodeError as exc:
		raise RuleSetError(f"{path.name}: invalid JSON ({exc})") from None
	return parse_rule_set(data, source=path.name)
