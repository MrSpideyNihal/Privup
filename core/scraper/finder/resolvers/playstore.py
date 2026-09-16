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

"""Resolver that fetches developer Privacy Policy link from Google Play Store."""

import html.parser
import logging
import re
import urllib.parse
from typing import List, Optional
from .base import BaseResolver
from ..models import CandidateLink, SourceType
from ..utils import fetch_url, is_android_package

logger = logging.getLogger("privacy_url_finder")


class PlayStoreResolver(BaseResolver):
    name: str = "play_store"

    def __init__(self, timeout: float = 6.0):
        self.timeout = timeout

    def resolve(self, query: str, domain: Optional[str] = None) -> List[CandidateLink]:
        package_id = None
        if is_android_package(query):
            package_id = query.strip()
        else:
            # Try searching Play Store for the app name
            package_id = self._search_play_store_package(query)

        if not package_id:
            return []

        # Fetch Play Store app page (large payload >1MB)
        app_url = f"https://play.google.com/store/apps/details?id={package_id}&hl=en"
        status, html, _ = fetch_url(app_url, timeout=self.timeout, max_bytes=3_000_000)
        if status != 200 or not html:
            return []

        privacy_url = self._extract_privacy_url_from_play_html(html, package_id=package_id)
        if privacy_url:
            return [
                CandidateLink(
                    url=privacy_url,
                    source=SourceType.PLAY_STORE,
                    anchor_text=f"Google Play Store ({package_id})",
                    score=0.92,
                    meta={"package_id": package_id, "play_store_url": app_url},
                )
            ]
        return []

    def _search_play_store_package(self, app_name: str) -> Optional[str]:
        """Search Google Play Store for app name to get top result package ID."""
        encoded = urllib.parse.quote(app_name)
        search_url = f"https://play.google.com/store/search?q={encoded}&c=apps&hl=en"
        status, html, _ = fetch_url(search_url, timeout=self.timeout)
        if status == 200 and html:
            match = re.search(r"/store/apps/details\?id=([a-zA-Z0-9_.]+[a-zA-Z0-9_])", html)
            if match:
                return match.group(1)

        # Fallback: search engine lookup for Play Store app package
        query_ddg = urllib.parse.quote(f"{app_name} site:play.google.com/store/apps")
        ddg_url = f"https://html.duckduckgo.com/html/?q={query_ddg}"
        status_ddg, html_ddg, _ = fetch_url(ddg_url, timeout=self.timeout)
        if status_ddg == 200 and html_ddg:
            match = re.search(r"/store/apps/details\?id=([a-zA-Z0-9_.]+[a-zA-Z0-9_])", html_ddg)
            if match:
                return match.group(1)

        return None

    def _extract_privacy_url_from_play_html(self, html: str, package_id: Optional[str] = None) -> Optional[str]:
        """Extract the official developer privacy policy URL from Play Store page HTML."""
        is_google_app = package_id and package_id.startswith("com.google.")
        ignored_domains = ["android.com", "gstatic.com", "googleapis.com", "schema.org", "w3.org"]
        if not is_google_app:
            ignored_domains.append("google.com")

        # 1. Regex search for direct anchor with 'Privacy Policy' in text
        patterns = [
            r'href="([^"]+)"[^>]*>Privacy\s+(?:Policy|policy)</a>',
            r'<a[^>]+href="([^"]+)"[^>]*>[^<]*Privacy\s+policy[^<]*</a>',
            r'"https?://[^"]*(?:privacy|privacypolicy)[^"]*"',
        ]

        for pat in patterns[:2]:
            match = re.search(pat, html, re.IGNORECASE)
            if match:
                url = match.group(1)
                if url.startswith("http://") or url.startswith("https://"):
                    u_lower = url.lower()
                    if not any(ign in u_lower for ign in ignored_domains):
                        return url

        # 2. Look for developer info section URLs with privacy slug
        matches = re.findall(r'href="(https?://[^"]+)"', html)
        for url in matches:
            u_lower = url.lower()
            if "privacy" in u_lower and not any(ign in u_lower for ign in ignored_domains):
                return url

        # 3. Search script tags (AF_initDataCallback metadata blobs)
        for script in re.findall(r'<script[^>]*>(.*?)</script>', html, re.DOTALL):
            if "privacy" in script.lower():
                found = re.findall(r'https?://[^"\'\\,\s]+(?:privacy|policy)[^"\'\\,\s]*', script, re.IGNORECASE)
                for f in found:
                    f_lower = f.lower()
                    if not any(ign in f_lower for ign in ignored_domains):
                        return f

        return None
