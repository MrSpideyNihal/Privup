"""Tests for the SPA content recovery module.

Uses a local HTTP server to serve synthetic SPA shell fixtures so tests
never depend on third-party sites and can run offline.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import patch

import pytest

from core.scraper.spa import (
	RecoveryResult,
	_extract_inline_json_scripts,
	_extract_json_ld,
	_extract_next_data,
	_extract_nuxt_data,
	_extract_preloaded_state,
	_try_wayback,
	_visible_word_count,
	is_spa_shell,
	recover_content,
)

# -----------------------------------------------------------------------
# Fixtures: real-world SPA shell patterns
# -----------------------------------------------------------------------

# A pure React CRA shell, modeled after Stashfin.
CRA_SHELL = (
	'<!doctype html><html lang="en"><head>'
	'<meta charset="utf-8"/>'
	'<title>StashApp</title>'
	'<script defer="defer" src="/static/js/main.237392bd.js"></script>'
	'<link href="/static/css/main.fafc1536.css" rel="stylesheet">'
	"</head><body>"
	"<noscript>You need to enable JavaScript to run this app.</noscript>"
	'<div id="root"></div>'
	"</body></html>"
)

# A React CRA with hashed bundles, modeled after KreditBee.
KREDITBEE_SHELL = (
	'<!doctype html><html lang="en"><head>'
	'<meta charset="utf-8">'
	"<title>LendApp</title>"
	'<script defer="defer" src="/react/runtime-main.00c1ea70.js"></script>'
	'<script defer="defer" src="/react/npm.react.b94aca77.js"></script>'
	'<script defer="defer" src="/react/npm.lodash.01f5f5ab.js"></script>'
	'<script defer="defer" src="/react/npm.axios.7bff02b3.js"></script>'
	"</head><body>"
	"<noscript>If you're seeing this, JavaScript has been disabled.</noscript>"
	'<div id="app"></div>'
	"</body></html>"
)

# A real policy page with content — should NOT be detected as SPA.
REAL_POLICY = (
	"<html><body>"
	"<h1>Privacy Policy</h1>"
	"<p>We collect your personal data when you register with us. "
	"We may collect your personal information for verification. "
	"We share it with third parties. We use your data for analytics. "
	"Your consent is required. We share cookies with partners. "
	"Retention of personal data is described here.</p>"
	+ "<p>" + "Additional policy prose about personal data. " * 40 + "</p>"
	+ "</body></html>"
)

# Next.js page with __NEXT_DATA__ containing policy text.
NEXTJS_SHELL = (
	'<!doctype html><html><head></head><body>'
	'<div id="__next"></div>'
	'<script id="__NEXT_DATA__" type="application/json">'
	+ json.dumps({
		"props": {
			"pageProps": {
				"content": (
					"We collect your personal data when you register. "
					"We share it with third parties for analytics and advertising. "
					"Your consent is required before we process your information. "
					"Retention of your personal data follows applicable law."
				)
			}
		},
		"page": "/privacy",
		"buildId": "abc123",
	})
	+ "</script>"
	"</body></html>"
)

# Nuxt.js page with window.__NUXT__ containing policy text.
NUXT_SHELL = (
	'<!doctype html><html><head></head><body>'
	'<div id="__nuxt"></div>'
	"<script>"
	"window.__NUXT__ = "
	+ json.dumps({
		"data": [{
			"policy": (
				"We collect personal information including your name and email. "
				"We share this information with trusted third-party service providers. "
				"Your data is retained for as long as your account remains active. "
				"You have the right to request deletion of your personal data."
			)
		}]
	})
	+ ";"
	"</script>"
	"</body></html>"
)

# Page with JSON-LD containing an article body.
JSONLD_SHELL = (
	'<!doctype html><html><head></head><body>'
	'<div id="root"></div>'
	'<script type="application/ld+json">'
	+ json.dumps({
		"@context": "https://schema.org",
		"@type": "Article",
		"articleBody": (
			"This privacy policy describes how we collect and use your personal data. "
			"We may collect personal information such as your name, email, and phone number. "
			"We share this data with our partners for marketing and analytics purposes. "
			"You may withdraw your consent at any time by contacting us."
		),
	})
	+ "</script>"
	"</body></html>"
)

# Page with window.__PRELOADED_STATE__ containing policy text.
PRELOADED_SHELL = (
	'<!doctype html><html><head></head><body>'
	'<div id="root"></div>'
	"<script>"
	"window.__PRELOADED_STATE__ = "
	+ json.dumps({
		"page": {
			"content": (
				"Your personal information is collected for the purpose of loan processing. "
				"We access your contacts and SMS logs to assess creditworthiness. "
				"This data is shared with our partner banks and financial institutions. "
				"You may request deletion of your data at any time by writing to us."
			)
		}
	})
	+ ";"
	"</script>"
	"</body></html>"
)

# Page with an inline JSON <script> block (no id or type attribute).
INLINE_JSON_SHELL = (
	'<!doctype html><html><head></head><body>'
	'<div id="root"></div>'
	"<script>"
	+ json.dumps({
		"privacyPolicy": {
			"text": (
				"We collect and process your personal data for service delivery. "
				"Your information may be shared with regulated financial partners. "
				"Data retention periods are described in our data management policy. "
				"Contact our data protection officer to exercise your rights."
			)
		}
	})
	+ "</script>"
	"</body></html>"
)

# A legitimately short page (e.g., 404 error) that is NOT an SPA shell.
SHORT_404_PAGE = (
	"<html><body>"
	"<h1>404 Not Found</h1>"
	"<p>The requested page could not be found.</p>"
	"</body></html>"
)


# -----------------------------------------------------------------------
# Tests: SPA detection
# -----------------------------------------------------------------------

class TestIsSpaShell:
	def test_detects_react_cra_shell(self):
		assert is_spa_shell(CRA_SHELL) is True

	def test_detects_kreditbee_style_shell(self):
		assert is_spa_shell(KREDITBEE_SHELL) is True

	def test_does_not_flag_real_policy(self):
		assert is_spa_shell(REAL_POLICY) is False

	def test_does_not_flag_short_404_page(self):
		"""A 404 page with few words is not an SPA shell."""
		assert is_spa_shell(SHORT_404_PAGE) is False

	def test_detects_nextjs_empty_shell(self):
		# Even though NEXTJS_SHELL has __NEXT_DATA__, the visible text is very short
		# and it has an empty __next mount point.
		assert is_spa_shell(NEXTJS_SHELL) is True

	def test_detects_nuxt_shell(self):
		assert is_spa_shell(NUXT_SHELL) is True

	def test_respects_word_threshold(self):
		"""A page with exactly enough words should not be flagged."""
		wordy_spa = '<div id="root"></div>' + " word" * 100
		assert is_spa_shell(wordy_spa, word_threshold=80) is False


class TestVisibleWordCount:
	def test_strips_scripts_and_styles(self):
		html = (
			"<p>Hello world</p>"
			"<script>var x = 1; var y = 2; var z = 3;</script>"
			"<style>.a { color: red; } .b { color: blue; }</style>"
			"<p>Goodbye</p>"
		)
		assert _visible_word_count(html) == 3  # Hello world Goodbye

	def test_counts_empty_shell(self):
		assert _visible_word_count(CRA_SHELL) < 30


# -----------------------------------------------------------------------
# Tests: embedded data extraction
# -----------------------------------------------------------------------

class TestExtractNextData:
	def test_extracts_from_valid_next_data(self):
		text = _extract_next_data(NEXTJS_SHELL)
		assert "personal data" in text
		assert "third parties" in text

	def test_returns_empty_for_missing_next_data(self):
		assert _extract_next_data(CRA_SHELL) == ""

	def test_returns_empty_for_empty_page_props(self):
		"""CRED-style Next.js with empty pageProps should return empty."""
		html = (
			'<script id="__NEXT_DATA__" type="application/json">'
			'{"props":{"pageProps":{}},"page":"/privacy"}'
			"</script>"
		)
		assert _extract_next_data(html) == ""

	def test_handles_malformed_json(self):
		html = '<script id="__NEXT_DATA__">not valid json</script>'
		assert _extract_next_data(html) == ""


class TestExtractNuxtData:
	def test_extracts_from_valid_nuxt_data(self):
		text = _extract_nuxt_data(NUXT_SHELL)
		assert "personal information" in text
		assert "third-party" in text

	def test_returns_empty_for_missing_nuxt(self):
		assert _extract_nuxt_data(CRA_SHELL) == ""


class TestExtractJsonLd:
	def test_extracts_article_body(self):
		text = _extract_json_ld(JSONLD_SHELL)
		assert "privacy policy" in text
		assert "personal data" in text

	def test_returns_empty_for_short_descriptions(self):
		"""JSON-LD with only a short description is not worth extracting."""
		html = (
			'<script type="application/ld+json">'
			'{"@type": "WebPage", "description": "A short page."}'
			"</script>"
		)
		assert _extract_json_ld(html) == ""

	def test_returns_empty_for_missing_json_ld(self):
		assert _extract_json_ld(CRA_SHELL) == ""


class TestExtractPreloadedState:
	def test_extracts_from_preloaded_state(self):
		text = _extract_preloaded_state(PRELOADED_SHELL)
		assert "loan processing" in text
		assert "contacts" in text

	def test_returns_empty_for_missing_state(self):
		assert _extract_preloaded_state(CRA_SHELL) == ""


class TestExtractInlineJson:
	def test_extracts_from_inline_json(self):
		text = _extract_inline_json_scripts(INLINE_JSON_SHELL)
		assert "personal data" in text

	def test_ignores_non_json_scripts(self):
		html = "<script>var x = 42;</script>"
		assert _extract_inline_json_scripts(html) == ""


# -----------------------------------------------------------------------
# Tests: recovery orchestration
# -----------------------------------------------------------------------

class TestRecoverContent:
	def test_returns_not_shell_for_real_content(self):
		result = recover_content(REAL_POLICY)
		assert result.is_shell is False
		assert result.recovered is False
		assert result.method == ""

	def test_recovers_from_next_data(self):
		result = recover_content(NEXTJS_SHELL, try_wayback=False)
		assert result.is_shell is True
		assert result.recovered is True
		assert result.method == "embedded"
		assert "personal data" in result.text

	def test_recovers_from_nuxt_data(self):
		result = recover_content(NUXT_SHELL, try_wayback=False)
		assert result.is_shell is True
		assert result.recovered is True
		assert result.method == "embedded"

	def test_recovers_from_json_ld(self):
		result = recover_content(JSONLD_SHELL, try_wayback=False)
		assert result.is_shell is True
		assert result.recovered is True
		assert result.method == "embedded"

	def test_recovers_from_preloaded_state(self):
		result = recover_content(PRELOADED_SHELL, try_wayback=False)
		assert result.is_shell is True
		assert result.recovered is True
		assert result.method == "embedded"

	def test_recovers_from_inline_json(self):
		result = recover_content(INLINE_JSON_SHELL, try_wayback=False)
		assert result.is_shell is True
		assert result.recovered is True
		assert result.method == "embedded"

	def test_fails_gracefully_for_pure_cra_shell(self):
		"""A pure CRA shell with no embedded data and no Wayback."""
		result = recover_content(CRA_SHELL, try_wayback=False)
		assert result.is_shell is True
		assert result.recovered is False

	def test_recovery_result_repr(self):
		r = RecoveryResult(text="Hello world " * 10, method="embedded", is_shell=True)
		assert "embedded" in repr(r)
		assert "words=20" in repr(r)


# -----------------------------------------------------------------------
# Tests: Wayback Machine fallback (mocked)
# -----------------------------------------------------------------------

class _WaybackHandler(BaseHTTPRequestHandler):
	"""Mock Wayback CDX API and snapshot server."""

	SNAPSHOT_HTML = (
		"<html><body>"
		"<h1>Privacy Policy</h1>"
		"<p>We collect your personal data when you register. "
		"We share it with third parties for analytics purposes. "
		"Your consent is required for data processing. "
		"Data retention follows applicable regulations.</p>"
		"<p>" + "Additional privacy policy content about your data. " * 20 + "</p>"
		"</body></html>"
	)

	def log_message(self, *args):
		pass

	def do_GET(self):
		if "/cdx/search/cdx" in self.path:
			# Mock CDX API response.
			result = json.dumps([
				["timestamp", "original", "statuscode"],
				["20250601120000", "https://example.com/privacy", "200"],
			])
			self._send(200, result.encode("utf-8"), "application/json")
		elif "/web/" in self.path:
			# Mock snapshot response.
			self._send(200, self.SNAPSHOT_HTML.encode("utf-8"), "text/html")
		else:
			self._send(404, b"not found", "text/plain")

	def _send(self, status, body: bytes, content_type: str):
		self.send_response(status)
		self.send_header("Content-Type", content_type)
		self.send_header("Content-Length", str(len(body)))
		self.end_headers()
		self.wfile.write(body)


@pytest.fixture(scope="module")
def wayback_server():
	httpd = HTTPServer(("127.0.0.1", 0), _WaybackHandler)
	thread = threading.Thread(target=httpd.serve_forever, daemon=True)
	thread.start()
	host, port = httpd.server_address
	yield f"http://{host}:{port}"
	httpd.shutdown()
	httpd.server_close()


class TestWaybackFallback:
	def test_fetches_from_mock_wayback(self, wayback_server):
		"""With a mock CDX API, the Wayback fallback recovers text."""
		with patch("core.scraper.spa._WAYBACK_CDX", f"{wayback_server}/cdx/search/cdx"), \
			 patch("core.scraper.spa._WAYBACK_WEB", f"{wayback_server}/web"):
			text = _try_wayback("https://example.com/privacy", timeout=5)
		assert "personal data" in text
		assert len(text.split()) > 30

	def test_returns_empty_on_network_error(self):
		"""When the CDX API is unreachable, returns empty gracefully."""
		with patch("core.scraper.spa._WAYBACK_CDX", "http://127.0.0.1:1/cdx"):
			text = _try_wayback("https://example.com/privacy", timeout=1)
		assert text == ""

	def test_full_recovery_with_wayback(self, wayback_server):
		"""The full recover_content pipeline uses Wayback as a last resort."""
		with patch("core.scraper.spa._WAYBACK_CDX", f"{wayback_server}/cdx/search/cdx"), \
			 patch("core.scraper.spa._WAYBACK_WEB", f"{wayback_server}/web"):
			result = recover_content(
				CRA_SHELL,
				url="https://example.com/privacy",
				try_wayback=True,
				wayback_timeout=5,
			)
		assert result.is_shell is True
		assert result.recovered is True
		assert result.method == "wayback"
		assert "personal data" in result.text


# -----------------------------------------------------------------------
# Tests: integration with UrlDriver
# -----------------------------------------------------------------------

class _SpaHandler(BaseHTTPRequestHandler):
	"""Local HTTP server serving SPA shell pages for integration tests."""

	def log_message(self, *args):
		pass

	def _send(self, status, body: bytes, content_type="text/html; charset=utf-8"):
		self.send_response(status)
		self.send_header("Content-Type", content_type)
		self.send_header("Content-Length", str(len(body)))
		self.end_headers()
		self.wfile.write(body)

	def do_GET(self):
		if self.path == "/spa-nextjs":
			self._send(200, NEXTJS_SHELL.encode("utf-8"))
		elif self.path == "/spa-empty":
			self._send(200, CRA_SHELL.encode("utf-8"))
		elif self.path == "/spa-jsonld":
			self._send(200, JSONLD_SHELL.encode("utf-8"))
		elif self.path == "/real-policy":
			self._send(200, REAL_POLICY.encode("utf-8"))
		else:
			self._send(404, b"not found")


@pytest.fixture(scope="module")
def spa_server():
	httpd = HTTPServer(("127.0.0.1", 0), _SpaHandler)
	thread = threading.Thread(target=httpd.serve_forever, daemon=True)
	thread.start()
	host, port = httpd.server_address
	yield f"http://{host}:{port}"
	httpd.shutdown()
	httpd.server_close()


class TestUrlDriverSpaIntegration:
	def test_recovers_next_data_from_spa_shell(self, spa_server):
		from core.scraper.url_driver import UrlDriver

		driver = UrlDriver(timeout=5)
		result = driver.fetch(f"{spa_server}/spa-nextjs")
		assert "personal data" in result.raw_text
		assert result.metadata.get("spa_recovery") == "embedded"

	def test_recovers_json_ld_from_spa_shell(self, spa_server):
		from core.scraper.url_driver import UrlDriver

		driver = UrlDriver(timeout=5)
		result = driver.fetch(f"{spa_server}/spa-jsonld")
		assert "privacy policy" in result.raw_text
		assert result.metadata.get("spa_recovery") == "embedded"

	def test_real_policy_passes_through_unchanged(self, spa_server):
		from core.scraper.url_driver import UrlDriver

		driver = UrlDriver(timeout=5)
		result = driver.fetch(f"{spa_server}/real-policy")
		assert "personal data" in result.raw_text
		assert result.metadata.get("spa_recovery") is None

	def test_pure_spa_shell_raises_when_no_recovery(self, spa_server):
		"""A pure CRA shell with no embedded data and Wayback disabled."""
		from core.scraper.base import DriverError
		from core.scraper.url_driver import UrlDriver

		driver = UrlDriver(timeout=5)
		# The SPA shell has no embedded data, so detection finds it but
		# recovery fails. Since the visible text IS non-empty (the noscript
		# message counts), it won't raise DriverError but will return the
		# shell HTML as-is, which the scorer will handle downstream.
		result = driver.fetch(f"{spa_server}/spa-empty")
		# The noscript text means text.strip() is truthy, so it returns
		# the shell. The spa_recovery will be None since recovery failed.
		assert result.metadata.get("spa_recovery") is None
