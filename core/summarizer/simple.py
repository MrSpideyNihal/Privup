"""Rule-free preprocessing: clean, then segment.

Deliberately contains no policy knowledge. Everything this module knows about
is HTML and sentence boundaries. All judgement about what a sentence *means*
lives in ``core/tags`` rule sets, so a contributor adding a rule never has to
come here.
"""

from __future__ import annotations

from core.models import Clause, DriverResult
from core.summarizer.base import BaseSummarizer
from core.summarizer.cleaner import clean_html
from core.summarizer.segmenter import blocks_from_text, segment

__all__ = ["SimpleSummarizer"]

_HTML_TYPES = {"text/html", "application/xhtml+xml"}


class SimpleSummarizer(BaseSummarizer):
	"""Strip markup when there is any, then split into sentence clauses."""

	def clean(self, result: DriverResult) -> list[Clause]:
		if result.is_empty:
			return []

		content_type = result.content_type.split(";")[0].strip().lower()
		if content_type in _HTML_TYPES:
			blocks = clean_html(result.raw_text)
		else:
			blocks = blocks_from_text(result.raw_text)

		return segment(blocks)
