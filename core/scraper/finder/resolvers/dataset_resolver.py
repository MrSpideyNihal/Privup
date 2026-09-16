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

"""Resolver that looks up the query in the curated dataset."""

from typing import List, Optional
from .base import BaseResolver
from ..dataset.manager import DatasetManager
from ..models import CandidateLink, SourceType


class DatasetResolver(BaseResolver):
    name: str = "dataset"

    def __init__(self, dataset_manager: Optional[DatasetManager] = None):
        self.dataset = dataset_manager or DatasetManager()

    def resolve(self, query: str, domain: Optional[str] = None) -> List[CandidateLink]:
        # 1. Lookup query directly
        entry = self.dataset.lookup(query)
        # 2. If not found and domain is provided, lookup domain
        if not entry and domain:
            entry = self.dataset.lookup(domain)

        if entry and entry.get("privacy_url"):
            return [
                CandidateLink(
                    url=entry["privacy_url"],
                    source=SourceType.DATASET,
                    anchor_text=entry.get("name", "Curated Dataset"),
                    score=0.98,
                    meta={
                        "id": entry.get("id"),
                        "name": entry.get("name"),
                        "domain": entry.get("domain"),
                        "category": entry.get("category"),
                        "terms_url": entry.get("terms_url"),
                        "regulated_nbfc": entry.get("regulated_nbfc"),
                        "country": entry.get("country"),
                    },
                )
            ]
        return []
