"""Filling {placeholders} in a line of text the user will read.

One implementation, shared by the analyzer (which fills a rule's reason) and
the translator (which fills the same reason in another language), so a figure
such as ``{annualised}`` is formatted identically in every language. It lives
in ``core/models`` because stages may share code only through that package.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

__all__ = ["fill_template"]

_PLACEHOLDER = re.compile(r"\{(\w+)\}")


def fill_template(template: str, values: Mapping[str, Any]) -> str:
	"""Substitute {placeholders}, leaving unknown ones as written.

	A rule author who mistypes a placeholder gets a visible ``{typo}`` in the
	output rather than a crash in front of a user mid-consent-dialog. Floats
	print with six significant digits, so 73.0 reads 73 and 0.2 reads 0.2.
	"""
	def replace(match: re.Match[str]) -> str:
		key = match.group(1)
		if key not in values:
			return match.group(0)
		value = values[key]
		if isinstance(value, float):
			return f"{value:.6g}"
		return str(value)

	return _PLACEHOLDER.sub(replace, template)
