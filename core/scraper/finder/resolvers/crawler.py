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

"""Resolver that crawls a homepage and extracts links matching privacy keywords."""

import html.parser
import logging
import re
import urllib.parse
from typing import List, Optional, Tuple
from .base import BaseResolver
from ..models import CandidateLink, SourceType
from ..utils import extract_domain, fetch_url, is_url, normalize_url

logger = logging.getLogger("privacy_url_finder")

KEYWORDS_TEXT_STRONG = [
    r"^privacy\s+policy$",
    r"^privacy\s+notice$",
    r"^privacy\s+statement$",
    r"^data\s+protection\s+policy$",
    r"^privacy$",
]

KEYWORDS_TEXT_MEDIUM = [
    r"privacy",
    r"data protection",
    r"terms & privacy",
    r"security & privacy",
    r"legal & privacy",
]

KEYWORDS_HREF_STRONG = [
    r"/privacy[-_]policy",
    r"/privacypolicy",
    r"/privacy/?$",
    r"/legal/privacy",
]


class LinkExtractor(html.parser.HTMLParser):
    """HTML Parser to extract anchor tags with their text and attributes."""

    def __init__(self):
        super().__init__()
        self.links: List[Tuple[str, str, str]] = []  # (href, text, title)
        self._current_href: Optional[str] = None
        self._current_text: List[str] = []
        self._current_title: str = ""

    def handle_starttag(self, tag: str, attrs: list):
        if tag.lower() == "a":
            attrs_dict = dict(attrs)
            self._current_href = attrs_dict.get("href")
            self._current_title = attrs_dict.get("title", "") or attrs_dict.get("aria-label", "")
            self._current_text = []

    def handle_data(self, data: str):
        if self._current_href is not None:
            self._current_text.append(data)

    def handle_endtag(self, tag: str):
        if tag.lower() == "a" and self._current_href is not None:
            raw_text = " ".join(self._current_text).strip()
            self.links.append((self._current_href, raw_text, self._current_title))
            self._current_href = None
            self._current_text = []
            self._current_title = ""


class HomepageCrawlerResolver(BaseResolver):
    name: str = "homepage_crawl"

    def __init__(self, timeout: float = 6.0):
        self.timeout = timeout

    def resolve(self, query: str, domain: Optional[str] = None) -> List[CandidateLink]:
        target_domain = domain
        if not target_domain:
            if is_url(query):
                target_domain = extract_domain(query)
            else:
                return []

        base_url = f"https://{target_domain}"
        status, html_content, final_url = fetch_url(base_url, timeout=self.timeout)
        if status < 200 or status >= 400 or not html_content:
            return []

        parser = LinkExtractor()
        try:
            parser.feed(html_content)
        except Exception as e:
            logger.debug("LinkExtractor parsing warning for %s: %s", base_url, e)

        scored_candidates: List[CandidateLink] = []
        seen_urls = set()

        for href, text, title_attr in parser.links:
            if not href or href.startswith("javascript:") or href.startswith("mailto:") or href.startswith("tel:"):
                continue

            clean_text = text.strip()
            text_lower = clean_text.lower()
            href_lower = href.lower()
            title_lower = title_attr.lower()

            score = 0.0

            # Text scoring
            for pattern in KEYWORDS_TEXT_STRONG:
                if re.search(pattern, text_lower):
                    score += 0.50
                    break
            else:
                for pattern in KEYWORDS_TEXT_MEDIUM:
                    if re.search(pattern, text_lower):
                        score += 0.35
                        break

            # Title attribute scoring
            if any(term in title_lower for term in ["privacy policy", "privacy", "data protection"]):
                score += 0.20

            # Href scoring
            for pattern in KEYWORDS_HREF_STRONG:
                if re.search(pattern, href_lower):
                    score += 0.35
                    break
            else:
                if "privacy" in href_lower:
                    score += 0.20

            # Disqualify irrelevant or external social links
            if any(term in href_lower for term in ["facebook.com", "twitter.com", "instagram.com", "linkedin.com"]):
                continue

            if score >= 0.35:
                abs_url = normalize_url(href, base_url=final_url)
                if abs_url not in seen_urls:
                    seen_urls.add(abs_url)
                    display_text = clean_text or title_attr or "Privacy Link"
                    scored_candidates.append(
                        CandidateLink(
                            url=abs_url,
                            source=SourceType.HOMEPAGE_CRAWL,
                            anchor_text=display_text[:80],
                            score=min(0.95, score),
                            meta={"raw_href": href},
                        )
                    )

        scored_candidates.sort(key=lambda c: c.score, reverse=True)
        return scored_candidates
