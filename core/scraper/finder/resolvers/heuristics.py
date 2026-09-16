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

"""Resolver using direct URL pattern heuristics."""

import logging
import urllib.parse
from typing import List, Optional
from .base import BaseResolver
from ..models import CandidateLink, SourceType
from ..utils import extract_domain, fetch_url, is_url, normalize_url

logger = logging.getLogger("privacy_url_finder")

STANDARD_PATHS = [
    "/privacy",
    "/privacy-policy",
    "/privacy-policy/",
    "/legal/privacy",
    "/legal/privacy-policy",
    "/privacy_policy",
    "/privacypolicy.html",
    "/privacy.html",
    "/en/privacy",
    "/policies/privacy-policy",
    "/about/privacy",
    "/privacy-notice",
]


class HeuristicsResolver(BaseResolver):
    name: str = "heuristics"

    def __init__(self, timeout: float = 4.0, max_probes: int = 5):
        self.timeout = timeout
        self.max_probes = max_probes

    def resolve(self, query: str, domain: Optional[str] = None) -> List[CandidateLink]:
        target_domain = domain
        if not target_domain:
            if is_url(query):
                target_domain = extract_domain(query)
            else:
                return []

        base_url = f"https://{target_domain}"
        candidates: List[CandidateLink] = []

        for path in STANDARD_PATHS[: self.max_probes]:
            probe_url = urllib.parse.urljoin(base_url, path)
            status, _, final_url = fetch_url(probe_url, timeout=self.timeout, head_only=True)

            # If 200 and not redirected back to root
            if status == 200:
                parsed_final = urllib.parse.urlparse(final_url)
                # Ensure it didn't just redirect to homepage root "/"
                if parsed_final.path and parsed_final.path not in ("", "/"):
                    candidates.append(
                        CandidateLink(
                            url=final_url,
                            source=SourceType.HEURISTIC,
                            anchor_text=f"Probed: {path}",
                            score=0.85,
                            meta={"probed_path": path, "status_code": status},
                        )
                    )
                    break  # First successful standard path is usually the official one

        return candidates
