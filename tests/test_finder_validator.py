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

"""Tests for core.scraper.finder.validator."""

from core.scraper.finder.validator import PolicyValidator

SAMPLE_POLICY_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Privacy Policy - ACME Corporation</title>
</head>
<body>
    <h1>Privacy Policy</h1>
    <p>This privacy notice explains how we collect and use your personal information and personal data.</p>
    <p>Information we collect includes your device permissions, camera access, and contact information.</p>
    <p>We do not sell personal data to third parties without your consent. You may withdraw consent at any time.</p>
    <p>For inquiries, contact our Grievance Officer or Data Protection Officer.</p>
</body>
</html>
"""

SAMPLE_404_HTML = """
<!DOCTYPE html>
<html>
<head><title>404 Not Found</title></head>
<body><h1>Page Not Found</h1><p>The page you are looking for does not exist.</p></body>
</html>
"""


def test_validator_extract_title():
    validator = PolicyValidator()
    title = validator.extract_title(SAMPLE_POLICY_HTML)
    assert "Privacy Policy" in title


def test_validator_validates_genuine_policy():
    validator = PolicyValidator()
    result = validator.validate_content(SAMPLE_POLICY_HTML, url="https://example.com/privacy")
    assert result.is_valid is True
    assert result.confidence >= 0.70
    assert len(result.signals) >= 3


def test_validator_rejects_404_page():
    validator = PolicyValidator()
    result = validator.validate_content(SAMPLE_404_HTML, url="https://example.com/missing")
    assert result.is_valid is False
    assert result.rejection_reason is not None
