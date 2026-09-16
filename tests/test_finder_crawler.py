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

"""Tests for crawler and heuristics resolvers."""

from unittest.mock import patch
from core.scraper.finder.models import SourceType
from core.scraper.finder.resolvers.crawler import HomepageCrawlerResolver, LinkExtractor
from core.scraper.finder.resolvers.heuristics import HeuristicsResolver

SAMPLE_LANDING_HTML = """
<html>
<body>
    <nav><a href="/home">Home</a></nav>
    <main><h1>Welcome to Our Financial Service</h1></main>
    <footer>
        <a href="/privacy-policy" title="Official Privacy Policy">Privacy Policy</a>
        <a href="/terms">Terms of Service</a>
        <a href="/about-us">About</a>
    </footer>
</body>
</html>
"""


def test_crawler_link_extractor():
    parser = LinkExtractor()
    parser.feed(SAMPLE_LANDING_HTML)
    assert len(parser.links) >= 3
    privacy_links = [l for l in parser.links if l[0] == "/privacy-policy"]
    assert len(privacy_links) == 1
    href, text, title = privacy_links[0]
    assert href == "/privacy-policy"
    assert text == "Privacy Policy"
    assert title == "Official Privacy Policy"


def test_crawler_resolver_with_mock():
    crawler = HomepageCrawlerResolver()
    with patch("core.scraper.finder.resolvers.crawler.fetch_url") as mock_fetch:
        mock_fetch.return_value = (200, SAMPLE_LANDING_HTML, "https://fintechapp.in/")
        candidates = crawler.resolve("fintechapp.in")
        assert len(candidates) >= 1
        top_cand = candidates[0]
        assert top_cand.url == "https://fintechapp.in/privacy-policy"
        assert top_cand.source == SourceType.HOMEPAGE_CRAWL
        assert top_cand.score >= 0.7


def test_heuristics_probe_with_mock():
    resolver = HeuristicsResolver(timeout=2.0)
    with patch("core.scraper.finder.resolvers.heuristics.fetch_url") as mock_fetch:
        mock_fetch.return_value = (200, "", "https://example.com/privacy")
        candidates = resolver.resolve("example.com")
        assert len(candidates) == 1
        cand = candidates[0]
        assert cand.url == "https://example.com/privacy"
        assert cand.source == SourceType.HEURISTIC
        assert cand.score >= 0.8
