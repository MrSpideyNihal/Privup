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

"""Base resolver interface."""

from abc import ABC, abstractmethod
from typing import List, Optional
from ..models import CandidateLink


class BaseResolver(ABC):
    """Abstract base class for URL resolvers."""

    name: str = "base"

    @abstractmethod
    def resolve(self, query: str, domain: Optional[str] = None) -> List[CandidateLink]:
        """
        Attempt to discover candidate privacy policy links for a query.
        Returns a list of CandidateLink ordered by score descending.
        """
        pass
