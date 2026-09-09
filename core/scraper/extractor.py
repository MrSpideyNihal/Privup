"""Decode fetched bytes into text.

Deliberately narrow: bytes in, string out. It decides nothing about what the
text means and strips no markup. HTML cleaning belongs to
``core/summarizer``, and keeping the two apart is what stops the scraper and
the summarizer growing two competing ideas of what a document is.
"""

from __future__ import annotations

import re

__all__ = ["decode", "looks_like_policy"]

# <meta charset="..."> or <meta http-equiv="Content-Type" content="...charset=...">
_META_CHARSET = re.compile(
	rb"""<meta[^>]+charset\s*=\s*["']?\s*([a-zA-Z0-9_\-]+)""",
	re.IGNORECASE,
)

# Indian policy pages are frequently served as windows-1252 while declaring
# utf-8, or the reverse. Order matters: the first that decodes cleanly wins.
_FALLBACKS = ("utf-8", "cp1252", "latin-1")


def decode(body: bytes, declared_charset: str | None = None) -> str:
	"""Turn response bytes into text, guessing the encoding if necessary.

	Tries the charset the server declared, then one embedded in a meta tag,
	then a short list of encodings that policy pages actually use. Falls back
	to utf-8 with replacement rather than raising: a document with a handful
	of mangled characters is still worth analyzing, and refusing to read a
	policy over one bad byte would help nobody.
	"""
	candidates: list[str] = []
	if declared_charset:
		candidates.append(declared_charset)

	embedded = _META_CHARSET.search(body[:4096])
	if embedded:
		try:
			candidates.append(embedded.group(1).decode("ascii"))
		except UnicodeDecodeError:
			pass

	candidates.extend(_FALLBACKS)

	seen: set[str] = set()
	for encoding in candidates:
		key = encoding.lower().replace("_", "-")
		if key in seen:
			continue
		seen.add(key)
		try:
			return body.decode(encoding)
		except (UnicodeDecodeError, LookupError):
			continue

	return body.decode("utf-8", errors="replace")


# Phrases that only appear in policy *prose*.
#
# Notably absent: "privacy policy", "terms of use", "terms and conditions".
# Those are footer link text and sit on every page of a site. Including them
# made Kissht's homepage, 15,000 words of product marketing with a footer,
# test positive as a policy document, so the driver never followed the link
# it was supposed to follow. What distinguishes the real thing is a sentence
# about collecting data, not a navigation item naming the document.
_POLICY_SIGNALS = (
	"information we collect",
	"we collect",
	"we may collect",
	"personal information",
	"personal data",
	"data protection",
	"we use your",
	"third parties",
	"your consent",
	"retention",
	"we share",
	"cookies",
	# Loan-terms prose. Without these a terms-of-use page tests negative,
	# and the driver would wander off looking for a privacy policy when the
	# user deliberately handed it the loan agreement. The schedule of
	# charges is exactly the document worth reading before you borrow.
	"governing law",
	"indemnif",
	"liability",
	"borrower",
	"processing fee",
	"rate of interest",
	"repayment",
)

# Two distinct signals, and enough of them to be prose rather than a stray
# marketing line.
_MIN_SIGNALS = 3
_MIN_HITS = 6


def looks_like_policy(text: str, minimum_words: int = 250) -> bool:
	"""Rough test for whether ``text`` is a policy document.

	Used only to decide whether following a link is worth a second request,
	never to decide a verdict. Being wrong costs one extra HTTP call.
	"""
	if len(text.split()) < minimum_words:
		return False

	lowered = text.lower()
	distinct = 0
	total = 0
	for signal in _POLICY_SIGNALS:
		occurrences = lowered.count(signal)
		if occurrences:
			distinct += 1
			total += occurrences

	return distinct >= _MIN_SIGNALS and total >= _MIN_HITS
