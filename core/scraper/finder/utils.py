# /*
#  *  ╔════════════════════════════════════════════════════════════╗
#  *  ║                                                            ║
#  *  ║                     PRIVACY-URL-FINDER                     ║
#  *  ║                                                            ║
#  *  ║                         by Nihal Rodge                     ║
#  *  ║                                                            ║
#  *  ║  GitHub: github.com/MrSpideyNihal/privacy-url-finder       ║
#  *  ║                                                            ║
#  *  ╚════════════════════════════════════════════════════════════╝
#  */
#
# This code was integrated from privacy-url-finder:
# https://github.com/MrSpideyNihal/privacy-url-finder
#

"""Utility functions for Privacy URL Finder."""

import logging
import re
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("privacy_url_finder")

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# Secure (default) SSL context — used first
_SSL_CONTEXT_SECURE = ssl.create_default_context()

# Permissive SSL context — fallback for sites with bad/self-signed certificates
_SSL_CONTEXT_PERMISSIVE = ssl.create_default_context()
_SSL_CONTEXT_PERMISSIVE.check_hostname = False
_SSL_CONTEXT_PERMISSIVE.verify_mode = ssl.CERT_NONE

# Transient HTTP status codes that warrant a retry
_RETRYABLE_STATUS_CODES = {500, 502, 503, 504, 429}


def normalize_query(query: str) -> str:
    """Clean whitespace and lowercase query."""
    return query.strip()


COMMON_TLDS = {
    "com", "in", "org", "net", "io", "app", "ai", "co", "club",
    "money", "bike", "pe", "me", "biz", "info", "gov", "edu", "us", "uk",
}


def is_android_package(query: str) -> bool:
    """Check if query looks like an Android package identifier (e.g. com.example.app)."""
    q = query.strip()
    if "/" in q or ":" in q:
        return False
    if re.match(r"^[a-zA-Z][a-zA-Z0-9_]*(\.[a-zA-Z][a-zA-Z0-9_]*)+$", q):
        parts = q.split(".")
        if parts[0].lower() in ("com", "org", "net", "in", "co", "io", "ind", "net"):
            if len(parts) == 2 and parts[1].lower() in COMMON_TLDS:
                return False
            return True
        if len(parts) >= 3:
            return True
    return False


def is_url(query: str) -> bool:
    """Check if query is already a URL or domain."""
    q = query.strip().lower()
    if q.startswith("http://") or q.startswith("https://"):
        return True
    if is_android_package(query):
        return False
    # Check domain-like: e.g. example.com, test.co.in
    if re.match(r"^[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+(?:/.*)?$", q):
        return True
    return False


def extract_domain(url_or_domain: str) -> str:
    """Extract registered domain or hostname."""
    url = url_or_domain.strip()
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc or parsed.path
    if ":" in host:
        host = host.split(":")[0]
    return host.lower()


def normalize_url(url: str, base_url: Optional[str] = None) -> str:
    """Normalize relative or protocol-relative URL to absolute URL."""
    url = url.strip()
    if base_url:
        url = urllib.parse.urljoin(base_url, url)
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url
    parsed = urllib.parse.urlparse(url)
    # Remove fragment
    cleaned = parsed._replace(fragment="")
    return urllib.parse.urlunparse(cleaned)


def _fetch_url_once(
    url: str,
    timeout: float,
    headers: Dict[str, str],
    head_only: bool,
    max_bytes: int,
    ssl_context: ssl.SSLContext,
) -> Tuple[int, str, str]:
    """Internal single-attempt fetch. Returns (status_code, content_text, final_url)."""
    req = urllib.request.Request(
        url,
        headers=headers,
        method="HEAD" if head_only else "GET",
    )
    with urllib.request.urlopen(req, timeout=timeout, context=ssl_context) as resp:
        final_url = resp.geturl()
        status = resp.getcode()
        if head_only:
            return status, "", final_url
        raw_bytes = resp.read(max_bytes)
        # Try utf-8 first, fallback to latin-1
        try:
            text = raw_bytes.decode("utf-8")
        except UnicodeDecodeError:
            text = raw_bytes.decode("latin-1", errors="replace")
        return status, text, final_url


def fetch_url(
    url: str,
    timeout: float = 6.0,
    headers: Optional[Dict[str, str]] = None,
    head_only: bool = False,
    max_bytes: int = 500_000,
    max_retries: int = 1,
) -> Tuple[int, str, str]:
    """
    Fetch a URL using stdlib urllib with SSL fallback and retry logic.

    - Tries secure SSL context first; falls back to permissive on SSLError.
    - Retries once on transient errors (timeout, 5xx, connection reset).

    Returns: (status_code, content_text, final_url)
    """
    req_headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    if headers:
        req_headers.update(headers)

    last_exception = None

    for attempt in range(1 + max_retries):
        if attempt > 0:
            backoff = min(2.0, 0.5 * (2 ** (attempt - 1)))
            logger.debug("Retry %d/%d for %s after %.1fs backoff", attempt, max_retries, url, backoff)
            time.sleep(backoff)

        # Try secure SSL first, then permissive on SSLError
        for ssl_ctx in (_SSL_CONTEXT_SECURE, _SSL_CONTEXT_PERMISSIVE):
            try:
                status, text, final_url = _fetch_url_once(
                    url, timeout, req_headers, head_only, max_bytes, ssl_ctx,
                )
                # If retryable server error, break inner loop to retry
                if status in _RETRYABLE_STATUS_CODES:
                    logger.debug("Retryable HTTP %d from %s (attempt %d)", status, url, attempt + 1)
                    last_exception = None
                    break
                return status, text, final_url

            except ssl.SSLError as e:
                if ssl_ctx is _SSL_CONTEXT_SECURE:
                    logger.debug("SSL verification failed for %s, retrying with permissive context: %s", url, e)
                    continue  # try permissive context
                else:
                    logger.warning("SSL error even with permissive context for %s: %s", url, e)
                    last_exception = e
                    break

            except urllib.error.HTTPError as e:
                final_url = e.geturl() if hasattr(e, "geturl") else url
                try:
                    body = e.read(100_000).decode("utf-8", errors="replace")
                except Exception:
                    body = ""
                if e.code in _RETRYABLE_STATUS_CODES:
                    logger.debug("Retryable HTTP %d from %s (attempt %d)", e.code, url, attempt + 1)
                    last_exception = e
                    break  # break inner SSL loop to retry
                return e.code, body, final_url

            except (socket.timeout, TimeoutError, ConnectionResetError, ConnectionError, OSError) as e:
                # If DNS failure (domain does not exist), fail fast without retrying
                if isinstance(e, socket.gaierror) or "getaddrinfo failed" in str(e).lower():
                    logger.debug("DNS lookup failed for %s: %s", url, e)
                    return 0, "", url
                logger.debug("Transient network error for %s (attempt %d): %s", url, attempt + 1, e)
                last_exception = e
                break  # break inner SSL loop to retry

            except Exception as e:
                logger.debug("Non-retryable error fetching %s: %s", url, e)
                return 0, "", url
        else:
            # Both SSL contexts exhausted without success — break to return failure
            break

    # Exhausted all retries
    if last_exception:
        logger.debug("All %d attempts failed for %s: %s", 1 + max_retries, url, last_exception)
    return 0, "", url


def guess_candidate_domains(entity_name: str) -> List[str]:
    """Generate probable domains for a company or app name."""
    # Strip common subtitles, colons, or trailing "app" words
    primary = re.split(r"[:\-\|\(]", entity_name)[0].strip()
    primary = re.sub(r"\s+app$", "", primary, flags=re.IGNORECASE).strip()
    clean = re.sub(r"[^a-zA-Z0-9]", "", primary or entity_name).lower()
    if not clean or len(clean) > 30:
        return []

    # Common TLDs especially relevant for Indian and global tech
    tlds = [".in", ".com", ".co.in", ".app", ".io", ".org", ".net"]
    domains = [f"{clean}{tld}" for tld in tlds]
    return domains
