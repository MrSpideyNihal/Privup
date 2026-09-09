"""Evaluation harness: how good is the classifier, and at what.

Runnable and rerunnable, not a notebook:

	python -m tests.evaluation            # print a report
	python -m tests.evaluation --json     # machine-readable
	python -m tests.evaluation --failures # show what it got wrong

The labelled set is real policy text with a provenance header, and it is
explicitly marked as an unreviewed bootstrap. Ground truth written by the
system under test is circular; the file says so, and the right response to a
disagreement is to correct the label, not to tune the rule until the number
improves.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.analyzer.base import Classifier
from core.analyzer.composite import default_analyzer
from core.models import Clause
from core.tags import get_tag_set
from tests.evaluation.metrics import Report, build_report

__all__ = ["LABELS_PATH", "load_labels", "evaluate", "Report"]

LABELS_PATH = Path(__file__).parent / "labels.json"


def load_labels(path: Path | None = None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
	"""Return ``(meta, clauses)`` from the labelled set."""
	data = json.loads((path or LABELS_PATH).read_text(encoding="utf-8"))
	return data["meta"], data["clauses"]


def rule_sets_for(entry: dict[str, Any]) -> list[str]:
	"""Which rule sets would actually be applied to this clause.

	``generic`` covers any service and ``loan_app`` supplements it for
	lenders, so a lending clause is evaluated under both. A borrower checking
	a loan app cares about third-party sharing just as much as anyone else.

	Getting this wrong understated recall badly on the first run: lender
	clauses were scored only against ``loan_app``, which has no
	``third_party_sharing`` category, so the classifier was marked down for
	missing something that rule set does not define.
	"""
	if entry["rule_set"] == "loan_app":
		return ["generic", "loan_app"]
	return ["generic"]


def predict(entry: dict[str, Any], classifier: Classifier) -> set[str]:
	"""Categories the classifier assigns to one labelled clause.

	The clause is passed straight to the classifier rather than through a
	driver and summarizer. Those stages are tested elsewhere, and putting
	them in the loop here would mean a segmentation change silently moved the
	classification numbers.

	Document-scope findings are dropped: they are a claim about a whole
	document, and every one of them fires when a single clause is the whole
	document.
	"""
	clause = Clause(text=entry["text"], index=0)
	categories: set[str] = set()
	for name in rule_sets_for(entry):
		findings = classifier.classify([clause], get_tag_set(name), origin="evaluation")
		categories |= {f.category for f in findings if f.clause.index >= 0}
	return categories


def evaluate(classifier: Classifier | None = None, path: Path | None = None) -> Report:
	"""Score ``classifier`` against the labelled set."""
	classifier = classifier or default_analyzer()
	_, clauses = load_labels(path)

	rows = [
		(entry["text"], predict(entry, classifier), set(entry["labels"]))
		for entry in clauses
	]
	return build_report(rows)
