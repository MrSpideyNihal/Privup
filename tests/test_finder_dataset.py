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
# This code integrates privacy-url-finder tests:
# https://github.com/MrSpideyNihal/privacy-url-finder
#

"""Tests for core.scraper.finder curated dataset manager and resolver."""

from core.scraper.finder.dataset.manager import DatasetManager
from core.scraper.finder.resolvers.dataset_resolver import DatasetResolver


def test_dataset_loads_entries():
    mgr = DatasetManager()
    assert len(mgr.entries) >= 40


def test_dataset_lookup_exact_name():
    mgr = DatasetManager()
    entry = mgr.lookup("KreditBee")
    assert entry is not None
    assert "kreditbee" in entry["privacy_url"].lower()


def test_dataset_lookup_case_insensitive():
    mgr = DatasetManager()
    entry = mgr.lookup("swiggy")
    assert entry is not None
    assert "swiggy" in entry["privacy_url"].lower()


def test_dataset_lookup_domain():
    mgr = DatasetManager()
    entry = mgr.lookup("kreditbee.in")
    assert entry is not None
    assert entry["name"] == "KreditBee"


def test_dataset_resolver_returns_candidates():
    resolver = DatasetResolver()
    candidates = resolver.resolve("Paytm")
    assert len(candidates) >= 1
    assert candidates[0].score >= 0.95
    assert candidates[0].url


def test_dataset_resolver_unknown_query_empty():
    resolver = DatasetResolver()
    candidates = resolver.resolve("NonExistentCompanyXYZ999")
    assert candidates == []
