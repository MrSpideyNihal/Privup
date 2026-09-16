"""Tag definitions: named rule sets that decide what counts as a red flag.

Rule sets are data. To add one, drop a JSON file into ``core/tags/rulesets/``
and it is discovered automatically. See ``core/tags/rules.py`` for the fields
a rule can have and why each exists.
"""

from core.tags.registry import (
	RULESET_DIR,
	UnknownTagSetError,
	available_tag_sets,
	describe_tag_sets,
	get_tag_set,
	register_tag_set,
	reload_tag_sets,
)
from core.tags.rules import (
	NumericCheck,
	Rule,
	RuleSet,
	RuleSetError,
	Scope,
	load_rule_set,
	parse_rule_set,
)

__all__ = [
	"NumericCheck",
	"RULESET_DIR",
	"Rule",
	"RuleSet",
	"RuleSetError",
	"Scope",
	"UnknownTagSetError",
	"available_tag_sets",
	"describe_tag_sets",
	"get_tag_set",
	"load_rule_set",
	"parse_rule_set",
	"register_tag_set",
	"reload_tag_sets",
]
