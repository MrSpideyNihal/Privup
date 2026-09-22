"""Turn findings into one of three answers a person can act on.

The decision rule is deliberately blunt:

	no findings            -> Allow
	any critical finding   -> Deny
	anything else          -> Warning

Blunt because this output is read in the two seconds before someone taps
Accept. A nuanced five-band score would be more defensible on paper and
useless at a consent dialog.

Critical is the only thing that denies, and nothing accumulates into a Deny.
That is a considered choice rather than an oversight. Severities are assigned
by rule authors, and a scorer that escalated on volume would let a rule set
with many medium rules out-vote one with few precise ones, which rewards
writing more rules rather than better ones. It would also be unstable here in
particular: the ``loan_app`` set contributes two high-severity absence
findings to almost any document, so a "three highs deny" rule would deny
nearly everything and the verdict would stop meaning anything.

``risk_score`` exists for sorting and for showing change over time. It is not
the verdict and must never be presented as one.
"""

from __future__ import annotations

from core.models import Decision, Finding, Severity, Verdict

__all__ = ["Scorer", "SEVERITY_WEIGHTS", "DENY_AT"]

# Contribution of one finding to the 0-100 risk score. Spaced so that a
# critical finding alone dominates a handful of mediums, matching the fact
# that one disallowed permission matters more than several vague clauses.
SEVERITY_WEIGHTS: dict[Severity, float] = {
	Severity.INFO: 1.0,
	Severity.LOW: 3.0,
	Severity.MEDIUM: 8.0,
	Severity.HIGH: 18.0,
	Severity.CRITICAL: 40.0,
}

#: The severity at which a verdict becomes Deny.
DENY_AT = Severity.CRITICAL

# Worst first, then document order, so the reason a user reads first is the
# reason that matters most.
def _rank(finding: Finding) -> tuple[int, int]:
	return (-finding.severity.rank, finding.clause.index)


RULE_LABELS: dict[str, str] = {
	"gdpr.retention.indefinite": "indefinite data retention",
	"gdpr.retention.vague": "vague retention limits",
	"gdpr.sharing.sale": "selling personal data",
	"gdpr.sharing.third_party": "third-party data sharing",
	"gdpr.tracking.profiling": "user profiling",
	"gdpr.tracking.cross_site": "cross-site tracking",
	"gdpr.tracking.targeted_ads": "targeted advertising",
	"ai.training_on_user_content": "AI training on user content",
	"gdpr.consent.bundled": "bundled agreement",
	"gdpr.change.unilateral": "terms changed without notice",
	"gdpr.transfer.cross_border": "overseas data transfer",
	"gdpr.security.disclaimed": "disclaimed security liability",
	"gdpr.optout.absent": "no opt-out or deletion options",
	"rbi.permission.contacts": "reads phone contacts",
	"rbi.permission.call_logs": "reads call logs",
	"rbi.permission.sms": "reads text messages",
	"rbi.permission.files_media": "accesses device files",
	"rbi.permission.installed_apps": "inspects installed apps",
	"rbi.permission.one_time_unqualified": "continuous device access",
	"rbi.charges.interest_high": "high interest rates",
	"rbi.charges.penal_daily": "daily penal interest",
	"rbi.charges.non_refundable_fee": "non-refundable fees",
	"rbi.charges.processing_fee": "processing fee deductions",
	"rbi.charges.cooling_off_charged": "cooling-off exit fee",
	"rbi.charges.foreclosure_penalty": "early repayment penalty",
	"rbi.charges.undisclosed": "undisclosed open charges",
	"rbi.recovery.third_party_agents": "third-party debt recovery",
	"rbi.consent.no_withdrawal": "no consent withdrawal",
	"rbi.disclosure.no_lender_named": "unnamed regulated lender",
	"rbi.consent.bundled": "bundled consent",
}


def generate_headline(ordered_findings: list[Finding]) -> str | None:
	"""Build a short human-readable summary of all findings for the verdict heading."""
	if not ordered_findings:
		return None

	seen: set[str] = set()
	topics: list[str] = []
	for f in ordered_findings:
		label = RULE_LABELS.get(f.rule_id) or (f.category.replace("_", " ") if f.category else None)
		if label and label not in seen:
			seen.add(label)
			topics.append(label)

	if not topics:
		fallback = ordered_findings[0].reason.rstrip(". ") if ordered_findings[0].reason else ""
		return fallback or "Concerns detected in policy."

	if len(topics) == 1:
		t = topics[0]
		return t[:1].upper() + t[1:] + " flagged."

	displayed = topics[:3]
	remaining = len(topics) - len(displayed)
	if len(displayed) == 2:
		text = f"{displayed[0]} and {displayed[1]}"
	else:
		text = f"{displayed[0]}, {displayed[1]}, and {displayed[2]}"

	if remaining > 0:
		text += f" (+{remaining} more)"

	return text[:1].upper() + text[1:] + "."


class Scorer:
	"""Produce a Verdict from a list of findings."""

	def score(
		self,
		findings: list[Finding],
		rule_set: str,
		origin: str,
		clauses_analyzed: int = 0,
	) -> Verdict:
		ordered = sorted(findings, key=_rank)

		if not ordered:
			return self._clean(rule_set, origin, clauses_analyzed)

		worst = max(f.severity for f in ordered)
		decision = Decision.DENY if worst >= DENY_AT else Decision.WARNING

		# Two rules can reach the same conclusion about a document. The user
		# does not need to be told the same thing twice, but the findings
		# behind both are kept so the evidence is still there to expand.
		reasons: list[str] = []
		seen: set[str] = set()
		for finding in ordered:
			if finding.reason not in seen:
				seen.add(finding.reason)
				reasons.append(finding.reason)

		counts: dict[str, int] = {}
		for finding in ordered:
			counts[finding.severity.value] = counts.get(finding.severity.value, 0) + 1

		return Verdict(
			decision=decision,
			rule_set=rule_set,
			origin=origin,
			reasons=reasons,
			findings=ordered,
			risk_score=self._risk_score(ordered),
			clauses_analyzed=clauses_analyzed,
			metadata={
				"severity_counts": counts,
				"worst_severity": worst.value,
				"categories": sorted({f.category for f in ordered}),
				"headline": generate_headline(ordered),
			},
		)

	@staticmethod
	def _risk_score(findings: list[Finding]) -> float:
		total = sum(SEVERITY_WEIGHTS[f.severity] * f.confidence for f in findings)
		return round(min(100.0, total), 1)

	@staticmethod
	def _clean(rule_set: str, origin: str, clauses_analyzed: int) -> Verdict:
		"""No findings. Allow, unless nothing was actually read.

		A document that produced no clauses produced no findings either, and
		reporting Allow for it would be the worst bug this project could
		ship: a confident green light for a page nobody managed to read.
		Several live lending sites render their policy entirely in
		JavaScript and return a near-empty document to a plain fetch, so this
		is a routine case, not a defensive branch.
		"""
		if clauses_analyzed == 0:
			return Verdict(
				decision=Decision.WARNING,
				rule_set=rule_set,
				origin=origin,
				reasons=[
					"No readable policy text was found here, so nothing could be "
					"checked. This is not an all-clear."
				],
				findings=[],
				risk_score=0.0,
				clauses_analyzed=0,
				metadata={"empty_document": True, "headline": "No readable policy text found here."},
			)

		return Verdict(
			decision=Decision.ALLOW,
			rule_set=rule_set,
			origin=origin,
			reasons=[],
			findings=[],
			risk_score=0.0,
			clauses_analyzed=clauses_analyzed,
			metadata={"severity_counts": {}, "categories": [], "headline": "No red flags detected in this policy."},
		)
