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

"""Unit and integration tests for PrivacyURLFinder pipeline."""

from unittest.mock import patch
import pytest

from core.scraper.finder import PrivacyURLFinder, find_policy, find_policies_batch
from core.scraper.finder.dataset.manager import DatasetManager
from core.scraper.finder.models import ResolutionStatus, SourceType


@pytest.fixture
def empty_dataset(tmp_path):
    p = tmp_path / "empty_policies.json"
    p.write_text("[]", encoding="utf-8")
    return DatasetManager(str(p))


def test_finder_dataset_query():
    finder = PrivacyURLFinder(verify=False, auto_save=False)
    res = finder.find("KreditBee")

    assert res.status == ResolutionStatus.FOUND
    assert res.source == SourceType.DATASET
    assert "kreditbee.in" in (res.url or "")
    assert res.confidence >= 0.9
    assert res.entity_name == "KreditBee"


def test_finder_dataset_alias():
    finder = PrivacyURLFinder(verify=False, auto_save=False)
    res = finder.find("krazybee")

    assert res.status == ResolutionStatus.FOUND
    assert res.source == SourceType.DATASET
    assert "kreditbee" in (res.url or "")


def test_finder_empty_query():
    finder = PrivacyURLFinder(auto_save=False)
    res = finder.find("   ")
    assert res.status == ResolutionStatus.NOT_FOUND


def test_finder_batch():
    finder = PrivacyURLFinder(verify=False, auto_save=False)
    results = finder.find_batch(["KreditBee", "Swiggy"])
    assert len(results) == 2
    assert results[0].status == ResolutionStatus.FOUND
    assert results[1].status == ResolutionStatus.FOUND


def test_finder_with_mocked_crawler(empty_dataset):
    crawler_html = """
    <html>
        <body>
            <a href="/legal/privacy-policy">Privacy Policy</a>
        </body>
    </html>
    """
    finder = PrivacyURLFinder(verify=False, dataset_manager=empty_dataset, auto_save=False)

    with patch("core.scraper.finder.resolvers.heuristics.fetch_url") as mock_heur_fetch, \
         patch("core.scraper.finder.resolvers.crawler.fetch_url") as mock_crawl_fetch:
        mock_heur_fetch.return_value = (404, "", "https://unknownstartup.io/")
        mock_crawl_fetch.return_value = (200, crawler_html, "https://unknownstartup.io/")

        res = finder.find("https://unknownstartup.io")
        assert res.status == ResolutionStatus.UNVERIFIED
        assert res.url == "https://unknownstartup.io/legal/privacy-policy"
        assert res.source == SourceType.HOMEPAGE_CRAWL


def test_finder_convenience_function():
    res = find_policy("Cred", verify=False, auto_save=False)
    assert res.status == ResolutionStatus.FOUND
    assert "cred.club" in (res.url or "")


# ----- Regression tests for GH-22 (auto_save data-integrity) -----

def test_auto_save_defaults_false():
    """auto_save must default to False so unverified guesses never pollute
    the curated dataset.  See GH-22."""
    finder = PrivacyURLFinder()
    assert finder.auto_save is False


def test_dataset_file_unchanged_after_test_run():
    """The curated policies.json must be byte-identical before and after a
    test-suite run.  If this test fails, a test mutated shipped data.
    See GH-22."""
    import hashlib
    import os

    dataset_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "core", "scraper", "finder", "dataset", "policies.json",
    )
    with open(dataset_path, "rb") as f:
        before = hashlib.sha256(f.read()).hexdigest()

    # Run a query with auto_save=False (the default) against the real dataset
    finder = PrivacyURLFinder(verify=False)
    finder.find("KreditBee")

    with open(dataset_path, "rb") as f:
        after = hashlib.sha256(f.read()).hexdigest()

    assert before == after, "policies.json was mutated during the test run!"

