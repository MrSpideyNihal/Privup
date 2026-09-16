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

"""Tests for CompanyDriver and UrlDriver company name resolution."""

from pathlib import Path
from unittest.mock import patch
import pytest

from core.main import run
from core.models import DriverResult
from core.scraper import DriverError, get_driver
from core.scraper.fetcher import Response
from core.scraper.finder import PolicyResult, ResolutionStatus, find_policy
from core.scraper.url_driver import CompanyDriver, UrlDriver


POLICY_HTML = """
<html>
<head><title>KreditBee Privacy Policy</title></head>
<body>
    <h1>Privacy Policy</h1>
    <p>We access your contact list and call logs to evaluate creditworthiness.</p>
    <p>We retain your personal data indefinitely. Personal data is shared with third parties.</p>
</body>
</html>
"""


def test_company_driver_registered():
    driver = get_driver("company")
    assert isinstance(driver, CompanyDriver)
    assert driver.name == "company"


def test_url_driver_registered():
    driver = get_driver("url")
    assert isinstance(driver, UrlDriver)


def test_find_policy_curated_dataset():
    res = find_policy("KreditBee", verify=False)
    assert res.status == ResolutionStatus.FOUND
    assert "kreditbee" in res.url.lower()
    assert res.entity_name == "KreditBee"


def test_url_driver_fetches_company_with_mocked_fetch():
    mock_resp = Response(
        body=POLICY_HTML.encode("utf-8"),
        final_url="https://www.kreditbee.in/privacy-policy",
        status=200,
        content_type="text/html",
        charset="utf-8",
    )

    with patch("core.scraper.url_driver.fetch_url", return_value=mock_resp):
        driver = UrlDriver()
        result = driver.fetch("KreditBee")

        assert isinstance(result, DriverResult)
        assert result.origin == "https://www.kreditbee.in/privacy-policy"
        assert "contact list" in result.raw_text
        assert result.metadata["entity_name"] == "KreditBee"
        assert result.metadata["resolved_policy_url"] == "https://www.kreditbee.in/privacy-policy"
        assert result.metadata["resolved_via"] == "curated_dataset"


def test_company_driver_fetches_company():
    mock_resp = Response(
        body=POLICY_HTML.encode("utf-8"),
        final_url="https://www.kreditbee.in/privacy-policy",
        status=200,
        content_type="text/html",
        charset="utf-8",
    )

    with patch("core.scraper.url_driver.fetch_url", return_value=mock_resp):
        driver = CompanyDriver()
        result = driver.fetch("KreditBee")

        assert isinstance(result, DriverResult)
        assert result.metadata["entity_name"] == "KreditBee"


def test_end_to_end_pipeline_with_company_name():
    mock_resp = Response(
        body=POLICY_HTML.encode("utf-8"),
        final_url="https://www.kreditbee.in/privacy-policy",
        status=200,
        content_type="text/html",
        charset="utf-8",
    )

    with patch("core.scraper.url_driver.fetch_url", return_value=mock_resp):
        verdict = run(driver_name="url", target="KreditBee", tag_set_name="loan_app")
        assert verdict.decision.value in ("warning", "deny")
        assert len(verdict.findings) > 0


def test_unknown_company_raises_driver_error():
    driver = UrlDriver()
    with patch("core.scraper.finder.finder.PrivacyURLFinder.find") as mock_find:
        mock_find.return_value = PolicyResult(
            query="NonExistentCompanyXYZ999999",
            status=ResolutionStatus.NOT_FOUND,
            method="exhausted_all_tiers",
        )
        with pytest.raises(DriverError, match="Could not find a verified privacy policy"):
            driver.fetch("NonExistentCompanyXYZ999999")


def test_watermark_present_in_integrated_files():
    watermark_marker = "PRIVACY-URL-FINDER"
    repo_root = Path(__file__).resolve().parents[1]

    # Check url_driver.py
    url_driver_code = (repo_root / "core" / "scraper" / "url_driver.py").read_text(encoding="utf-8")
    assert watermark_marker in url_driver_code

    # Check resolver.py
    resolver_code = (repo_root / "core" / "scraper" / "resolver.py").read_text(encoding="utf-8")
    assert watermark_marker in resolver_code

    # Check finder/__init__.py
    finder_init_code = (repo_root / "core" / "scraper" / "finder" / "__init__.py").read_text(encoding="utf-8")
    assert watermark_marker in finder_init_code
