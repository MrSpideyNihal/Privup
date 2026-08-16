"""
#############################################################
#                                                           #
#   PRIVUP: Privacy Policy Analysis and Scoring Framework   #
#                                                           #
#############################################################
#                                                           #
#                                                           #
#                                                           #
#############################################################

"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Support direct execution: python core/main.py
if __package__ is None or __package__ == "":
	sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.analyzer.simple import SimpleAnalyzer
from core.scorer.scorer import Scorer
from core.scraper.extractor import Extractor
from core.scraper.fetcher import Fetcher
from core.scraper.resolver import Resolver
from core.summarizer.simple import SimpleSummarizer


def run_pipeline(service_or_url: str, tags: list[str] | None = None) -> dict:
	"""Execute the baseline pipeline and return a structured result."""
	resolver = Resolver()
	fetcher = Fetcher()
	extractor = Extractor()
	analyzer = SimpleAnalyzer()
	summarizer = SimpleSummarizer()
	scorer = Scorer()

	policy_url = resolver.resolve_policy_url(service_or_url)
	raw = fetcher.fetch(policy_url)
	extracted = extractor.extract(raw)
	findings = analyzer.analyze(extracted, tags)
	summary = summarizer.summarize(extracted, tags)
	score = scorer.score(findings)

	return {
		"input": service_or_url,
		"resolved_policy_url": policy_url,
		"score": score,
		"summary": summary,
		"findings": findings,
	}


def build_parser() -> argparse.ArgumentParser:
	"""Create command-line parser for the PrivUp skeleton runner."""
	parser = argparse.ArgumentParser(description="Run the PrivUp pipeline skeleton")
	parser.add_argument("service", help="Service name or URL")
	parser.add_argument(
		"--tags",
		default="",
		help="Comma-separated tags, e.g. camera,location,ads",
	)
	return parser


def main() -> None:
	"""CLI main function."""
	parser = build_parser()
	args = parser.parse_args()
	tags = [t.strip() for t in args.tags.split(",") if t.strip()]

	result = run_pipeline(args.service, tags)
	print(json.dumps(result, indent=2))


if __name__ == "__main__":
	main()
