"""Rendering a Verdict for a terminal.

Formatting only. Nothing here decides anything about a policy; it presents
what the scorer already decided.

Plain ASCII, no colour by default and no box-drawing characters. This output
gets piped into other tools, pasted into issues and read over SSH, and escape
codes in a pipe are noise. Colour is opt-in via ``--color``.
"""

from __future__ import annotations

import shutil
import textwrap

from core.models import Decision, Finding, Verdict

__all__ = ["render_text", "render_json_ready", "DECISION_LABELS"]

DECISION_LABELS: dict[Decision, str] = {
	Decision.ALLOW: "ALLOW",
	Decision.WARNING: "WARNING",
	Decision.DENY: "DENY",
}

# A short line under the badge saying what the verdict means, because
# "WARNING" on its own does not tell anyone what to do.
_DECISION_BLURB: dict[Decision, str] = {
	Decision.ALLOW: "Nothing in this document matched a red flag.",
	Decision.WARNING: "Read these before you agree.",
	Decision.DENY: "Do not agree to this without reading it in full.",
}

_ANSI = {
	Decision.ALLOW: "\033[32m",
	Decision.WARNING: "\033[33m",
	Decision.DENY: "\033[31m",
}
_RESET = "\033[0m"
_DIM = "\033[2m"


def _width(explicit: int | None = None) -> int:
	if explicit:
		return explicit
	return max(50, min(shutil.get_terminal_size((100, 24)).columns, 100))


def _wrap(text: str, width: int, indent: str) -> list[str]:
	return textwrap.wrap(
		text,
		width=width,
		initial_indent=indent,
		subsequent_indent=" " * len(indent),
	) or [indent.rstrip()]


def render_text(
	verdict: Verdict,
	*,
	color: bool = False,
	verbose: bool = False,
	width: int | None = None,
) -> str:
	"""Render a Verdict as human-readable text.

	``verbose`` adds the clause that triggered each finding, which is the
	terminal equivalent of expanding a row in the UI.
	"""
	columns = _width(width)
	lines: list[str] = []

	label = DECISION_LABELS[verdict.decision]
	if color:
		label = f"{_ANSI[verdict.decision]}{label}{_RESET}"
	lines.append(f"{label}  {_DECISION_BLURB[verdict.decision]}")

	summary = (
		f"{verdict.origin}  |  rule set: {verdict.rule_set}  |  "
		f"risk {verdict.risk_score:g}/100  |  "
		f"{len(verdict.findings)} finding(s) in {verdict.clauses_analyzed} clause(s)"
	)
	lines.extend(_wrap(summary, columns, ""))

	# Printed above the findings, because it changes how they should be read.
	notice = (verdict.metadata.get("relevance") or {}).get("notice")
	if notice:
		lines.append("")
		lines.extend(_wrap(f"Note: {notice}", columns, ""))

	lines.append("")

	if not verdict.reasons:
		lines.append("No red flags matched.")
		return "\n".join(lines)

	# Reasons and findings are ordered identically by the scorer, so a
	# reason and its evidence line up. Findings can outnumber reasons when
	# two clauses produce the same sentence, so index off reasons.
	for position, reason in enumerate(verdict.reasons):
		lines.extend(_wrap(reason, columns, "- "))
		if verbose:
			for finding in _findings_for_reason(verdict, reason):
				lines.append("")
				lines.extend(_evidence(finding, columns, color))
		lines.append("")

	return "\n".join(lines).rstrip() + "\n"


def _findings_for_reason(verdict: Verdict, reason: str) -> list[Finding]:
	return [f for f in verdict.findings if f.reason == reason]


def _evidence(finding: Finding, columns: int, color: bool) -> list[str]:
	dim = _DIM if color else ""
	reset = _RESET if color else ""

	lines: list[str] = []
	meta = f"{finding.rule_id}  [{finding.severity.value}]"
	if finding.reference:
		meta += f"  {finding.reference}"
	lines.append(f"{dim}    {meta}{reset}")

	if finding.clause.index < 0:
		lines.append(f"{dim}    (nothing in the document covers this){reset}")
		return lines

	if finding.clause.heading:
		lines.append(f"{dim}    under: {finding.clause.heading}{reset}")
	for line in _wrap(f'"{finding.clause.text}"', columns - 4, "    "):
		lines.append(f"{dim}{line}{reset}")
	return lines


def render_json_ready(verdict: Verdict) -> dict:
	"""The full Verdict as plain data, ready for ``json.dumps``."""
	return verdict.to_dict()
