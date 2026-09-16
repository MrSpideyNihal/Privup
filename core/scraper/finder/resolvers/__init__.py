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

"""Resolvers package for Privacy URL Finder."""

from .base import BaseResolver
from .crawler import HomepageCrawlerResolver
from .dataset_resolver import DatasetResolver
from .heuristics import HeuristicsResolver
from .playstore import PlayStoreResolver
from .search import SearchResolver

__all__ = [
    "BaseResolver",
    "DatasetResolver",
    "HeuristicsResolver",
    "HomepageCrawlerResolver",
    "PlayStoreResolver",
    "SearchResolver",
]
