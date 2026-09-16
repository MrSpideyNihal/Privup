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

"""Resolver that uses search engine fallback to locate privacy policy pages."""

import html
import logging
import re
import urllib.parse
from typing import List, Optional
from .base import BaseResolver
from ..models import CandidateLink, SourceType
from ..utils import DEFAULT_USER_AGENT, fetch_url

logger = logging.getLogger("privacy_url_finder")


class SearchResolver(BaseResolver):
    name: str = "web_search"

    def __init__(self, timeout: float = 7.0):
        self.timeout = timeout

    def resolve(self, query: str, domain: Optional[str] = None) -> List[CandidateLink]:
        search_query = f"{query} privacy policy official"
        encoded = urllib.parse.quote(search_query)

        # DuckDuckGo HTML endpoint
        url = f"https://html.duckduckgo.com/html/?q={encoded}"
        headers = {
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": "https://html.duckduckgo.com/",
        }

        status, body, _ = fetch_url(url, timeout=self.timeout, headers=headers)
        if status != 200 or not body:
            # Try lite endpoint
            url_lite = f"https://lite.duckduckgo.com/lite/?q={encoded}"
            status, body, _ = fetch_url(url_lite, timeout=self.timeout, headers=headers)
            if status != 200 or not body:
                return []

        candidates = self._parse_ddg_results(body)
        return candidates

    def _parse_ddg_results(self, html_text: str) -> List[CandidateLink]:
        candidates: List[CandidateLink] = []
        # Find result links in DDG HTML: class="result__url" or href="//duckduckgo.com/l/?uddg=..."
        # Pattern 1: DDG redirect link containing uddg param
        redirect_matches = re.findall(r'href="[^"]*uddg=([^"&]+)[^"]*"', html_text)
        for enc_url in redirect_matches:
            target_url = urllib.parse.unquote(enc_url)
            if target_url.startswith("http://") or target_url.startswith("https://"):
                url_lower = target_url.lower()
                # Skip search aggregators
                if any(x in url_lower for x in ["duckduckgo.com", "google.com", "bing.com", "wikipedia.org"]):
                    continue
                score = 0.60
                if "privacy" in url_lower:
                    score = 0.85
                candidates.append(
                    CandidateLink(
                        url=target_url,
                        source=SourceType.WEB_SEARCH,
                        anchor_text="Web Search Result",
                        score=score,
                    )
                )

        # Pattern 2: Direct links in lite or fallback format
        if not candidates:
            matches = re.findall(r'<a[^>]+class="result-link"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', html_text)
            for link_url, link_text in matches:
                clean_url = html.unescape(link_url)
                clean_text = re.sub(r"<[^>]+>", "", link_text).strip()
                if clean_url.startswith("http://") or clean_url.startswith("https://"):
                    score = 0.70 if "privacy" in clean_url.lower() or "privacy" in clean_text.lower() else 0.50
                    candidates.append(
                        CandidateLink(
                            url=clean_url,
                            source=SourceType.WEB_SEARCH,
                            anchor_text=clean_text[:80],
                            score=score,
                        )
                    )

        return candidates[:5]
