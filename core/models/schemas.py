"""Shared data schemas for the PrivUp pipeline.

These four types are the only contract between pipeline stages:

	DriverResult  produced by core/scraper   -> consumed by core/summarizer
	Clause        produced by core/summarizer -> consumed by core/analyzer
	Finding       produced by core/analyzer   -> consumed by core/scorer
	Verdict       produced by core/scorer     -> consumed by callers (CLI, UI, app)

No stage imports another stage. A new driver, rule set or front end plugs in by
speaking these types and nothing else.

Everything here is standard-library only, frozen, and round-trips through
``to_dict``/``from_dict`` so the same objects can cross a process boundary
(CLI JSON output), a language boundary (browser extension, Android) or a test
fixture without a serialization framework.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterable, Mapping

__all__ = [
	"Severity",
	"Decision",
	"DriverResult",
	"Clause",
	"Finding",
	"Verdict",
	"utc_now",
]


def utc_now() -> datetime:
	"""Return the current time as a timezone-aware UTC datetime."""
	return datetime.now(timezone.utc)


def _parse_time(value: Any) -> datetime:
	"""Accept a datetime or an ISO-8601 string and return a datetime."""
	if isinstance(value, datetime):
		return value
	return datetime.fromisoformat(str(value))


class Severity(str, Enum):
	"""How bad a single matched rule is.

	Ordered. ``scorer`` compares severities to pick a decision, so the order
	below is load-bearing: CRITICAL is what turns a Warning into a Deny.
	"""

	INFO = "info"
	LOW = "low"
	MEDIUM = "medium"
	HIGH = "high"
	CRITICAL = "critical"

	@property
	def rank(self) -> int:
		"""Position in the severity order, 0 for INFO."""
		return _SEVERITY_ORDER.index(self.value)

	def __lt__(self, other: object) -> bool:
		if not isinstance(other, Severity):
			return NotImplemented
		return self.rank < other.rank

	def __le__(self, other: object) -> bool:
		if not isinstance(other, Severity):
			return NotImplemented
		return self.rank <= other.rank

	def __gt__(self, other: object) -> bool:
		if not isinstance(other, Severity):
			return NotImplemented
		return self.rank > other.rank

	def __ge__(self, other: object) -> bool:
		if not isinstance(other, Severity):
			return NotImplemented
		return self.rank >= other.rank


_SEVERITY_ORDER = ("info", "low", "medium", "high", "critical")


class Decision(str, Enum):
	"""The three answers PrivUp is allowed to give a user."""

	ALLOW = "allow"
	WARNING = "warning"
	DENY = "deny"


@dataclass(frozen=True, slots=True)
class DriverResult:
	"""Raw policy text plus where it came from.

	Produced by a scraper driver's ``fetch(target)``. This is the only object
	in the pipeline that may have touched the network, and only from inside
	``fetch``.

	``content_type`` tells the summarizer whether to run HTML stripping. A
	driver that already knows it holds plain text says so, and the summarizer
	does not have to guess.

	``metadata`` is the driver's private extension point: HTTP status and the
	post-redirect URL for ``url_driver``, declared permissions read from
	PackageManager for a future Android driver. No downstream stage may depend
	on a specific key being present.
	"""

	raw_text: str
	origin: str
	driver: str
	content_type: str = "text/plain"
	fetched_at: datetime = field(default_factory=utc_now)
	metadata: Mapping[str, Any] = field(default_factory=dict)

	@property
	def is_empty(self) -> bool:
		"""True when the driver returned nothing usable to analyze."""
		return not self.raw_text.strip()

	def to_dict(self) -> dict[str, Any]:
		return {
			"raw_text": self.raw_text,
			"origin": self.origin,
			"driver": self.driver,
			"content_type": self.content_type,
			"fetched_at": self.fetched_at.isoformat(),
			"metadata": dict(self.metadata),
		}

	@classmethod
	def from_dict(cls, data: Mapping[str, Any]) -> "DriverResult":
		return cls(
			raw_text=data["raw_text"],
			origin=data["origin"],
			driver=data["driver"],
			content_type=data.get("content_type", "text/plain"),
			fetched_at=_parse_time(data.get("fetched_at", utc_now())),
			metadata=dict(data.get("metadata", {})),
		)


@dataclass(frozen=True, slots=True)
class Clause:
	"""One sentence-level unit of policy text, with the heading it sat under.

	``heading`` is kept because it carries most of the context a single
	sentence loses. "We retain this for as long as necessary" means something
	different under "Data Retention" than under "Cookie Preferences", and the
	user needs to see which section a warning came from.

	``char_start``/``char_end`` are offsets into the cleaned document, not the
	original HTML. They exist so a front end can highlight the clause in the
	text it was shown; they are -1 when the producer did not track them.
	"""

	text: str
	index: int
	heading: str | None = None
	char_start: int = -1
	char_end: int = -1

	@property
	def clause_id(self) -> str:
		"""Stable handle for this clause, safe to use as a DOM id."""
		return f"c{self.index:04d}"

	def to_dict(self) -> dict[str, Any]:
		return {
			"clause_id": self.clause_id,
			"text": self.text,
			"index": self.index,
			"heading": self.heading,
			"char_start": self.char_start,
			"char_end": self.char_end,
		}

	@classmethod
	def from_dict(cls, data: Mapping[str, Any]) -> "Clause":
		return cls(
			text=data["text"],
			index=int(data["index"]),
			heading=data.get("heading"),
			char_start=int(data.get("char_start", -1)),
			char_end=int(data.get("char_end", -1)),
		)


@dataclass(frozen=True, slots=True)
class Finding:
	"""One clause matched by one rule, and why that matters.

	The triggering ``Clause`` is embedded rather than referenced by id. A
	Finding is therefore self-contained: the CLI, the local UI, the browser
	popup and the Android result screen can each render the evidence without
	being handed the full clause list alongside it.

	``reason`` is the plain-language line the user actually reads. It is
	written for someone standing in front of a permission dialog, not for a
	lawyer.

	``reference`` is the regulation or principle the rule encodes, for example
	"RBI Digital Lending Directions 2025" or "GDPR Art. 5(1)(e)". It is what
	separates "this app looks sketchy" from "this is not permitted".

	``confidence`` is 1.0 for a deterministic rule match. It exists now so the
	later ML phase can lower it without changing this schema.

	``metadata`` carries rule-set-specific detail, for example which Android
	permission a loan_app rule fired on, or the result of the RBI DLA
	directory lookup once that hook is implemented.
	"""

	rule_id: str
	rule_set: str
	category: str
	severity: Severity
	reason: str
	clause: Clause
	matched_text: str = ""
	confidence: float = 1.0
	reference: str | None = None
	metadata: Mapping[str, Any] = field(default_factory=dict)

	def to_dict(self) -> dict[str, Any]:
		return {
			"rule_id": self.rule_id,
			"rule_set": self.rule_set,
			"category": self.category,
			"severity": self.severity.value,
			"reason": self.reason,
			"clause": self.clause.to_dict(),
			"matched_text": self.matched_text,
			"confidence": self.confidence,
			"reference": self.reference,
			"metadata": dict(self.metadata),
		}

	@classmethod
	def from_dict(cls, data: Mapping[str, Any]) -> "Finding":
		return cls(
			rule_id=data["rule_id"],
			rule_set=data["rule_set"],
			category=data["category"],
			severity=Severity(data["severity"]),
			reason=data["reason"],
			clause=Clause.from_dict(data["clause"]),
			matched_text=data.get("matched_text", ""),
			confidence=float(data.get("confidence", 1.0)),
			reference=data.get("reference"),
			metadata=dict(data.get("metadata", {})),
		)


@dataclass(frozen=True, slots=True)
class Verdict:
	"""The answer PrivUp hands back: Allow, Warning or Deny, and why.

	``reasons`` is the flat display list, one line per finding, ordered most
	severe first. It duplicates ``Finding.reason`` on purpose: a caller that
	only wants to print three lines should not have to walk the findings, and
	a caller that wants the evidence behind line two can index into
	``findings``, which is ordered identically.

	``risk_score`` is a 0-100 derived signal for sorting and trend display. It
	is not the verdict. ``decision`` is the verdict.

	``language`` is the language ``reasons`` are written in. The translator
	stage rewrites the reasons and updates this field; clause text is left in
	its source language on purpose, so a translation error can never change
	what the user believes the policy says.
	"""

	decision: Decision
	rule_set: str
	origin: str
	reasons: tuple[str, ...] = ()
	findings: tuple[Finding, ...] = ()
	risk_score: float = 0.0
	clauses_analyzed: int = 0
	language: str = "en"
	analyzed_at: datetime = field(default_factory=utc_now)
	metadata: Mapping[str, Any] = field(default_factory=dict)

	def __post_init__(self) -> None:
		# Accept lists from callers, store tuples so a frozen Verdict is
		# actually frozen rather than frozen-with-a-mutable-list-inside.
		object.__setattr__(self, "reasons", tuple(self.reasons))
		object.__setattr__(self, "findings", tuple(self.findings))

	@property
	def is_blocking(self) -> bool:
		"""True when PrivUp is telling the user not to accept."""
		return self.decision is Decision.DENY

	@property
	def highest_severity(self) -> Severity | None:
		"""Severity of the worst finding, or None when there are no findings."""
		if not self.findings:
			return None
		return max(f.severity for f in self.findings)

	def findings_by_category(self) -> dict[str, list[Finding]]:
		"""Group findings by rule category, preserving order within a group."""
		grouped: dict[str, list[Finding]] = {}
		for finding in self.findings:
			grouped.setdefault(finding.category, []).append(finding)
		return grouped

	def with_reasons(self, reasons: Iterable[str], language: str) -> "Verdict":
		"""Return a copy carrying translated reasons. Used by core/translator."""
		return replace(self, reasons=tuple(reasons), language=language)

	def to_dict(self) -> dict[str, Any]:
		return {
			"decision": self.decision.value,
			"rule_set": self.rule_set,
			"origin": self.origin,
			"reasons": list(self.reasons),
			"findings": [f.to_dict() for f in self.findings],
			"risk_score": self.risk_score,
			"clauses_analyzed": self.clauses_analyzed,
			"language": self.language,
			"analyzed_at": self.analyzed_at.isoformat(),
			"metadata": dict(self.metadata),
		}

	@classmethod
	def from_dict(cls, data: Mapping[str, Any]) -> "Verdict":
		return cls(
			decision=Decision(data["decision"]),
			rule_set=data["rule_set"],
			origin=data["origin"],
			reasons=tuple(data.get("reasons", ())),
			findings=tuple(Finding.from_dict(f) for f in data.get("findings", ())),
			risk_score=float(data.get("risk_score", 0.0)),
			clauses_analyzed=int(data.get("clauses_analyzed", 0)),
			language=data.get("language", "en"),
			analyzed_at=_parse_time(data.get("analyzed_at", utc_now())),
			metadata=dict(data.get("metadata", {})),
		)
