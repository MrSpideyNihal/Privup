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

"""Privacy URL Finder - Intelligent privacy policy URL discovery and verification engine."""

from .dataset.manager import DatasetManager
from .finder import PrivacyURLFinder
from .models import (
    CandidateLink,
    PolicyResult,
    ResolutionStatus,
    SourceType,
    ValidationResult,
)
from .validator import PolicyValidator

__version__ = "0.1.0"


def find_policy(
    query: str,
    verify: bool = True,
    timeout: float = 6.0,
    enable_search: bool = True,
    auto_save: bool = True,
) -> PolicyResult:
    """
    Convenience function to find the official privacy policy URL for an app, service, or URL.

    Example:
        >>> from privacy_url_finder import find_policy
        >>> res = find_policy("KreditBee")
        >>> print(res.url, res.confidence)
        https://www.kreditbee.in/privacy-policy 0.98
    """
    finder = PrivacyURLFinder(
        verify=verify,
        timeout=timeout,
        enable_search_fallback=enable_search,
        auto_save=auto_save,
    )
    return finder.find(query)


def find_policies_batch(
    queries: list,
    verify: bool = True,
    timeout: float = 6.0,
) -> list:
    """Convenience function to resolve multiple queries in sequence."""
    finder = PrivacyURLFinder(verify=verify, timeout=timeout)
    return finder.find_batch(queries)


__all__ = [
    "PrivacyURLFinder",
    "DatasetManager",
    "PolicyValidator",
    "PolicyResult",
    "ResolutionStatus",
    "SourceType",
    "ValidationResult",
    "CandidateLink",
    "find_policy",
    "find_policies_batch",
    "__version__",
]
