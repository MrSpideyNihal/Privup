"""
#############################################################
#                                                           #
#   PRIVUP: Privacy Policy Analysis and Scoring Framework   #
#                                                           #
#############################################################

Pipeline orchestration.

	driver.fetch()  ->  summarizer.clean()  ->  analyzer.classify()  ->  scorer.score()

This module wires four stages together and does nothing else. It holds no
knowledge of HTTP, of HTML, of RBI, or of what a red flag is. Adding a driver
or a rule set does not change this file, which is the property that makes the
rest of the design worth having.

Everything runs on the device. The only outbound call in the whole pipeline
happens inside a driver's ``fetch``, and the built-in ``raw_text`` driver
makes none at all.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

# Support direct execution: python core/main.py
if __package__ is None or __package__ == "":
	sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.analyzer.simple import RuleAnalyzer
from core.models import Verdict
from core.scorer.scorer import Scorer
from core.scraper import available_drivers, get_driver
from core.summarizer.simple import SimpleSummarizer
from core.tags import available_tag_sets, get_tag_set
from core.tags.relevance import check_relevance

__all__ = ["run", "run_pipeline"]


def run(driver_name: str, target: str, tag_set_name: str) -> Verdict:
	"""Analyze ``target`` with ``driver_name`` against ``tag_set_name``.

	Raises ``UnknownDriverError`` or ``UnknownTagSetError`` for a bad name,
	and ``DriverError`` when the target cannot be read. Those are surfaced
	rather than swallowed: a caller that asked for a check and silently got
	an Allow because the fetch failed has been actively misled.
	"""
	driver = get_driver(driver_name)
	rule_set = get_tag_set(tag_set_name)

	result = driver.fetch(target)
	clauses = SimpleSummarizer().clean(result)
	findings = RuleAnalyzer().classify(clauses, rule_set, origin=result.origin)

	verdict = Scorer().score(
		findings,
		rule_set=rule_set.name,
		origin=result.origin,
		clauses_analyzed=len(clauses),
	)

	# Advisory, never a veto. Running a rule set against something it was not
	# written for is allowed, and sometimes deliberate, but the user should be
	# told when the fit looks wrong rather than handed a confident verdict on
	# the wrong grounds. Attached here rather than in the scorer so scoring
	# stays purely a function of the findings.
	relevance = check_relevance(clauses, rule_set)
	if not relevance.applies:
		verdict = replace(
			verdict,
			metadata={**verdict.metadata, "relevance": relevance.to_dict()},
		)

	return verdict


def run_pipeline(target: str, tag_set_name: str = "generic", driver_name: str = "raw_text") -> Verdict:
	"""Convenience wrapper with the argument order most callers want."""
	return run(driver_name=driver_name, target=target, tag_set_name=tag_set_name)


def _format_text(verdict: Verdict) -> str:
	lines = [f"{verdict.decision.value.upper()}  ({verdict.origin})"]
	lines.append(
		f"risk {verdict.risk_score:g}/100 from {len(verdict.findings)} finding(s) "
		f"across {verdict.clauses_analyzed} clause(s), rule set '{verdict.rule_set}'"
	)
	if not verdict.reasons:
		lines.append("No red flags matched.")
	for reason in verdict.reasons:
		lines.append(f"  - {reason}")
	return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
	parser = argparse.ArgumentParser(
		description="Run the PrivUp pipeline. A fuller command line lives in cli/."
	)
	parser.add_argument("target", nargs="?", help="URL, or policy text, depending on --driver")
	parser.add_argument("--driver", default="raw_text", help="driver name")
	parser.add_argument("--tags", default="generic", help="rule set name")
	parser.add_argument("--format", default="text", choices=["text", "json"])
	parser.add_argument("--list-drivers", action="store_true")
	parser.add_argument("--list-tags", action="store_true")
	return parser


def main() -> int:
	args = build_parser().parse_args()

	if args.list_drivers:
		print("\n".join(available_drivers()))
		return 0
	if args.list_tags:
		print("\n".join(available_tag_sets()))
		return 0
	if not args.target:
		build_parser().error("a target is required unless listing drivers or rule sets")

	verdict = run(args.driver, args.target, args.tags)

	if args.format == "json":
		print(json.dumps(verdict.to_dict(), indent=2))
	else:
		print(_format_text(verdict))

	# Non-zero on Deny so this is usable from a script.
	return 1 if verdict.is_blocking else 0


if __name__ == "__main__":
	raise SystemExit(main())
