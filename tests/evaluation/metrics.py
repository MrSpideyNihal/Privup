"""Precision, recall and F1 for clause classification.

Deliberately small and dependency-free. The arithmetic is not the hard part of
evaluation; deciding what counts as correct is, so that decision is written
down here rather than buried in a runner.

Two choices worth stating.

Evaluation is per clause per category, not per rule. Two rules reaching the
same conclusion about the same sentence is one correct answer, not two, and a
metric that rewarded firing many rules would reward writing many rules.

Document-scope findings are excluded. "This policy never mentions how to opt
out" is a claim about a whole document, and scoring it against a single
labelled clause would measure the wrong mechanism and flatter the classifier
besides: run one clause through the pipeline and every absence rule fires.
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = ["Counts", "Report", "score_category", "build_report"]


@dataclass(frozen=True, slots=True)
class Counts:
	"""Confusion counts for one category."""

	true_positives: int = 0
	false_positives: int = 0
	false_negatives: int = 0

	@property
	def support(self) -> int:
		"""How many clauses were actually labelled with this category."""
		return self.true_positives + self.false_negatives

	@property
	def predicted(self) -> int:
		return self.true_positives + self.false_positives

	@property
	def precision(self) -> float:
		"""Of what we flagged, how much was right.

		Defined as 1.0 when nothing was flagged: a classifier that stays
		silent has told no lies. Recall is what punishes it.
		"""
		if self.predicted == 0:
			return 1.0
		return self.true_positives / self.predicted

	@property
	def recall(self) -> float:
		"""Of what was there, how much we found."""
		if self.support == 0:
			return 1.0
		return self.true_positives / self.support

	@property
	def f1(self) -> float:
		precision, recall = self.precision, self.recall
		if precision + recall == 0:
			return 0.0
		return 2 * precision * recall / (precision + recall)

	def to_dict(self) -> dict[str, float | int]:
		return {
			"true_positives": self.true_positives,
			"false_positives": self.false_positives,
			"false_negatives": self.false_negatives,
			"support": self.support,
			"precision": round(self.precision, 4),
			"recall": round(self.recall, 4),
			"f1": round(self.f1, 4),
		}


@dataclass
class Report:
	"""Per-category counts plus the two aggregate views."""

	by_category: dict[str, Counts] = field(default_factory=dict)
	examples: dict[str, list[dict]] = field(default_factory=dict)

	@property
	def micro(self) -> Counts:
		"""Pool every decision. Dominated by common categories."""
		return Counts(
			sum(c.true_positives for c in self.by_category.values()),
			sum(c.false_positives for c in self.by_category.values()),
			sum(c.false_negatives for c in self.by_category.values()),
		)

	def macro(self) -> dict[str, float]:
		"""Average the per-category scores. Treats rare categories equally.

		Reported alongside micro because they disagree in a way that matters
		here: a rare category like a disallowed permission is the one a
		borrower most needs, and micro would let it disappear.
		"""
		scored = [c for c in self.by_category.values() if c.support or c.predicted]
		if not scored:
			return {"precision": 1.0, "recall": 1.0, "f1": 0.0}
		count = len(scored)
		return {
			"precision": round(sum(c.precision for c in scored) / count, 4),
			"recall": round(sum(c.recall for c in scored) / count, 4),
			"f1": round(sum(c.f1 for c in scored) / count, 4),
		}

	def to_dict(self) -> dict:
		return {
			"micro": self.micro.to_dict(),
			"macro": self.macro(),
			"by_category": {k: v.to_dict() for k, v in sorted(self.by_category.items())},
		}


def score_category(predicted: set[str], actual: set[str], category: str) -> tuple[int, int, int]:
	"""Return ``(tp, fp, fn)`` contributions for one clause and one category."""
	is_predicted = category in predicted
	is_actual = category in actual
	return (
		int(is_predicted and is_actual),
		int(is_predicted and not is_actual),
		int(not is_predicted and is_actual),
	)


def build_report(
	rows: list[tuple[str, set[str], set[str]]],
	keep_examples: int = 4,
) -> Report:
	"""Build a report from ``(clause_text, predicted, actual)`` rows.

	Keeps a few worked examples per failure kind. A number tells you the
	classifier got worse; an example tells you why, and without one nobody
	acts on the number.
	"""
	categories: set[str] = set()
	for _, predicted, actual in rows:
		categories |= predicted | actual

	report = Report()
	for category in sorted(categories):
		tp = fp = fn = 0
		for text, predicted, actual in rows:
			one_tp, one_fp, one_fn = score_category(predicted, actual, category)
			tp += one_tp
			fp += one_fp
			fn += one_fn

			if one_fp and len(report.examples.setdefault("false_positive", [])) < keep_examples * 4:
				report.examples["false_positive"].append({"category": category, "text": text})
			if one_fn and len(report.examples.setdefault("false_negative", [])) < keep_examples * 4:
				report.examples["false_negative"].append({"category": category, "text": text})

		report.by_category[category] = Counts(tp, fp, fn)

	return report
