"""url_driver, against a local HTTP server.

A real socket and a real HTTP exchange, but nothing leaves the machine. Tests
that depend on a live lender's website fail when that lender redesigns, which
teaches the team to ignore red builds.
"""

from __future__ import annotations

import gzip
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from core.scraper import DriverError, get_driver
from core.scraper.extractor import decode, looks_like_policy
from core.scraper.fetcher import normalize_url
from core.scraper.resolver import find_policy_links, resolve
from core.scraper.url_driver import UrlDriver

POLICY_BODY = (
	"<h1>Privacy Policy</h1>"
	"<p>We collect your personal data when you register with us. "
	"We may collect your personal information for verification. "
	"We share it with third parties. We use your data for analytics. "
	"Your consent is required. We share cookies with partners. "
	"Retention of personal data is described here.</p>"
	+ "<p>" + "Additional policy prose about personal data. " * 40 + "</p>"
)

HOMEPAGE_BODY = (
	'<html><body><nav><a href="/">Home</a></nav>'
	"<h1>Get a loan in minutes</h1>"
	"<p>" + "Fast approval and great rates for everyone. " * 60 + "</p>"
	'<footer><a href="/privacy-policy">Privacy Policy</a>'
	'<a href="/about">About</a></footer></body></html>'
)


class _Handler(BaseHTTPRequestHandler):
	def log_message(self, *args):  # keep test output clean
		pass

	def _send(self, status, body: bytes, content_type="text/html; charset=utf-8", extra=None):
		self.send_response(status)
		self.send_header("Content-Type", content_type)
		self.send_header("Content-Length", str(len(body)))
		for key, value in (extra or {}).items():
			self.send_header(key, value)
		self.end_headers()
		self.wfile.write(body)

	def do_GET(self):
		if self.path == "/privacy-policy":
			self._send(200, POLICY_BODY.encode("utf-8"))
		elif self.path == "/":
			self._send(200, HOMEPAGE_BODY.encode("utf-8"))
		elif self.path == "/redirect":
			self.send_response(302)
			self.send_header("Location", "/privacy-policy")
			self.end_headers()
		elif self.path == "/gzipped":
			self._send(200, gzip.compress(POLICY_BODY.encode("utf-8")),
					   extra={"Content-Encoding": "gzip"})
		elif self.path == "/latin1":
			self._send(200, "<p>Charge of 50 \xa3 applies to accounts.</p>".encode("latin-1"),
					   content_type="text/html; charset=iso-8859-1")
		elif self.path == "/brochure.pdf":
			self._send(200, b"%PDF-1.4 binary", content_type="application/pdf")
		elif self.path == "/empty":
			self._send(200, b"   ")
		else:
			self._send(404, b"not found", content_type="text/plain")


@pytest.fixture(scope="module")
def server():
	httpd = HTTPServer(("127.0.0.1", 0), _Handler)
	thread = threading.Thread(target=httpd.serve_forever, daemon=True)
	thread.start()
	host, port = httpd.server_address
	yield f"http://{host}:{port}"
	httpd.shutdown()
	httpd.server_close()


@pytest.fixture
def driver():
	return UrlDriver(timeout=10)


class TestFetching:
	def test_registered_under_the_name_url(self):
		assert isinstance(get_driver("url"), UrlDriver)

	def test_fetches_a_policy_page(self, driver, server):
		result = driver.fetch(f"{server}/privacy-policy")
		assert "personal data" in result.raw_text
		assert result.driver == "url"
		assert result.content_type == "text/html"
		assert result.metadata["status"] == 200

	def test_follows_redirects(self, driver, server):
		result = driver.fetch(f"{server}/redirect")
		assert result.origin.endswith("/privacy-policy")
		assert result.metadata["final_url"].endswith("/privacy-policy")

	def test_records_the_requested_url_alongside_the_final_one(self, driver, server):
		result = driver.fetch(f"{server}/redirect")
		assert result.metadata["requested_url"].endswith("/redirect")

	def test_decompresses_a_gzipped_response(self, driver, server):
		assert "personal data" in driver.fetch(f"{server}/gzipped").raw_text

	def test_decodes_a_non_utf8_page(self, driver, server):
		assert "\xa3" in driver.fetch(f"{server}/latin1").raw_text


class TestPolicyLinkFollowing:
	def test_follows_a_policy_link_from_a_homepage(self, driver, server):
		"""Users paste homepages, not policy URLs."""
		result = driver.fetch(server)
		assert result.metadata["final_url"].endswith("/privacy-policy")
		assert result.metadata["followed_policy_link_from"] is not None

	def test_does_not_wander_off_a_page_that_is_already_a_policy(self, driver, server):
		result = driver.fetch(f"{server}/privacy-policy")
		assert result.metadata["followed_policy_link_from"] is None

	def test_can_be_switched_off(self, server):
		result = UrlDriver(timeout=10, follow_policy_link=False).fetch(server)
		assert result.metadata["followed_policy_link_from"] is None


class TestRefusals:
	@pytest.mark.parametrize("target,message", [
		("ftp://example.com/policy", "http and https"),
		("", "needs a URL"),
		("   ", "needs a URL"),
	])
	def test_refuses_what_it_cannot_fetch(self, driver, target, message):
		with pytest.raises(DriverError, match=message):
			driver.fetch(target)

	def test_reports_an_http_error(self, driver, server):
		with pytest.raises(DriverError, match="404"):
			driver.fetch(f"{server}/missing")

	def test_refuses_a_pdf_rather_than_guessing(self, driver, server):
		"""A PDF's bytes decoded as text produce confident nonsense."""
		with pytest.raises(DriverError, match="application/pdf"):
			driver.fetch(f"{server}/brochure.pdf")

	def test_reports_an_empty_document_rather_than_returning_one(self, driver, server):
		with pytest.raises(DriverError, match="empty"):
			driver.fetch(f"{server}/empty")

	def test_reports_an_unreachable_host(self, driver):
		with pytest.raises(DriverError, match="could not reach"):
			driver.fetch("https://privup-nonexistent-host.invalid/policy")


class TestUrlNormalization:
	def test_adds_a_scheme_to_a_bare_host(self):
		assert normalize_url("example.com/privacy").startswith("https://")

	def test_keeps_an_explicit_scheme(self):
		assert normalize_url("http://example.com").startswith("http://")

	@pytest.mark.parametrize("bad", ["", "   ", "https://"])
	def test_rejects_unusable_input(self, bad):
		with pytest.raises(DriverError):
			normalize_url(bad)


class TestResolver:
	def test_resolves_a_relative_link(self):
		assert resolve("https://x.com/a/b", "/privacy") == "https://x.com/privacy"
		assert resolve("https://x.com/a/b", "../privacy") == "https://x.com/privacy"

	def test_finds_and_ranks_policy_links(self):
		html = (
			'<a href="/about">About</a>'
			'<a href="/legal">Legal</a>'
			'<a href="/privacy-policy">Privacy Policy</a>'
		)
		links = find_policy_links(html, "https://x.com")
		assert links[0].url == "https://x.com/privacy-policy"

	def test_ignores_off_site_links(self):
		html = '<a href="https://other.com/privacy-policy">Privacy</a>'
		assert find_policy_links(html, "https://x.com") == []

	@pytest.mark.parametrize("href", [
		"mailto:a@b.com", "tel:+911234", "javascript:void(0)",
		"/blog/privacy-tips", "/privacy.pdf",
	])
	def test_skips_links_that_are_not_documents(self, href):
		html = f'<a href="{href}">Privacy Policy</a>'
		assert find_policy_links(html, "https://x.com") == []

	def test_handles_unquoted_hrefs(self):
		links = find_policy_links("<a href=/privacy-policy>Privacy</a>", "https://x.com")
		assert links and links[0].url.endswith("/privacy-policy")


class TestExtractor:
	def test_prefers_the_declared_charset(self):
		assert decode("caf\xe9".encode("latin-1"), "iso-8859-1") == "caf\xe9"

	def test_reads_a_meta_charset(self):
		body = '<meta charset="iso-8859-1"><p>caf\xe9</p>'.encode("latin-1")
		assert "caf\xe9" in decode(body, None)

	def test_never_raises_on_bad_bytes(self):
		assert isinstance(decode(b"\xff\xfe\x00bad", "utf-8"), str)

	def test_a_footer_link_does_not_make_a_page_a_policy(self):
		"""Kissht's homepage is 15,000 words of marketing with a footer
		reading 'Privacy Policy'. It tested positive and the driver never
		followed the link it was meant to follow."""
		homepage = "Get a loan fast. " * 300 + " Privacy Policy Terms of Use"
		assert looks_like_policy(homepage) is False

	def test_real_policy_prose_is_recognised(self):
		text = (
			"We collect your personal data. We may collect personal information. "
			"We share it with third parties. We use your data. Your consent matters. "
			"Retention of personal data. Cookies are used. " * 10
		)
		assert looks_like_policy(text) is True

	def test_loan_terms_are_recognised_as_a_document_worth_reading(self):
		"""Tightening the test far enough to reject a homepage made a terms
		page test negative, and the driver would have wandered off the loan
		agreement the user deliberately pasted."""
		terms = (
			"The borrower shall repay the loan. Rate of interest applies. "
			"A processing fee is charged. Governing law is Indian law. "
			"Liability is limited. Repayment schedule follows. " * 12
		)
		assert looks_like_policy(terms) is True

	def test_a_short_page_is_not_a_policy(self):
		assert looks_like_policy("We collect personal data.") is False
