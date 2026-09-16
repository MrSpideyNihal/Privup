# /*
#  *  ╔════════════════════════════════════════════════════════════╗
#  *  ║                                                            ║
#  *  ║                     PRIVACY-URL-FINDER                     ║
#  *  ║                                                            ║
#  *  ║                         by Nihal Rodge                     ║
#  *  ║                                                            ║
#  *  ║  GitHub: github.com/MrSpideyNihal/privacy-url-finder       ║
#  *  ║                                                            ║
#  *  ╚════════════════════════════════════════════════════════════╝
#  */
#
# This code was integrated from privacy-url-finder:
# https://github.com/MrSpideyNihal/privacy-url-finder
#

"""Command line interface for Privacy URL Finder."""

import argparse
import json
import logging
import sys
import time
from typing import List

from .dataset.manager import DatasetManager
from .finder import PrivacyURLFinder
from .models import PolicyResult, ResolutionStatus


if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def format_text_result(res: PolicyResult, verbose: bool = False) -> str:
    """Format single result for terminal display."""
    lines = []
    if res.status == ResolutionStatus.FOUND:
        status_icon = "+"
    elif res.status in (ResolutionStatus.PROBABLE, ResolutionStatus.UNVERIFIED):
        status_icon = "~"
    else:
        status_icon = "x"
    lines.append(f"[{status_icon}] Query: {res.query}")
    lines.append(f"    Status:     {res.status.value}")
    lines.append(f"    Policy URL: {res.url or 'Not found'}")
    lines.append(f"    Confidence: {res.confidence * 100:.1f}%")
    lines.append(f"    Method:     {res.method} (Source: {res.source.value if res.source else 'None'})")

    if res.entity_name:
        lines.append(f"    Entity:     {res.entity_name}")
    if res.domain:
        lines.append(f"    Domain:     {res.domain}")
    if res.title:
        lines.append(f"    Title:      {res.title}")

    if verbose and res.validation:
        lines.append("    Validation Signals:")
        for sig in res.validation.signals:
            lines.append(f"      - {sig}")
        if res.validation.rejection_reason:
            lines.append(f"      - Rejection: {res.validation.rejection_reason}")

    if res.metadata and verbose:
        lines.append("    Metadata:")
        for k, v in res.metadata.items():
            if v:
                lines.append(f"      {k}: {v}")

    lines.append(f"    Elapsed:    {res.elapsed_ms:.1f}ms")
    return "\n".join(lines)


def cmd_find(args: argparse.Namespace) -> int:
    finder = PrivacyURLFinder(
        verify=not args.no_verify,
        timeout=args.timeout,
        enable_search_fallback=not args.no_search,
    )

    res = finder.find(args.query)

    if args.format == "json":
        print(json.dumps(res.to_dict(), indent=2))
    else:
        print(format_text_result(res, verbose=args.verbose))

    return 0 if res.status in (ResolutionStatus.FOUND, ResolutionStatus.PROBABLE, ResolutionStatus.UNVERIFIED) else 1


def cmd_batch(args: argparse.Namespace) -> int:
    finder = PrivacyURLFinder(
        verify=not args.no_verify,
        timeout=args.timeout,
    )

    with open(args.file, "r", encoding="utf-8") as f:
        queries = [line.strip() for line in f if line.strip() and not line.startswith("#")]

    results = []
    print(f"Resolving {len(queries)} queries...", file=sys.stderr)
    for q in queries:
        r = finder.find(q)
        results.append(r)
        if args.format != "json":
            print(format_text_result(r, verbose=args.verbose))
            print("-" * 60)

    if args.format == "json":
        data = [r.to_dict() for r in results]
        if args.output:
            with open(args.output, "w", encoding="utf-8") as out_f:
                json.dump(data, out_f, indent=2)
            print(f"Wrote results to {args.output}", file=sys.stderr)
        else:
            print(json.dumps(data, indent=2))

    return 0


def cmd_dataset(args: argparse.Namespace) -> int:
    dm = DatasetManager()
    if args.dataset_action == "search":
        items = dm.search(args.term)
        if args.format == "json":
            print(json.dumps(items, indent=2))
        else:
            print(f"Found {len(items)} matching entities in curated dataset:")
            for item in items:
                nbfc_info = f" (NBFC: {item['regulated_nbfc']})" if item.get("regulated_nbfc") else ""
                print(f"  * {item['name']} [{item.get('category', 'general')}]{nbfc_info}")
                print(f"    Domain:  {item.get('domain')}")
                print(f"    Privacy: {item.get('privacy_url')}")
                if item.get("aliases"):
                    print(f"    Aliases: {', '.join(item['aliases'][:5])}")
                print()
    elif args.dataset_action == "list":
        if args.format == "json":
            print(json.dumps(dm.entries, indent=2))
        else:
            print(f"Curated Dataset Catalog ({len(dm.entries)} entries):")
            for item in dm.entries:
                print(f"  * {item['name']:<25} | {item.get('category', ''):<15} | {item.get('privacy_url')}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="privacy-url-finder",
        description="Privacy URL Finder - Intelligent privacy policy URL discovery and verification engine.",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # Command: find
    find_p = subparsers.add_parser("find", help="Find privacy policy URL for a company, app, or website")
    find_p.add_argument("query", help="Company name, app name, Android package ID, or domain/URL")
    find_p.add_argument("--format", choices=["text", "json"], default="text", help="Output format")
    find_p.add_argument("--verbose", "-v", action="store_true", help="Show validation signals and extra details")
    find_p.add_argument("--no-verify", action="store_true", help="Skip HTTP body policy validation")
    find_p.add_argument("--no-search", action="store_true", help="Disable web search engine fallback")
    find_p.add_argument("--timeout", type=float, default=6.0, help="HTTP request timeout in seconds")
    find_p.add_argument("--debug", action="store_true", help="Enable debug logging")

    # Command: batch
    batch_p = subparsers.add_parser("batch", help="Batch find privacy policies from a file of queries")
    batch_p.add_argument("file", help="Path to text file with one query per line")
    batch_p.add_argument("--output", "-o", help="Optional output JSON file path")
    batch_p.add_argument("--format", choices=["text", "json"], default="text", help="Output format")
    batch_p.add_argument("--verbose", "-v", action="store_true", help="Verbose details")
    batch_p.add_argument("--no-verify", action="store_true", help="Skip HTTP body policy validation")
    batch_p.add_argument("--timeout", type=float, default=6.0, help="HTTP timeout")
    batch_p.add_argument("--debug", action="store_true", help="Enable debug logging")

    # Command: dataset
    dataset_p = subparsers.add_parser("dataset", help="Inspect and search curated dataset")
    dataset_sub = dataset_p.add_subparsers(dest="dataset_action", required=True)
    d_search = dataset_sub.add_parser("search", help="Search dataset by keyword")
    d_search.add_argument("term", help="Search keyword")
    d_search.add_argument("--format", choices=["text", "json"], default="text")

    d_list = dataset_sub.add_parser("list", help="List all catalog entries")
    d_list.add_argument("--format", choices=["text", "json"], default="text")

    # Command: ui / gui
    subparsers.add_parser("ui", help="Launch native desktop GUI application")
    subparsers.add_parser("gui", help="Launch native desktop GUI application")
    subparsers.add_parser("tui", help="Launch interactive Rich terminal UI")
    subparsers.add_parser("interactive", help="Launch interactive Rich terminal UI")

    return parser


def main() -> None:
    parser = build_parser()
    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(0)

    args = parser.parse_args()
    if getattr(args, "debug", False):
        logging.basicConfig(level=logging.DEBUG, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    else:
        logging.basicConfig(level=logging.WARNING, format="[%(levelname)s] %(message)s")

    if args.command == "find":
        sys.exit(cmd_find(args))
    elif args.command == "batch":
        sys.exit(cmd_batch(args))
    elif args.command == "dataset":
        sys.exit(cmd_dataset(args))
    elif args.command in ("ui", "gui"):
        from .ui import launch_gui
        launch_gui()
        sys.exit(0)
    elif args.command in ("tui", "interactive"):
        from .interactive import run_interactive_tui
        run_interactive_tui()
        sys.exit(0)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
