"""Read rates out of clause text and normalise them to a yearly figure.

The reason this module exists, in one line of real text from a live lender:

	"Daily charges of up to 0.2% of the overdue principal amount"

Nought point two percent reads as almost nothing. Annualised it is about 73
percent, which is roughly twice the headline rate the same document quotes as
"Up to 36% p.a." for the loan itself. No keyword rule sees that, and no
borrower reading quickly sees it either. Normalising to a yearly figure before
comparing against a threshold is the entire trick, and it belongs here rather
than in a rule file because it is machinery, not policy.

Rules declare which strategy to use; this module implements them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = ["RateMatch", "extract", "DAYS_PER_YEAR", "MONTHS_PER_YEAR"]

DAYS_PER_YEAR = 365
MONTHS_PER_YEAR = 12

# A percentage, capturing the number. Allows "36%", "36 %", "0.2%", "7.5%".
_PERCENT = re.compile(r"(\d+(?:\.\d+)?)\s*(?:%|per ?cent(?:age)?\b)", re.IGNORECASE)

# Period markers, searched near a percentage.
_ANNUAL = re.compile(
	r"\bp\.?\s?a\.?\b|\bper annum\b|\bannual(?:ly|ised|ized)?\b|\ba year\b|\byearly\b|\bAPR\b",
	re.IGNORECASE,
)
_DAILY = re.compile(r"\bper day\b|\bdaily\b|\ba day\b|\bper diem\b", re.IGNORECASE)
_MONTHLY = re.compile(r"\bper month\b|\bmonthly\b|\ba month\b|\bp\.?\s?m\.?\b", re.IGNORECASE)

# How far from the number a period marker still counts as attached to it.
# Wide enough for "Rate of Interest (%) | Up to 36% p.a.", narrow enough that
# a percentage in one table cell does not borrow the period from another.
_NEAR = 32


@dataclass(frozen=True, slots=True)
class RateMatch:
	"""A figure found in a clause, and what it comes to over a year."""

	#: The number exactly as written, e.g. 0.2 for "0.2%".
	value: float

	#: ``value`` expressed per year. Equal to ``value`` when the figure was
	#: already annual or has no period at all.
	annualised: float

	#: The substring the figure was read from, for showing the user.
	text: str

	#: Which strategy produced this.
	kind: str


def _window(text: str, start: int, end: int) -> str:
	return text[max(0, start - _NEAR):min(len(text), end + _NEAR)]

def _snippet(text: str, start: int, end: int) -> str:
	"""A short readable quote around the figure, trimmed to word boundaries."""
	left = max(0, start - 20)
	right = min(len(text), end + 20)
	piece = text[left:right].strip()
	if left > 0:
		piece = piece.partition(" ")[2] or piece
	if right < len(text):
		piece = piece.rpartition(" ")[0] or piece
	return piece.strip(" |,;")


def _candidates(text: str) -> list[tuple[float, int, int]]:
	return [(float(m.group(1)), m.start(), m.end()) for m in _PERCENT.finditer(text)]


def extract(kind: str, text: str) -> RateMatch | None:
	"""Return the worst figure in ``text`` for the given strategy.

	"Worst" means largest once annualised, because a clause listing several
	rates is describing the one that hurts most alongside the others, and a
	user warned about the smallest has not been warned.

	Returns ``None`` when the clause has no figure the strategy recognises.
	The caller treats that as "this rule does not fire", not as zero.
	"""
	candidates = _candidates(text)
	if not candidates:
		return None

	best: RateMatch | None = None
	for value, start, end in candidates:
		near = _window(text, start, end)

		if kind == "percent_annual":
			if not _ANNUAL.search(near):
				continue
			annualised = value
		elif kind == "percent_daily":
			if not _DAILY.search(near):
				continue
			annualised = value * DAYS_PER_YEAR
		elif kind == "percent_monthly":
			if not _MONTHLY.search(near):
				continue
			annualised = value * MONTHS_PER_YEAR
		elif kind == "percent_any":
			annualised = value
		else:
			return None

		if best is None or annualised > best.annualised:
			best = RateMatch(
				value=value,
				annualised=annualised,
				text=_snippet(text, start, end),
				kind=kind,
			)

	return best
