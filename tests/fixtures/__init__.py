"""Real privacy-policy and loan-terms text used by the test suite.

Every fixture in this directory is real text retrieved from a live page, not
written for the tests. That is a deliberate rule, and it has already earned
its keep: invented text would have been uniformly incriminating, and the
first pass of the analyzer would have looked excellent while being useless.

Real policies are not like that. Kissht's policy says it does *not* access
contact lists and call logs. LazyPay's says it "ideally restrains" from doing
so, then says elsewhere that it transmits SMS logs to its servers. Only
reading the real thing surfaces the fact that negation and hedging are the
central problem, not keyword coverage.

Text fixtures carry a provenance header of ``#`` comment lines terminated by
``# ---``. ``load_text`` strips it, so the header never reaches the analyzer.
Excerpts only; none of these reproduce a complete document.
"""

from __future__ import annotations

from pathlib import Path

__all__ = ["FIXTURE_DIR", "load_text", "load_html", "provenance", "text_fixtures"]

FIXTURE_DIR = Path(__file__).parent

_HEADER_END = "# ---"


def _split_header(content: str) -> tuple[list[str], str]:
	lines = content.splitlines()
	for position, line in enumerate(lines):
		if line.strip() == _HEADER_END:
			return lines[:position], "\n".join(lines[position + 1:])
	return [], content


def load_text(name: str) -> str:
	"""Return a text fixture's body with its provenance header removed."""
	path = FIXTURE_DIR / name
	_, body = _split_header(path.read_text(encoding="utf-8"))
	return body.strip("\n")


def provenance(name: str) -> dict[str, str]:
	"""Return the ``key: value`` pairs from a text fixture's header."""
	header, _ = _split_header((FIXTURE_DIR / name).read_text(encoding="utf-8"))
	fields: dict[str, str] = {}
	for line in header:
		stripped = line.lstrip("#").strip()
		if ":" in stripped:
			key, _, value = stripped.partition(":")
			fields.setdefault(key.strip(), value.strip())
	return fields


def load_html(name: str) -> str:
	"""Return an HTML fixture verbatim, provenance comment included.

	The comment is left in place on purpose: the cleaner has to survive it,
	and a fixture that has been tidied up is no longer a test of real markup.
	"""
	return (FIXTURE_DIR / name).read_text(encoding="utf-8")


def text_fixtures() -> list[str]:
	"""Every ``.txt`` fixture name, sorted."""
	return sorted(p.name for p in FIXTURE_DIR.glob("*.txt"))
