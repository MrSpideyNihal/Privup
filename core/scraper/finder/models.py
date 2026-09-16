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

"""Data models for Privacy URL Finder."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class ResolutionStatus(str, Enum):
    FOUND = "FOUND"             # Verified policy page with strong confidence
    PROBABLE = "PROBABLE"       # High-scoring link found, likely valid
    UNVERIFIED = "UNVERIFIED"   # Candidate link found but unverified or verification skipped
    NOT_FOUND = "NOT_FOUND"     # No valid policy found after all tiers


class SourceType(str, Enum):
    DATASET = "DATASET"
    HEURISTIC = "HEURISTIC"
    HOMEPAGE_CRAWL = "HOMEPAGE_CRAWL"
    PLAY_STORE = "PLAY_STORE"
    WEB_SEARCH = "WEB_SEARCH"
    DIRECT = "DIRECT"


@dataclass
class CandidateLink:
    url: str
    source: SourceType
    anchor_text: str = ""
    score: float = 0.0
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidationResult:
    is_valid: bool
    confidence: float
    title: str = ""
    signals: List[str] = field(default_factory=list)
    rejection_reason: Optional[str] = None
    sample_text: str = ""


@dataclass
class PolicyResult:
    query: str
    status: ResolutionStatus
    url: Optional[str] = None
    source: Optional[SourceType] = None
    confidence: float = 0.0
    title: str = ""
    method: str = ""
    entity_name: Optional[str] = None
    domain: Optional[str] = None
    validation: Optional[ValidationResult] = None
    alternate_links: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    elapsed_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "status": self.status.value,
            "url": self.url,
            "source": self.source.value if self.source else None,
            "confidence": round(self.confidence, 3),
            "title": self.title,
            "method": self.method,
            "entity_name": self.entity_name,
            "domain": self.domain,
            "validation": {
                "is_valid": self.validation.is_valid,
                "confidence": round(self.validation.confidence, 3),
                "title": self.validation.title,
                "signals": self.validation.signals,
                "rejection_reason": self.validation.rejection_reason,
            } if self.validation else None,
            "alternate_links": self.alternate_links,
            "metadata": self.metadata,
            "elapsed_ms": round(self.elapsed_ms, 2),
        }
