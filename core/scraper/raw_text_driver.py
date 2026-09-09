"""Pass-through driver for text that is already in hand.

This is the driver that makes the rest of the system testable: every rule
set, every analyzer change and every scorer threshold can be exercised
against a fixed string with no network, no fixtures server and no flakiness.

It is also a real user path, not just a test seam. Someone who has copied a
consent dialog or a loan agreement out of an app and pasted it into the local
UI is using this driver.
"""

from __future__ import annotations

import re

from core.models import DriverResult
from core.scraper.base import Driver, DriverError
from core.scraper.registry import register_driver

__all__ = ["RawTextDriver"]

# Enough of a signal that the payload is markup and the summarizer should run
# its HTML stripping pass. Deliberately narrow: a policy that merely mentions
# "<18 years of age" must not be treated as HTML.
_HTML_HINT = re.compile(
	r"<\s*(html|body|div|p|br|h[1-6]|ul|ol|li|table|section|article|span)\b[^>]*>",
	re.IGNORECASE,
)


@register_driver
class RawTextDriver(Driver):
	"""Return the target string as-is, with a content type sniffed from it."""

	name = "raw_text"
	default_content_type = "text/plain"
	description = "Analyze text supplied directly (pasted policy, fixture, stdin)."

	def fetch(self, target: str) -> DriverResult:
		if not isinstance(target, str):
			raise DriverError(
				f"raw_text driver expects a string, got {type(target).__name__}"
			)
		if not target.strip():
			raise DriverError("raw_text driver received empty input, nothing to analyze")

		content_type = "text/html" if _HTML_HINT.search(target) else "text/plain"

		return self.build_result(
			raw_text=target,
			origin="raw_text",
			content_type=content_type,
			metadata={"length": len(target)},
		)
