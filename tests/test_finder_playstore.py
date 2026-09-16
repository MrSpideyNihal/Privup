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

"""Unit tests for PlayStoreResolver."""

from unittest.mock import patch
from core.scraper.finder.models import SourceType
from core.scraper.finder.resolvers.playstore import PlayStoreResolver

MOCK_PLAY_STORE_HTML = """
<!DOCTYPE html>
<html>
<body>
    <h1>LendingPro Quick Loan</h1>
    <div>Developer contact</div>
    <a href="mailto:support@lendingpro.in">Support</a>
    <a href="https://www.lendingpro.in/legal/privacy-policy">Privacy policy</a>
    <a href="https://support.google.com/googleplay">Help</a>
</body>
</html>
"""


def test_playstore_resolver_with_package_id():
    resolver = PlayStoreResolver(timeout=2.0)

    with patch("core.scraper.finder.resolvers.playstore.fetch_url") as mock_fetch:
        mock_fetch.return_value = (200, MOCK_PLAY_STORE_HTML, "https://play.google.com/store/apps/details?id=com.lendingpro.app")

        candidates = resolver.resolve("com.lendingpro.app")
        assert len(candidates) == 1
        cand = candidates[0]
        assert cand.url == "https://www.lendingpro.in/legal/privacy-policy"
        assert cand.source == SourceType.PLAY_STORE
        assert cand.score >= 0.9
        assert cand.meta.get("package_id") == "com.lendingpro.app"
