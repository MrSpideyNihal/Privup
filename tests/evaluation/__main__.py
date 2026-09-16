"""Print an evaluation report.

	python -m tests.evaluation
	python -m tests.evaluation --json
	python -m tests.evaluation --failures
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in (None, ""):  # pragma: no cover
	sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.evaluation import evaluate, load_labels


def main(argv=None) -> int:
	parser = argparse.ArgumentParser(prog="tests.evaluation")
	parser.add_argument("--json", action="store_true", help="machine-readable output")
	parser.add_argument("--failures", action="store_true", help="show what it got wrong")
	args = parser.parse_args(argv)

	meta, clauses = load_labels()
	report = evaluate()

	if args.json:
		print(json.dumps({"meta": meta, "report": report.to_dict()}, indent=2))
		return 0

	positives = sum(1 for c in clauses if c["labels"])
	print(f"PrivUp classification baseline")
	print(f"{len(clauses)} labelled clauses  |  {positives} positive  |  "
		  f"{len(clauses) - positives} negative")
	print(f"labels: {meta['review_status']}\n")

	print(f"{'category':24} {'support':>7} {'flagged':>7} {'prec':>6} {'recall':>7} {'f1':>6}")
	print("-" * 62)
	for name, counts in sorted(report.by_category.items()):
		print(f"{name:24} {counts.support:>7} {counts.predicted:>7} "
			  f"{counts.precision:>6.2f} {counts.recall:>7.2f} {counts.f1:>6.2f}")

	micro, macro = report.micro, report.macro()
	print("-" * 62)
	print(f"{'micro average':24} {micro.support:>7} {micro.predicted:>7} "
		  f"{micro.precision:>6.2f} {micro.recall:>7.2f} {micro.f1:>6.2f}")
	print(f"{'macro average':24} {'':>7} {'':>7} "
		  f"{macro['precision']:>6.2f} {macro['recall']:>7.2f} {macro['f1']:>6.2f}")

	if args.failures:
		for kind in ("false_positive", "false_negative"):
			rows = report.examples.get(kind, [])
			if not rows:
				continue
			print(f"\n{kind.replace('_', ' ')}s ({len(rows)} shown)")
			for row in rows:
				print(f"  [{row['category']}] {row['text'][:130]}")

	return 0


if __name__ == "__main__":
	raise SystemExit(main())
