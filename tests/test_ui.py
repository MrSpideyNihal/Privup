"""The local web UI.

A smoke test, deliberately. The spec for this phase says not to over-invest in
UI test infrastructure, so there is no browser here: the server is exercised
over real HTTP, and the parts worth pinning are the contract with the browser
and the promises about staying local.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

import pytest

from core.main import run
from tests.fixtures import load_text
from ui.server import STATIC_DIR, analyze, build_server, guess_driver

LENDER_TEXT = (
	"We access your contact list and call logs to assess creditworthiness. "
	"Daily charges of up to 0.2% of the overdue principal amount apply to your loan. "
	"Rate of Interest Up to 36% p.a. for every borrower."
)


@pytest.fixture(scope="module")
def base_url():
	httpd = build_server("127.0.0.1", 0)
	threading.Thread(target=httpd.serve_forever, daemon=True).start()
	host, port = httpd.server_address[:2]
	yield f"http://{host}:{port}"
	httpd.shutdown()
	httpd.server_close()


def get(url, headers=None):
	request = urllib.request.Request(url, headers=headers or {})
	with urllib.request.urlopen(request, timeout=30) as response:
		return response.status, response.read(), response.headers


def post_json(url, payload, expect_error=False):
	request = urllib.request.Request(
		url,
		data=json.dumps(payload).encode("utf-8"),
		headers={"Content-Type": "application/json"},
		method="POST",
	)
	try:
		with urllib.request.urlopen(request, timeout=60) as response:
			return response.status, json.loads(response.read())
	except urllib.error.HTTPError as exc:
		if not expect_error:
			raise
		return exc.code, json.loads(exc.read())


class TestDriverGuessing:
	@pytest.mark.parametrize("target", [
		"https://example.com/privacy",
		"http://example.com",
		"example.com/privacy-policy",
		"www.kissht.com/privacy-policy",
	])
	def test_a_link_is_a_link(self, target):
		assert guess_driver(target) == "url"

	@pytest.mark.parametrize("target", [
		"We collect your personal data.",
		"Privacy Policy\nWe access your contacts.",
		"  ",
		"not a url at all",
		"See our policy at example.com for details.",
	])
	def test_everything_else_is_text(self, target):
		assert guess_driver(target) == "raw_text"


class TestStaticFiles:
	def test_serves_the_page(self, base_url):
		status, body, headers = get(base_url + "/")
		assert status == 200
		assert b"<title>PrivUp</title>" in body
		assert headers["Content-Type"].startswith("text/html")

	@pytest.mark.parametrize("path", ["/app.css", "/app.js"])
	def test_serves_its_assets(self, base_url, path):
		status, body, _ = get(base_url + path)
		assert status == 200 and body

	def test_ships_no_external_requests(self):
		"""The UI must stay local. A webfont or a CDN script would be the one
		thing on the page that talked to the internet."""
		for name in ["index.html", "app.css", "app.js"]:
			text = (STATIC_DIR / name).read_text(encoding="utf-8")
			for marker in ["http://", "https://", "//fonts.", "cdn."]:
				assert marker not in text, f"{name} references {marker}"

	def test_refuses_to_escape_the_static_directory(self, base_url):
		with pytest.raises(urllib.error.HTTPError) as caught:
			get(base_url + "/../core/main.py")
		assert caught.value.code == 404


class TestTagsEndpoint:
	def test_lists_the_same_rule_sets_the_cli_lists(self, base_url):
		_, body, _ = get(base_url + "/api/tags")
		names = [entry["name"] for entry in json.loads(body)["tag_sets"]]
		assert names == ["generic", "loan_app"]

	def test_each_entry_can_populate_a_dropdown(self, base_url):
		_, body, _ = get(base_url + "/api/tags")
		for entry in json.loads(body)["tag_sets"]:
			assert entry["description"] and entry["rules"] > 0


class TestAnalyzeEndpoint:
	def test_returns_a_verdict(self, base_url):
		status, payload = post_json(
			base_url + "/api/analyze", {"target": LENDER_TEXT, "tags": "loan_app"}
		)
		assert status == 200
		assert payload["decision"] == "deny"
		assert payload["decision_label"] == "Deny"
		assert payload["driver"] == "raw_text"

	def test_every_finding_carries_what_the_row_needs_to_expand(self, base_url):
		"""Collapsed shows the reason; expanded shows the clause behind it."""
		_, payload = post_json(
			base_url + "/api/analyze", {"target": LENDER_TEXT, "tags": "loan_app"}
		)
		for finding in payload["findings"]:
			assert finding["reason"]
			assert finding["severity"]
			assert "text" in finding["clause"]

	@pytest.mark.parametrize("tag_set", ["generic", "loan_app"])
	def test_works_for_both_rule_sets(self, base_url, tag_set):
		_, payload = post_json(
			base_url + "/api/analyze",
			{"target": load_text("loan_hedged_lazypay.txt"), "tags": tag_set},
		)
		assert payload["rule_set"] == tag_set

	def test_reports_the_mismatch_notice_without_withholding_findings(self, base_url):
		_, payload = post_json(
			base_url + "/api/analyze",
			{"target": load_text("generic_signal.txt"), "tags": "loan_app"},
		)
		assert payload["metadata"]["relevance"]["applies"] is False
		assert payload["metadata"]["relevance"]["notice"]
		assert payload["findings"], "a notice must never suppress the findings"

	@pytest.mark.parametrize("payload,status", [
		({"target": "", "tags": "generic"}, 400),
		({"target": "   ", "tags": "generic"}, 400),
		({"target": "text", "tags": "no_such_rules"}, 400),
	])
	def test_bad_requests_explain_themselves(self, base_url, payload, status):
		code, body = post_json(base_url + "/api/analyze", payload, expect_error=True)
		assert code == status
		assert body["error"]

	def test_an_unreachable_url_is_reported_not_swallowed(self, base_url):
		code, body = post_json(
			base_url + "/api/analyze",
			{"target": "https://privup-nonexistent.invalid/p", "tags": "generic"},
			expect_error=True,
		)
		assert code == 502
		assert "could not reach" in body["error"]

	def test_unknown_endpoints_404(self, base_url):
		with pytest.raises(urllib.error.HTTPError) as caught:
			post_json(base_url + "/api/nope", {})
		assert caught.value.code == 404


class TestStaysLocal:
	def test_refuses_a_non_loopback_host_header(self, base_url):
		"""Blocks DNS rebinding: a page on the open internet must not be able
		to drive this server and read back policy text."""
		with pytest.raises(urllib.error.HTTPError) as caught:
			get(base_url + "/api/tags", headers={"Host": "evil.example.com"})
		assert caught.value.code == 403

	def test_sends_no_cors_header(self, base_url):
		_, _, headers = get(base_url + "/")
		assert "Access-Control-Allow-Origin" not in headers

	def test_sets_conservative_response_headers(self, base_url):
		_, _, headers = get(base_url + "/")
		assert headers["X-Frame-Options"] == "DENY"
		assert headers["Referrer-Policy"] == "no-referrer"
		assert headers["Cache-Control"] == "no-store"

	def test_will_not_bind_a_public_interface(self):
		from ui.server import main

		assert main(["--host", "0.0.0.0"]) == 2


class TestNoDuplicatedPipelineLogic:
	def test_the_ui_reports_exactly_what_core_decided(self):
		"""If these diverge, the UI has grown logic it should not have."""
		for tag_set in ["generic", "loan_app"]:
			from_ui = analyze(LENDER_TEXT, tag_set)
			from_core = run("raw_text", LENDER_TEXT, tag_set).to_dict()

			assert from_ui["decision"] == from_core["decision"]
			assert from_ui["reasons"] == from_core["reasons"]
			assert from_ui["risk_score"] == from_core["risk_score"]
			assert len(from_ui["findings"]) == len(from_core["findings"])
