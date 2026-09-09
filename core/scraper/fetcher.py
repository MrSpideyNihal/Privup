"""HTTP retrieval. The only place in PrivUp that opens a socket.

Used exclusively by ``url_driver``. Nothing outside ``core/scraper`` imports
this, and nothing inside ``core/summarizer``, ``core/analyzer`` or
``core/scorer`` is allowed to.

Standard library only. ``urllib.request`` follows redirects, which is most of
what a policy URL needs, and avoiding a ``requests`` dependency keeps
``pyproject.toml`` empty of runtime requirements.
"""

from __future__ import annotations

import gzip
import zlib
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse, urlunparse
from urllib.request import Request, urlopen

from core.scraper.base import DriverError

__all__ = ["Response", "fetch_url", "DEFAULT_TIMEOUT", "MAX_BYTES"]

DEFAULT_TIMEOUT = 20.0

# Policy pages are prose. Anything past this is a download, not a document,
# and reading it into memory on a phone is not free.
MAX_BYTES = 5 * 1024 * 1024

# Several policy hosts return 403 to an unrecognised agent. Identifying
# honestly as PrivUp gets refused by more of them than not, so this presents
# as a browser. If a site owner wants to block this, the source is public.
_USER_AGENT = (
	"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
	"Chrome/120.0 Safari/537.36"
)

# Claiming to be Chrome is not enough on its own: some edges check that the
# claim is internally consistent and reject a Chrome user agent that arrives
# without the client-hint and fetch-metadata headers a real Chrome always
# sends. whatsapp.com answers 400 Bad Request to a bare Chrome user agent and
# 200 to no user agent at all, which is a confusing way to be told the request
# looks forged. Sending the full consistent set fixes it.
_HEADERS = {
	"User-Agent": _USER_AGENT,
	"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
	"Accept-Language": "en-US,en;q=0.9",
	"Accept-Encoding": "gzip, deflate",
	"Upgrade-Insecure-Requests": "1",
	"Sec-Fetch-Dest": "document",
	"Sec-Fetch-Mode": "navigate",
	"Sec-Fetch-Site": "none",
	"Sec-Fetch-User": "?1",
	"sec-ch-ua": '"Chromium";v="120", "Not:A-Brand";v="24"',
	"sec-ch-ua-mobile": "?0",
	"sec-ch-ua-platform": '"Windows"',
}

# Stripped-back request used as a second attempt. Some hosts dislike the
# browser impersonation; others (signal.org) refuse a request with no user
# agent. Neither header set works everywhere, so try the browser-shaped one
# first and fall back rather than pick a side.
_FALLBACK_HEADERS = {
	"Accept": "text/html,*/*;q=0.8",
	"Accept-Encoding": "gzip, deflate",
}

# Statuses that mean "we did not like the look of this request" rather than
# "there is nothing here". Only these are worth a second attempt: retrying a
# 404 just costs the user another round trip.
_RETRY_STATUSES = frozenset({400, 401, 403, 406, 409, 421, 429})

_ALLOWED_SCHEMES = {"http", "https"}

# Content types that are not prose. Handing a PDF's raw bytes to the
# summarizer produces confident nonsense, so refuse instead. A PDF driver is
# a reasonable thing for someone to contribute; guessing is not.
_BINARY_PREFIXES = ("image/", "audio/", "video/", "font/")
_BINARY_TYPES = {
	"application/pdf", "application/zip", "application/octet-stream",
	"application/msword", "application/vnd.android.package-archive",
}


@dataclass(frozen=True, slots=True)
class Response:
	"""A fetched document, before any decoding decision has been made."""

	body: bytes
	final_url: str
	status: int
	content_type: str
	charset: str | None


def normalize_url(url: str) -> str:
	"""Add a scheme when the user typed a bare host, and validate it."""
	candidate = url.strip()
	if not candidate:
		raise DriverError("no URL given")

	parsed = urlparse(candidate)
	if not parsed.scheme:
		parsed = urlparse("https://" + candidate)
	if parsed.scheme not in _ALLOWED_SCHEMES:
		raise DriverError(
			f"only http and https are supported, got {parsed.scheme!r}. "
			"A file or PDF source belongs in its own driver."
		)
	if not parsed.netloc:
		raise DriverError(f"{url!r} is not a usable URL")

	return urlunparse(parsed)


def _decompress(body: bytes, encoding: str) -> bytes:
	encoding = encoding.lower().strip()
	try:
		if encoding == "gzip":
			return gzip.decompress(body)
		if encoding == "deflate":
			return zlib.decompress(body, -zlib.MAX_WBITS)
	except (OSError, zlib.error):
		# A server that lied about its encoding is common enough that
		# falling back to the raw bytes beats failing the whole fetch.
		return body
	return body


def _attempt(target: str, headers: dict[str, str], timeout: float):
	"""One GET. Returns the pieces we need, or raises."""
	with urlopen(Request(target, headers=headers), timeout=timeout) as response:
		return (
			response.geturl(),
			getattr(response, "status", 200) or 200,
			response.headers,
			response.read(MAX_BYTES + 1),
		)


def fetch_url(url: str, timeout: float = DEFAULT_TIMEOUT) -> Response:
	"""GET ``url``, following redirects, and return the raw response.

	Tries a browser-shaped request first and a stripped-back one second, since
	some hosts reject each. Raises ``DriverError`` for anything that means "no
	document here": a bad scheme, a network failure, an HTTP error, a binary
	payload.
	"""
	target = normalize_url(url)

	try:
		final_url, status, headers, body = _attempt(target, _HEADERS, timeout)
	except HTTPError as exc:
		if exc.code not in _RETRY_STATUSES:
			raise DriverError(f"{target} returned HTTP {exc.code} ({exc.reason})") from None
		try:
			final_url, status, headers, body = _attempt(target, _FALLBACK_HEADERS, timeout)
		except HTTPError as retry_exc:
			# Report the original refusal. It is the one that describes how
			# the host normally answers.
			raise DriverError(
				f"{target} returned HTTP {exc.code} ({exc.reason})"
			) from None
		except (URLError, TimeoutError, OSError):
			raise DriverError(f"{target} returned HTTP {exc.code} ({exc.reason})") from None
	except URLError as exc:
		raise DriverError(f"could not reach {target}: {exc.reason}") from None
	except TimeoutError:
		raise DriverError(f"{target} timed out after {timeout:g}s") from None
	except OSError as exc:
		raise DriverError(f"could not read {target}: {exc}") from None

	if len(body) > MAX_BYTES:
		body = body[:MAX_BYTES]

	body = _decompress(body, headers.get("Content-Encoding", "") or "")

	raw_type = headers.get("Content-Type", "") or ""
	content_type = raw_type.split(";")[0].strip().lower() or "text/html"
	if content_type in _BINARY_TYPES or content_type.startswith(_BINARY_PREFIXES):
		raise DriverError(
			f"{final_url} is {content_type}, which this driver cannot read as text"
		)

	return Response(
		body=body,
		final_url=final_url,
		status=status,
		content_type=content_type,
		charset=headers.get_content_charset(),
	)
