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

"""Tests for core.scraper.finder.utils."""

from core.scraper.finder.utils import (
    extract_domain,
    guess_candidate_domains,
    is_android_package,
    is_url,
    normalize_query,
    normalize_url,
)


def test_is_android_package():
    assert is_android_package("com.kreditbee.android") is True
    assert is_android_package("in.swiggy.android") is True
    assert is_android_package("org.mozilla.firefox") is True
    assert is_android_package("KreditBee") is False
    assert is_android_package("https://kreditbee.in") is False
    assert is_android_package("swiggy.com") is False
    assert is_android_package("paytm.in") is False


def test_is_url():
    assert is_url("https://example.com") is True
    assert is_url("http://example.com/privacy") is True
    assert is_url("example.com") is True
    assert is_url("swiggy.co.in/privacy") is True
    assert is_url("KreditBee") is False
    assert is_url("com.kreditbee.android") is False


def test_extract_domain():
    assert extract_domain("https://www.example.com/path?query=1") == "www.example.com"
    assert extract_domain("example.com/privacy") == "example.com"
    assert extract_domain("https://sub.domain.org:8080/test") == "sub.domain.org"


def test_normalize_url():
    assert normalize_url("example.com") == "https://example.com"
    assert normalize_url("/privacy-policy", base_url="https://example.com") == "https://example.com/privacy-policy"
    assert normalize_url("https://example.com/p#section") == "https://example.com/p"


def test_guess_candidate_domains():
    domains = guess_candidate_domains("KreditBee")
    assert any("kreditbee.com" in d for d in domains)
    assert any("kreditbee.in" in d for d in domains)


def test_normalize_query():
    assert normalize_query("   KreditBee  \t ") == "KreditBee"
