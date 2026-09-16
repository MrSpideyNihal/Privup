"""Strip HTML boilerplate down to the prose a human would actually read.

Real policy pages are mostly not policy. The Fibe page this was built against
is 4381 words of which roughly 1300 are the site's product navigation menu,
repeated twice. Feeding that to the analyzer does not just waste time, it
produces findings against link text.

Uses ``html.parser`` from the standard library rather than BeautifulSoup. Not
for licensing reasons (bs4 is MIT and would be allowed) but because keeping
``core`` dependency-free keeps the Part 3 port to the browser extension and
Android honest. For dropping scripts, styles and navigation chrome, a targeted
parser is enough.

A note on why this is deliberately cautious. Guessing "this is chrome" from a
class name is a heuristic, and heuristics fail in exactly the wrong direction:
the first version of this module matched class substrings and threw away the
entire Signal policy, because ``<body class="index has-navbar-fixed-top">``
contains "nav". It also threw away Mozilla's policy via
``<div class="mzp-l-content mzp-has-sidebar">``, and matched the heading
``<h2 class="how-we-share-your-personal-data">`` as social-share chrome. Under-
cleaning costs some noise. Over-cleaning silently returns Allow for a policy
nobody read. So: structural roots are never chrome, hints match name parts
rather than substrings, and ``clean_html`` refuses any aggressive result that
lost more than half the document.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

__all__ = ["Block", "clean_html", "normalize_text"]

# Content inside these never survives, regardless of anything else.
_DROP_CONTENT = {
	"script", "style", "noscript", "template", "svg", "canvas",
	"iframe", "object", "embed", "head", "select", "button", "textarea",
}

# Structural chrome. Real policy text is never inside these.
_BOILERPLATE_TAGS = {"nav", "footer", "header", "aside", "menu", "dialog"}

# Never chrome, whatever their class says. These wrap the document, so a
# false positive here loses everything.
_NEVER_CHROME = {"html", "body", "main", "article"}

# Name parts that mark chrome. Compared against class/id split on separators,
# so "footer" matches "moz24-footer" but not "footermost". Deliberately does
# not include "share" or "sidebar": "how-we-share-your-personal-data" is the
# most important heading in a privacy policy, and "has-sidebar" is routinely
# on the element wrapping the main content.
_BOILERPLATE_HINTS = frozenset({
	"navbar", "navigation", "menu", "megamenu", "footer", "breadcrumb",
	"cookiebar", "cookiebanner", "consentbanner", "social", "socials",
	"newsletter", "subscribe", "topbar", "skiplink", "backtotop",
	"languageswitcher", "langswitcher", "sitesearch",
})

_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}

_BLOCK_TAGS = _HEADING_TAGS | {
	"p", "div", "li", "tr", "section", "article", "blockquote",
	"dd", "dt", "figcaption", "pre", "main", "ul", "ol", "table", "form",
}

# Table cells are joined into their row instead of each becoming a block.
# A lender's schedule of charges is a table, and split cell by cell it
# degrades into "Processing fees" and "Up to 7%" as unrelated fragments,
# which is precisely the association the analyzer needs to keep. Kept as one
# row it reads "Processing fees | Up to 7% | ...", and one rule can see both
# the label and the number.
_CELL_TAGS = {"td", "th"}
_CELL_SEPARATOR = " | "

# Elements with no closing tag, so they must not go on the open-tag stack.
_VOID_TAGS = {
	"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
	"meta", "param", "source", "track", "wbr",
}

# An aggressive pass that keeps less than this share of the conservative
# pass's words is treated as a heuristic failure, not as a clean document.
_CONTENT_FLOOR = 0.5

# Non-breaking, figure, thin, hair, zero-width and narrow spaces, plus the
# byte-order mark. \s does not cover these and policy pages pasted out of
# Word are full of them. Spelled as code points so the source stays ASCII
# and nobody "tidies up" an invisible character by accident.
_ODD_SPACES = "".join(
	chr(c) for c in (0x00A0, 0x2007, 0x2009, 0x200A, 0x200B, 0x202F, 0xFEFF)
)
_WHITESPACE = re.compile(r"[\s" + re.escape(_ODD_SPACES) + r"]+")

_NAME_SEPARATORS = re.compile(r"[\s_\-.:]+")


class Block:
	"""A run of text that came from one block-level element."""

	__slots__ = ("text", "is_heading")

	def __init__(self, text: str, is_heading: bool) -> None:
		self.text = text
		self.is_heading = is_heading

	def __repr__(self) -> str:
		kind = "H" if self.is_heading else "p"
		return f"Block[{kind}]({self.text[:60]!r})"

	def __eq__(self, other: object) -> bool:
		if not isinstance(other, Block):
			return NotImplemented
		return self.text == other.text and self.is_heading == other.is_heading

	def __hash__(self) -> int:
		return hash((self.text, self.is_heading))


def normalize_text(text: str) -> str:
	"""Collapse whitespace, including the non-breaking spaces policies love."""
	return _WHITESPACE.sub(" ", text).strip()


def _name_parts(value: str) -> set[str]:
	"""Split a class or id into comparable parts.

	``"moz24-footer-socials"`` -> ``{"moz24", "footer", "socials"}``. Digits
	are stripped from each part so ``m24-navigation`` matches ``navigation``.
	"""
	parts = set()
	for token in _NAME_SEPARATORS.split(value.lower()):
		if token:
			parts.add(token)
			stripped = token.strip("0123456789")
			if stripped:
				parts.add(stripped)
	return parts


def _is_boilerplate(
	tag: str, attrs: list[tuple[str, str | None]], use_hints: bool
) -> bool:
	"""True when this element is site chrome rather than policy content."""
	if tag in _NEVER_CHROME:
		return False
	if tag in _BOILERPLATE_TAGS:
		return True

	for key, value in attrs:
		if key == "role" and value in {"navigation", "banner", "contentinfo", "search"}:
			return True
		if key == "aria-hidden" and value == "true":
			return True
		if use_hints and key in {"class", "id"} and value:
			if _name_parts(value) & _BOILERPLATE_HINTS:
				return True
	return False


class _PolicyHTMLParser(HTMLParser):
	"""Collect block-level text, dropping scripts, styles and chrome.

	Tracks the full open-element stack rather than a depth counter. Real
	policy pages have unbalanced markup, and a counter gets stuck skipping
	the rest of the document the first time a ``<div class="nav">`` closes
	out of order.
	"""

	def __init__(self, use_hints: bool) -> None:
		super().__init__(convert_charrefs=True)
		self.blocks: list[Block] = []
		self._use_hints = use_hints
		self._open: list[tuple[str, bool]] = []  # (tag, opened_a_skip_region)
		self._skip_depth = 0
		self._buffer: list[str] = []
		self._buffer_is_heading = False

	def _flush(self) -> None:
		text = normalize_text("".join(self._buffer))
		self._buffer.clear()
		# A row ends with a trailing cell separator, and empty cells leave
		# runs of them in the middle.
		while _CELL_SEPARATOR.strip() in text:
			collapsed = re.sub(r"(?:\s*\|\s*)+", _CELL_SEPARATOR, text).strip(" |").strip()
			if collapsed == text:
				break
			text = collapsed
		if text:
			self.blocks.append(Block(text, self._buffer_is_heading))
		self._buffer_is_heading = False

	def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
		if tag in _VOID_TAGS:
			if tag == "br" and self._skip_depth == 0:
				self._buffer.append(" ")
			return

		skips = tag in _DROP_CONTENT or _is_boilerplate(tag, attrs, self._use_hints)
		if skips:
			self._flush()
			self._skip_depth += 1
		self._open.append((tag, skips))

		if self._skip_depth == 0 and tag in _BLOCK_TAGS:
			self._flush()
			if tag in _HEADING_TAGS:
				self._buffer_is_heading = True

	def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
		if tag == "br" and self._skip_depth == 0:
			self._buffer.append(" ")

	def handle_endtag(self, tag: str) -> None:
		if tag in _VOID_TAGS:
			return

		# Unwind to the matching open tag. Anything dangling above it was
		# never closed, which is normal in hand-written policy pages.
		for position in range(len(self._open) - 1, -1, -1):
			if self._open[position][0] == tag:
				for _, skipped in self._open[position:]:
					if skipped:
						self._skip_depth -= 1
				del self._open[position:]
				break
		else:
			return

		if self._skip_depth == 0:
			if tag in _CELL_TAGS:
				self._buffer.append(_CELL_SEPARATOR)
			elif tag in _BLOCK_TAGS:
				self._flush()

	def handle_data(self, data: str) -> None:
		if self._skip_depth == 0:
			self._buffer.append(data)

	def close(self) -> None:  # type: ignore[override]
		super().close()
		self._skip_depth = 0
		self._flush()


def _parse(html: str, use_hints: bool) -> list[Block]:
	parser = _PolicyHTMLParser(use_hints=use_hints)
	parser.feed(html)
	parser.close()
	return parser.blocks


def _word_count(blocks: list[Block]) -> int:
	return sum(len(block.text.split()) for block in blocks)


def clean_html(html: str, *, drop_chrome: bool = True) -> list[Block]:
	"""Parse ``html`` into ordered blocks with scripts, styles and chrome gone.

	Runs two passes. The conservative pass drops only unambiguous chrome:
	script, style, ``<nav>``, ``<footer>``, ARIA landmark roles. The
	aggressive pass additionally guesses from class and id names.

	The aggressive result is used only if it kept at least half the words the
	conservative pass found. A class-name guess that deletes most of a policy
	is wrong, and the correct response is to keep the noise rather than to
	confidently analyze a near-empty document.

	Parsing twice roughly doubles the cost of a step that is already far
	cheaper than the analyzer, which is a fair trade for not silently
	returning Allow on a policy that was never read.
	"""
	conservative = _parse(html, use_hints=False)
	if not drop_chrome:
		return conservative

	aggressive = _parse(html, use_hints=True)
	if _word_count(aggressive) < _CONTENT_FLOOR * _word_count(conservative):
		return conservative
	return aggressive
