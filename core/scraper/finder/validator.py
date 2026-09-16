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

"""Validator to verify whether a given URL or HTML content is a genuine Privacy Policy."""

import logging
import re
from typing import List, Tuple
from .models import ValidationResult
from .utils import fetch_url

logger = logging.getLogger("privacy_url_finder")

# Strong phrases that almost exclusively appear in privacy policies
STRONG_POLICY_PHRASES = [
    r"privacy policy",
    r"privacy notice",
    r"privacy statement",
    r"data protection policy",
    r"information we collect",
    r"how we collect and use",
    r"types of information we collect",
    r"how we use your personal (?:data|information)",
    r"personal (?:data|information) we collect",
    r"sharing of personal information",
    r"disclosure of your (?:information|personal data)",
    r"data retention",
    r"your privacy rights",
    r"grievance officer",       # Indian IT & DPDP compliance
    r"nodal officer",
    r"data protection officer",
    r"withdraw (?:your )?consent",
    r"cookies and tracking technologies",
    r"security of your information",
    r"transfer of your personal data",
]

# Medium phrases that frequently appear in privacy sections
MEDIUM_POLICY_PHRASES = [
    r"personal data",
    r"personal information",
    r"third-party service providers",
    r"third parties",
    r"ip address",
    r"credit information companies",  # Lending app specific (CIBIL, Experian, CRIF)
    r"device permissions",
    r"camera access",
    r"location data",
    r"contact information",
    r"rbi guidelines",
    r"opt-out",
    r"children's privacy",
]

# Negative indicators that denote non-policy pages
NEGATIVE_PATTERNS = [
    r"404 not found",
    r"page not found",
    r"the page you are looking for does not exist",
    r"access denied",
    r"403 forbidden",
    r"please log in to continue",
    r"sign in with your account",
    r"just a moment\.\.\. cloudflare",
]


class PolicyValidator:
    """Evaluates HTML text to ensure it is a real privacy policy."""

    def __init__(self, min_confidence: float = 0.5):
        self.min_confidence = min_confidence

    def extract_title(self, html: str) -> str:
        """Extract title tag, og:title, or h1 content from HTML."""
        match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
        if match:
            clean = re.sub(r"\s+", " ", match.group(1)).strip()
            if clean:
                if not any(k in clean.lower() for k in ("privacy", "policy")):
                    og_match = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']', html, re.IGNORECASE)
                    if not og_match:
                        og_match = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:title["\']', html, re.IGNORECASE)
                    if og_match and any(k in og_match.group(1).lower() for k in ("privacy", "policy")):
                        return re.sub(r"\s+", " ", og_match.group(1)).strip()[:120]
                return clean[:120]
        # Check og:title
        og_match = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']', html, re.IGNORECASE)
        if not og_match:
            og_match = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:title["\']', html, re.IGNORECASE)
        if og_match:
            return re.sub(r"\s+", " ", og_match.group(1)).strip()[:120]
        # Check first h1
        h1_match = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.IGNORECASE | re.DOTALL)
        if h1_match:
            clean = re.sub(r"<[^>]+>", "", h1_match.group(1))
            clean = re.sub(r"\s+", " ", clean).strip()
            return clean[:120]
        return ""

    def validate_content(self, html: str, url: str = "") -> ValidationResult:
        """Analyze HTML body for privacy policy signals."""
        if not html or len(html.strip()) < 100:
            return ValidationResult(
                is_valid=False,
                confidence=0.0,
                rejection_reason="Empty or minimal response body",
            )

        lower_html = html.lower()
        title = self.extract_title(html)
        lower_title = title.lower()

        # Check negative patterns first
        for neg in NEGATIVE_PATTERNS:
            if re.search(neg, lower_title) or (re.search(neg, lower_html[:1500]) and len(lower_html) < 2500):
                return ValidationResult(
                    is_valid=False,
                    confidence=0.0,
                    title=title,
                    rejection_reason=f"Matched negative/error signal: {neg}",
                )

        detected_signals: List[str] = []
        score = 0.0

        # Title signal
        if any(term in lower_title for term in ["privacy policy", "privacy notice", "privacy statement", "privacy"]):
            score += 0.35
            detected_signals.append(f"title_match: {title}")

        # Meta description signal
        meta_desc_match = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']', html, re.IGNORECASE)
        if not meta_desc_match:
            meta_desc_match = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']description["\']', html, re.IGNORECASE)
        if meta_desc_match:
            desc_lower = meta_desc_match.group(1).lower()
            if any(term in desc_lower for term in ["privacy policy", "privacy notice", "data protection"]):
                score += 0.15
                detected_signals.append("meta_description_privacy")

        # URL path signal
        if url:
            url_lower = url.lower()
            if any(term in url_lower for term in ["privacy", "privacy-policy", "privacypolicy", "privacy_policy"]):
                score += 0.20
                detected_signals.append("url_has_privacy_slug")

        # Strong phrases
        strong_count = 0
        for pattern in STRONG_POLICY_PHRASES:
            if re.search(pattern, lower_html):
                strong_count += 1
                if len(detected_signals) < 8:
                    detected_signals.append(f"strong_clause: {pattern}")

        score += min(0.35, strong_count * 0.08)

        # Medium phrases
        medium_count = 0
        for pattern in MEDIUM_POLICY_PHRASES:
            if re.search(pattern, lower_html):
                medium_count += 1

        score += min(0.15, medium_count * 0.03)

        # Content length check (real privacy policies usually have at least 1500 chars)
        if len(lower_html) > 2000:
            score += 0.05
        elif len(lower_html) < 400 and strong_count == 0:
            score = 0.1

        confidence = min(1.0, max(0.0, score))
        is_valid = confidence >= self.min_confidence

        return ValidationResult(
            is_valid=is_valid,
            confidence=confidence,
            title=title,
            signals=detected_signals,
            rejection_reason=None if is_valid else "Insufficient privacy policy textual signals",
        )

    def validate_url(self, url: str, timeout: float = 6.0) -> Tuple[bool, ValidationResult]:
        """Fetch URL and validate its content."""
        status, html, final_url = fetch_url(url, timeout=timeout)
        if status < 200 or status >= 400:
            return False, ValidationResult(
                is_valid=False,
                confidence=0.0,
                rejection_reason=f"HTTP status error: {status}",
            )

        res = self.validate_content(html, url=final_url)
        return res.is_valid, res
