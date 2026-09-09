"""Mirror the rule sets into the extension.

``core/tags/rulesets/*.json`` is the only place a rule is defined anywhere in
this repo. The extension cannot read files outside its own directory, so it
gets a generated JavaScript module embedding the same JSON verbatim.

Two implementations of the same logic drift. That is the normal outcome, and
it would be the worst failure this project could have: two verdicts for the
same policy, differing by platform, with no way to tell which is right. So
this is not a convention anyone has to remember:

	python tools/sync_rulesets.py            # regenerate
	python tools/sync_rulesets.py --check    # fail if out of date

``--check`` runs in the test suite, so a rule change that is not mirrored
fails the build rather than shipping a browser extension that quietly
disagrees with the CLI.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = REPO_ROOT / "core" / "tags" / "rulesets"
TARGET = REPO_ROOT / "extension" / "src" / "core" / "rulesets.generated.js"

BANNER = """\
/* GENERATED FILE - DO NOT EDIT.
 *
 * Mirror of core/tags/rulesets/*.json, which is the single definition of a
 * rule anywhere in this repo. Regenerate with:
 *
 *     python tools/sync_rulesets.py
 *
 * A test runs `--check` and fails if this file is out of date, so the
 * extension cannot quietly disagree with the CLI about what a policy says.
 *
 * To add or change a rule, edit the JSON. Never edit this file.
 */
"""


def build() -> str:
	"""Render the generated module."""
	rule_sets: dict[str, object] = {}
	for path in sorted(SOURCE_DIR.glob("*.json")):
		data = json.loads(path.read_text(encoding="utf-8"))
		rule_sets[data["name"]] = data

	if not rule_sets:
		raise SystemExit(f"no rule sets found in {SOURCE_DIR}")

	# sort_keys so the output is stable and a diff shows a real change rather
	# than dictionary ordering.
	body = json.dumps(rule_sets, indent=2, ensure_ascii=False, sort_keys=True)
	return f"{BANNER}\nexport const RULE_SETS = {body};\n"


def main(argv=None) -> int:
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument(
		"--check",
		action="store_true",
		help="exit non-zero if the generated file is out of date, and change nothing",
	)
	args = parser.parse_args(argv)

	expected = build()

	if args.check:
		current = TARGET.read_text(encoding="utf-8") if TARGET.exists() else ""
		if current != expected:
			print(
				"extension rule sets are out of date.\n"
				"A rule changed in core/tags/rulesets/ without being mirrored, so the "
				"browser extension would disagree with the CLI.\n"
				"Run: python tools/sync_rulesets.py",
				file=sys.stderr,
			)
			return 1
		print("extension rule sets are in sync")
		return 0

	TARGET.parent.mkdir(parents=True, exist_ok=True)
	TARGET.write_text(expected, encoding="utf-8")
	names = ", ".join(sorted(json.loads(
		expected.split("export const RULE_SETS = ", 1)[1].rstrip(";\n")
	)))
	print(f"wrote {TARGET.relative_to(REPO_ROOT)} ({names})")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
