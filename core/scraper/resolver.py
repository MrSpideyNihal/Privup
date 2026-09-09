"""Find the policy page from a page that merely links to one.

Users do not paste policy URLs. They paste the app's homepage, or the address
bar of the page with the consent banner on it. Making them hunt for the
privacy link defeats the point of answering before they tap Accept.

This module only reads links out of HTML that has already been fetched and
resolves them against the base URL. It performs no requests of its own; the
driver decides whether to follow what it finds.
"""

from __future__ import annotations

import html as html_module
import re
from urllib.parse import urljoin, urlparse

__all__ = ["PolicyLink", "find_policy_links", "resolve"]

# <a ...href="...">text</a>, tolerating the unquoted and unclosed attributes
# real pages are full of.
_ANCHOR = re.compile(
	r"""<a\b[^>]*?href\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))[^>]*>(.*?)</a\s*>""",
	re.IGNORECASE | re.DOTALL,
)

_TAGS = re.compile(r"<[^>]+>")

# Scored highest first. A link whose href says "privacy-policy" beats one
# whose text merely mentions privacy in a sentence.
_HREF_SIGNALS: tuple[tuple[str, int], ...] = (
	("privacy-policy", 100),
	("privacy_policy", 100),
	("privacypolicy", 100),
	("privacy-notice", 95),
	("privacy-statement", 95),
	("/privacy", 90),
	("data-protection", 70),
	("terms-and-conditions", 55),
	("terms-of-service", 55),
	("terms-of-use", 55),
	("/terms", 45),
	("legal", 30),
)

_TEXT_SIGNALS: tuple[tuple[str, int], ...] = (
	("privacy policy", 100),
	("privacy notice", 95),
	("privacy statement", 95),
	("privacy", 80),
	("data protection", 65),
	("terms of use", 50),
	("terms of service", 50),
	("terms and conditions", 50),
	("terms", 35),
)

# Never follow these, whatever they score.
_REJECT = (
	"mailto:", "tel:", "javascript:", "#",
	"/blog/", "/news/", "/careers", "/calculator",
	".pdf", ".jpg", ".png", ".zip", ".apk",
)


class PolicyLink:
	"""A candidate policy URL and how confident we are in it."""

	__slots__ = ("url", "score", "label")

	def __init__(self, url: str, score: int, label: str) -> None:
		self.url = url
		self.score = score
		self.label = label

	def __repr__(self) -> str:
		return f"PolicyLink({self.url!r}, score={self.score}, label={self.label!r})"


def resolve(base_url: str, href: str) -> str:
	"""Turn a possibly relative href into an absolute URL."""
	return urljoin(base_url, html_module.unescape(href.strip()))


def _anchor_text(raw: str) -> str:
	return " ".join(html_module.unescape(_TAGS.sub(" ", raw)).split())


def _score(url: str, text: str) -> int:
	lowered_url = url.lower()
	lowered_text = text.lower()

	best = 0
	for signal, points in _HREF_SIGNALS:
		if signal in lowered_url:
			best = max(best, points)
			break
	for signal, points in _TEXT_SIGNALS:
		if signal in lowered_text:
			best = max(best, points)
			break
	return best


def find_policy_links(html: str, base_url: str, same_host_only: bool = True) -> list[PolicyLink]:
	"""Return candidate policy URLs found in ``html``, best first.

	``same_host_only`` defaults to True. Following an off-site link would
	mean analyzing a document and attributing it to a service that did not
	publish it, which is worse than finding nothing.
	"""
	base_host = urlparse(base_url).netloc.lower()
	candidates: dict[str, PolicyLink] = {}

	for match in _ANCHOR.finditer(html):
		href = match.group(1) or match.group(2) or match.group(3) or ""
		if not href:
			continue

		lowered_href = href.lower().strip()
		if any(bad in lowered_href for bad in _REJECT):
			continue

		absolute = resolve(base_url, href)
		if urlparse(absolute).scheme not in {"http", "https"}:
			continue
		if same_host_only and urlparse(absolute).netloc.lower() != base_host:
			continue

		text = _anchor_text(match.group(4))
		score = _score(absolute, text)
		if score <= 0:
			continue

		existing = candidates.get(absolute)
		if existing is None or score > existing.score:
			candidates[absolute] = PolicyLink(absolute, score, text or absolute)

	# Shorter URLs win ties: /privacy beats /privacy/cookies/details.
	return sorted(candidates.values(), key=lambda link: (-link.score, len(link.url)))
