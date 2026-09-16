"""Rule-set registry.

Rule sets live as JSON files in ``core/tags/rulesets/``. The registry finds
them by globbing that directory, so contributing a rule set means adding one
file and nothing else. No import to add, no dictionary to extend, and in
particular nothing to change in ``core/analyzer``.

Rule sets registered from Python are also supported, for a package that wants
to ship rules without writing a file into this repo.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator, Mapping

from core.tags.rules import RuleSet, RuleSetError, load_rule_set, parse_rule_set

__all__ = [
	"RULESET_DIR",
	"available_tag_sets",
	"describe_tag_sets",
	"get_tag_set",
	"register_tag_set",
	"reload_tag_sets",
	"UnknownTagSetError",
]

RULESET_DIR = Path(__file__).parent / "rulesets"

_LOADED: dict[str, RuleSet] = {}
_REGISTERED: dict[str, RuleSet] = {}
_SCANNED = False


class UnknownTagSetError(KeyError):
	"""Asked for a rule set that is not on disk and was not registered."""

	def __init__(self, name: str) -> None:
		known = ", ".join(available_tag_sets()) or "none"
		super().__init__(f"unknown rule set {name!r}; available rule sets: {known}")
		self.name = name


def _scan() -> None:
	"""Load every rule set file once, on first use.

	A malformed file raises rather than being skipped. A rule set that fails
	to load silently would mean the pipeline quietly analyzing against fewer
	rules than the operator thinks, which is the failure mode this whole
	project exists to prevent.
	"""
	global _SCANNED
	if _SCANNED:
		return

	if RULESET_DIR.is_dir():
		for path in sorted(RULESET_DIR.glob("*.json")):
			rule_set = load_rule_set(path)
			if rule_set.name in _LOADED:
				raise RuleSetError(
					f"{path.name}: rule set name {rule_set.name!r} is already "
					f"defined by another file"
				)
			_LOADED[rule_set.name] = rule_set
	_SCANNED = True


def register_tag_set(rule_set: RuleSet | Mapping[str, object], source: str = "<registered>") -> RuleSet:
	"""Register a rule set from Python rather than from a file."""
	if not isinstance(rule_set, RuleSet):
		rule_set = parse_rule_set(rule_set, source=source)
	_REGISTERED[rule_set.name] = rule_set
	return rule_set


def get_tag_set(name: str) -> RuleSet:
	"""Return the rule set called ``name``."""
	_scan()
	if name in _REGISTERED:
		return _REGISTERED[name]
	try:
		return _LOADED[name]
	except KeyError:
		raise UnknownTagSetError(name) from None


def available_tag_sets() -> list[str]:
	"""Names of every rule set that can be used, sorted."""
	_scan()
	return sorted(set(_LOADED) | set(_REGISTERED))


def describe_tag_sets() -> Iterator[tuple[str, str, int]]:
	"""Yield ``(name, description, rule_count)`` for every rule set."""
	for name in available_tag_sets():
		rule_set = get_tag_set(name)
		yield name, rule_set.description, len(rule_set)


def reload_tag_sets() -> None:
	"""Forget everything loaded from disk. Used by tests and by the UI."""
	global _SCANNED
	_LOADED.clear()
	_SCANNED = False
