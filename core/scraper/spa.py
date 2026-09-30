"""Recover policy text from JavaScript-rendered pages.

Several Indian lending sites — KreditBee, Stashfin, and others — build their
privacy policy pages as client-side SPAs. A plain HTTP GET returns an empty
``<div id="root"></div>`` with all content loaded via JavaScript after the
page renders. ``urllib`` never executes that JavaScript.

This module detects those empty shells and tries every zero-dependency
strategy to recover the text before giving up:

1. **Embedded framework data** — Next.js ``__NEXT_DATA__``, Nuxt
   ``__NUXT__``, Redux/Apollo ``__PRELOADED_STATE__``, and JSON-LD
   ``application/ld+json`` all carry content inside ``<script>`` tags that
   never need JavaScript execution.

2. **Wayback Machine** — The Internet Archive's CDX API finds cached
   snapshots. The Wayback Machine renders JavaScript when crawling, so its
   snapshots contain the fully rendered HTML. This is the only fallback that
   works for pure React CRA / Vite SPAs that embed nothing.

Both strategies use only the standard library. No headless browser, no
``requests``, no third-party package.

A page is classified as an SPA shell only when the visible text is very
short *and* there are strong structural signals (an empty mount point, a
"you need JavaScript" noscript tag, or a JavaScript-heavy ``<head>``). This
avoids false positives on legitimately short pages or error pages.
"""

from __future__ import annotations

import json
import logging
import re
from html.parser import HTMLParser
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

__all__ = ["is_spa_shell", "recover_content", "RecoveryResult"]

logger = logging.getLogger("privup.spa")


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

# Mount points that pure SPAs leave empty.
_EMPTY_MOUNT = re.compile(
	r"""<div\s+id\s*=\s*["'](?:root|app|__next|__nuxt|main-app)["']\s*>\s*</div>""",
	re.IGNORECASE,
)

# "You need to enable JavaScript to run this app."
_NOSCRIPT_JS_MSG = re.compile(
	r"<noscript[^>]*>[^<]*(?:enable|activate|turn on)\s+javascript[^<]*</noscript>",
	re.IGNORECASE | re.DOTALL,
)

# SPA frameworks load most code via <script src="..."> with hashed filenames.
_HASHED_BUNDLE = re.compile(
	r"""<script[^>]+src=["'][^"']*[./][a-f0-9]{6,}\.js["']""",
	re.IGNORECASE,
)


def _visible_word_count(html: str) -> int:
	"""Rough count of words visible after stripping all tags and scripts."""
	stripped = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.DOTALL)
	stripped = re.sub(r"<style[^>]*>.*?</style>", " ", stripped, flags=re.DOTALL)
	stripped = re.sub(r"<[^>]+>", " ", stripped)
	return len(stripped.split())


def is_spa_shell(html: str, *, word_threshold: int = 80) -> bool:
	"""True when ``html`` is almost certainly a JavaScript-only shell.

	The test requires *both* a low visible word count *and* a structural
	signal. A 404 page with 20 words is not an SPA; an empty ``<div id="root">``
	with hashed bundles is.
	"""
	if _visible_word_count(html) >= word_threshold:
		return False

	# Must have at least one structural signal.
	if _EMPTY_MOUNT.search(html):
		return True
	if _NOSCRIPT_JS_MSG.search(html):
		return True
	# Heavy reliance on hashed JS bundles with almost no visible text.
	if len(_HASHED_BUNDLE.findall(html)) >= 3:
		return True

	return False


# ---------------------------------------------------------------------------
# Embedded-data extraction (strategy 1)
# ---------------------------------------------------------------------------

def _walk_strings(obj: Any, min_length: int = 80) -> list[str]:
	"""Recursively collect long strings from a parsed JSON tree."""
	strings: list[str] = []
	if isinstance(obj, str):
		if len(obj) >= min_length:
			strings.append(obj)
	elif isinstance(obj, dict):
		for value in obj.values():
			strings.extend(_walk_strings(value, min_length))
	elif isinstance(obj, list):
		for item in obj:
			strings.extend(_walk_strings(item, min_length))
	return strings


def _extract_next_data(html: str) -> str:
	"""Extract text from Next.js ``__NEXT_DATA__`` script tag."""
	match = re.search(
		r'<script[^>]*id\s*=\s*["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
		html,
		re.DOTALL,
	)
	if not match:
		return ""
	try:
		data = json.loads(match.group(1))
	except (json.JSONDecodeError, ValueError):
		return ""

	# Walk pageProps for long strings — that is where SSR content lives.
	strings = _walk_strings(data.get("props", {}))
	if not strings:
		return ""
	return "\n\n".join(strings)


def _extract_nuxt_data(html: str) -> str:
	"""Extract text from Nuxt.js ``window.__NUXT__`` or ``__NUXT_DATA__``."""
	# Nuxt 2: window.__NUXT__ = { ... }
	match = re.search(
		r"window\.__NUXT__\s*=\s*(\{.*?\})\s*;?\s*(?:</script>|$)",
		html,
		re.DOTALL,
	)
	if match:
		try:
			data = json.loads(match.group(1))
			strings = _walk_strings(data)
			if strings:
				return "\n\n".join(strings)
		except (json.JSONDecodeError, ValueError):
			pass
	return ""


def _extract_json_ld(html: str) -> str:
	"""Extract article text from JSON-LD ``application/ld+json`` scripts.

	Many sites (especially WordPress + Next.js hybrids) embed their full
	article body in structured data, even when the visible HTML is empty.
	"""
	texts: list[str] = []
	for match in re.finditer(
		r'<script[^>]*type\s*=\s*["\']application/ld\+json["\'][^>]*>(.*?)</script>',
		html,
		re.DOTALL | re.IGNORECASE,
	):
		try:
			data = json.loads(match.group(1))
		except (json.JSONDecodeError, ValueError):
			continue

		items = [data] if isinstance(data, dict) else data if isinstance(data, list) else []
		for item in items:
			if not isinstance(item, dict):
				continue
			for key in ("articleBody", "text", "description"):
				value = item.get(key, "")
				if isinstance(value, str) and len(value) > 100:
					texts.append(value)
	return "\n\n".join(texts)


def _extract_preloaded_state(html: str) -> str:
	"""Extract text from common preloaded-state patterns.

	Covers ``window.__PRELOADED_STATE__``, ``window.__INITIAL_STATE__``,
	``window.__INITIAL_PROPS__``, and ``window.__APOLLO_STATE__``.
	"""
	for varname in (
		"__PRELOADED_STATE__",
		"__INITIAL_STATE__",
		"__INITIAL_PROPS__",
		"__APOLLO_STATE__",
	):
		pattern = re.compile(
			rf"window\.{re.escape(varname)}\s*=\s*(\{{.*?\}})\s*;?\s*(?:</script>|$)",
			re.DOTALL,
		)
		match = pattern.search(html)
		if match:
			try:
				data = json.loads(match.group(1))
				strings = _walk_strings(data)
				if strings:
					return "\n\n".join(strings)
			except (json.JSONDecodeError, ValueError):
				continue
	return ""


def _extract_inline_json_scripts(html: str) -> str:
	"""Extract text from anonymous inline ``<script>`` tags containing JSON."""
	texts: list[str] = []
	for match in re.finditer(r"<script[^>]*>(.*?)</script>", html, re.DOTALL):
		content = match.group(1).strip()
		if not content.startswith(("{", "[")):
			continue
		try:
			data = json.loads(content)
		except (json.JSONDecodeError, ValueError):
			continue
		strings = _walk_strings(data)
		texts.extend(strings)
	return "\n\n".join(texts)


def _try_embedded_extraction(html: str) -> str:
	"""Try every embedded-data extractor, return the first non-empty result."""
	for extractor in (
		_extract_next_data,
		_extract_nuxt_data,
		_extract_json_ld,
		_extract_preloaded_state,
		_extract_inline_json_scripts,
	):
		text = extractor(html)
		if text and len(text.split()) >= 30:
			return text
	return ""


# ---------------------------------------------------------------------------
# Wayback Machine fallback (strategy 2)
# ---------------------------------------------------------------------------

_WAYBACK_CDX = "https://web.archive.org/cdx/search/cdx"
_WAYBACK_WEB = "https://web.archive.org/web"
_WAYBACK_TIMEOUT = 10.0


class _TextExtractor(HTMLParser):
	"""Minimal tag-stripping parser that also drops Wayback toolbar markup."""

	def __init__(self) -> None:
		super().__init__(convert_charrefs=True)
		self._parts: list[str] = []
		self._skip = 0

	def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
		if tag in ("script", "style", "noscript"):
			self._skip += 1
		# Wayback injects a toolbar div with id="wm-ipp-*".
		for key, value in attrs:
			if key == "id" and value and value.startswith("wm-ipp"):
				self._skip += 1

	def handle_endtag(self, tag: str) -> None:
		if tag in ("script", "style", "noscript"):
			self._skip = max(0, self._skip - 1)

	def handle_data(self, data: str) -> None:
		if self._skip == 0:
			self._parts.append(data)

	def get_text(self) -> str:
		return " ".join(self._parts)


def _try_wayback(url: str, timeout: float = _WAYBACK_TIMEOUT) -> str:
	"""Fetch the most recent Wayback Machine snapshot of ``url``.

	Returns the visible text content of the snapshot, or an empty string if
	no snapshot exists or the request fails.
	"""
	# Step 1: query the CDX API for the latest snapshot.
	cdx_params = (
		f"url={quote(url, safe='')}"
		"&output=json"
		"&limit=1"
		"&fl=timestamp,original,statuscode"
		"&filter=statuscode:200"
		"&sort=reverse"      # most recent first
	)
	cdx_url = f"{_WAYBACK_CDX}?{cdx_params}"

	try:
		req = Request(cdx_url, headers={"User-Agent": "PrivUp/1.0"})
		with urlopen(req, timeout=timeout) as resp:
			rows = json.loads(resp.read(500_000))
	except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError):
		return ""

	# rows[0] is the header, rows[1] is the first result.
	if len(rows) < 2:
		return ""

	timestamp = rows[1][0]
	original = rows[1][1]
	snapshot_url = f"{_WAYBACK_WEB}/{timestamp}id_/{original}"

	# Step 2: fetch the snapshot.
	try:
		req = Request(snapshot_url, headers={"User-Agent": "PrivUp/1.0"})
		with urlopen(req, timeout=timeout) as resp:
			body = resp.read(5 * 1024 * 1024)
			# Try utf-8, fall back to latin-1.
			try:
				html = body.decode("utf-8")
			except UnicodeDecodeError:
				html = body.decode("latin-1", errors="replace")
	except (HTTPError, URLError, TimeoutError, OSError):
		return ""

	# Step 3: strip tags and return visible text.
	parser = _TextExtractor()
	try:
		parser.feed(html)
		parser.close()
	except Exception:
		return ""
	return parser.get_text()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class RecoveryResult:
	"""The outcome of attempting to recover content from an SPA shell.

	Attributes:
		text:     The recovered text, or ``""`` if recovery failed.
		method:   How the text was obtained (``"embedded"``, ``"wayback"``,
		          or ``""`` on failure).
		is_shell: Whether the original HTML was classified as an SPA shell.
	"""
	__slots__ = ("text", "method", "is_shell")

	def __init__(self, text: str, method: str, is_shell: bool) -> None:
		self.text = text
		self.method = method
		self.is_shell = is_shell

	def __repr__(self) -> str:
		words = len(self.text.split()) if self.text else 0
		return (
			f"RecoveryResult(method={self.method!r}, "
			f"is_shell={self.is_shell}, words={words})"
		)

	@property
	def recovered(self) -> bool:
		"""True when usable text was obtained."""
		return bool(self.text and len(self.text.split()) >= 30)


def recover_content(
	html: str,
	url: str = "",
	*,
	try_wayback: bool = True,
	wayback_timeout: float = _WAYBACK_TIMEOUT,
) -> RecoveryResult:
	"""Attempt to recover readable policy text from an SPA shell.

	Call this when ``is_spa_shell(html)`` returns True, or unconditionally —
	it is a no-op when the HTML already has substantial visible content.

	Strategies are tried in order of speed and reliability:
	1. Embedded framework data (instant, parsed from the same HTML)
	2. Wayback Machine snapshot (network round trip, returns rendered HTML)

	Parameters:
		html:            The raw HTML received from the server.
		url:             The original URL, used for the Wayback lookup.
		try_wayback:     Set False to skip the Wayback Machine fallback.
		wayback_timeout: Timeout in seconds for Wayback requests.
	"""
	shell = is_spa_shell(html)

	if not shell:
		return RecoveryResult(text="", method="", is_shell=False)

	# Strategy 1: embedded data.
	embedded = _try_embedded_extraction(html)
	if embedded and len(embedded.split()) >= 30:
		logger.info("Recovered %d words from embedded data for %s", len(embedded.split()), url)
		return RecoveryResult(text=embedded, method="embedded", is_shell=True)

	# Strategy 2: Wayback Machine.
	if try_wayback and url:
		logger.info("Trying Wayback Machine for %s", url)
		wayback_text = _try_wayback(url, timeout=wayback_timeout)
		if wayback_text and len(wayback_text.split()) >= 30:
			logger.info("Recovered %d words from Wayback for %s", len(wayback_text.split()), url)
			return RecoveryResult(text=wayback_text, method="wayback", is_shell=True)

	# Neither strategy produced usable text.
	return RecoveryResult(text="", method="", is_shell=True)
