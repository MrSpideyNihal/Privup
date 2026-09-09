"""``privup`` command line entry point.

Wraps ``core.main.run`` and nothing else. Every decision about what a policy
means is made inside ``core``; this module chooses an output format and an
exit status.

Exit status is part of the contract, because the point of a scriptable
interface is that a script can branch on it:

	0  allow, or warning
	1  deny
	2  bad usage (argparse)
	3  could not complete: unreachable target, unknown driver or rule set

Deny and "could not check" are deliberately different. A build that fails
because a policy is bad and a build that fails because a URL 404'd need
different responses from whoever reads the log.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Sequence

from core.main import run
from core.models import Decision
from core.scraper import DriverError, UnknownDriverError, available_drivers, describe_drivers
from core.tags import UnknownTagSetError, available_tag_sets, describe_tag_sets
from cli.format import render_text

__all__ = ["build_parser", "main"]

EXIT_OK = 0
EXIT_DENY = 1
EXIT_USAGE = 2
EXIT_ERROR = 3

_STDIN_TARGET = "-"

_EPILOG = """\
exit status:
  0  allow or warning
  1  deny
  2  bad usage
  3  could not complete the check (unreachable target, unknown driver or rule set)

examples:
  privup scan "We access your contact list." --tags loan_app
  privup scan https://example.com --driver url --tags generic --format json
  cat policy.txt | privup scan - --tags generic
  privup --list-tags
"""


def build_parser() -> argparse.ArgumentParser:
	parser = argparse.ArgumentParser(
		prog="privup",
		description="Analyze a privacy policy or loan agreement on your device.",
		epilog=_EPILOG,
		formatter_class=argparse.RawDescriptionHelpFormatter,
	)

	# Listing flags sit on the root parser so they work without a subcommand,
	# which is what makes them usable as a quick check that a contributor's
	# new rule set or driver is actually being discovered.
	parser.add_argument(
		"--list-tags",
		action="store_true",
		help="list available rule sets and exit",
	)
	parser.add_argument(
		"--list-drivers",
		action="store_true",
		help="list available drivers and exit",
	)

	subparsers = parser.add_subparsers(dest="command")
	scan = subparsers.add_parser(
		"scan",
		help="analyze a target",
		description="Analyze a target and print a verdict.",
		epilog=_EPILOG,
		formatter_class=argparse.RawDescriptionHelpFormatter,
	)
	scan.add_argument(
		"target",
		help=f"a URL, policy text, or {_STDIN_TARGET!r} to read text from stdin",
	)
	scan.add_argument(
		"--driver",
		default="raw_text",
		choices=available_drivers(),
		help="where to read the policy from (default: raw_text)",
	)
	scan.add_argument(
		"--tags",
		default="generic",
		choices=available_tag_sets(),
		metavar="RULESET",
		help=f"rule set to apply, one of {{{','.join(available_tag_sets())}}} (default: generic)",
	)
	scan.add_argument(
		"--format",
		default="text",
		choices=["text", "json"],
		help="output format (default: text)",
	)
	scan.add_argument(
		"--verbose",
		action="store_true",
		help="in text format, also print the clause behind each finding",
	)
	scan.add_argument(
		"--color",
		action="store_true",
		help="colourise the verdict line (off by default so pipes stay clean)",
	)
	scan.add_argument(
		"--quiet",
		action="store_true",
		help="print nothing; rely on the exit status",
	)
	return parser


def _read_target(target: str) -> str:
	"""Resolve the stdin sentinel. Never prompts."""
	if target != _STDIN_TARGET:
		return target
	if sys.stdin is None or sys.stdin.isatty():
		# Reading here would block waiting for a human, and this tool must
		# never sit at an interactive prompt.
		raise DriverError(
			"'-' means read the policy from stdin, but stdin is a terminal. "
			"Pipe text in, or pass the text as the argument."
		)
	return sys.stdin.read()


def _list(pairs, stream) -> int:
	width = max((len(name) for name, *_ in pairs), default=0)
	for name, description, *rest in pairs:
		suffix = f" ({rest[0]} rules)" if rest else ""
		print(f"{name.ljust(width)}  {description}{suffix}", file=stream)
	return EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
	parser = build_parser()
	args = parser.parse_args(argv)

	if args.list_tags:
		return _list(list(describe_tag_sets()), sys.stdout)
	if args.list_drivers:
		return _list(list(describe_drivers()), sys.stdout)

	if args.command != "scan":
		parser.print_help()
		return EXIT_USAGE

	try:
		target = _read_target(args.target)
		verdict = run(args.driver, target, args.tags)
	except (UnknownDriverError, UnknownTagSetError) as exc:
		# KeyError stringifies with quotes around the whole message.
		print(f"privup: {exc.args[0]}", file=sys.stderr)
		return EXIT_ERROR
	except DriverError as exc:
		print(f"privup: {exc}", file=sys.stderr)
		return EXIT_ERROR

	if not args.quiet:
		if args.format == "json":
			print(json.dumps(verdict.to_dict(), indent=2))
		else:
			print(render_text(verdict, color=args.color, verbose=args.verbose), end="")

	return EXIT_DENY if verdict.decision is Decision.DENY else EXIT_OK


if __name__ == "__main__":
	raise SystemExit(main())
