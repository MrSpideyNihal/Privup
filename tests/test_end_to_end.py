"""The whole pipeline, both drivers, both rule sets.

Four combinations minimum, plus the properties that have to hold whichever
path a document takes through the system.

The url_driver runs against a local HTTP server serving real fixture text, so
these exercise a genuine HTTP fetch without depending on a lender's website
staying up and unchanged.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from core.main import run
from core.models import Decision, Severity, Verdict
from core.scraper import UnknownDriverError
from core.tags import UnknownTagSetError
from tests.fixtures import load_text

# Which fixture each rule set is meant to be run against, and what the
# pipeline should conclude.
CASES = {
	"loan_app": ("loan_permissive_truebalance.txt", Decision.DENY),
	"generic": ("generic_mozilla.txt", Decision.WARNING),
}

SERVED = {
	f"/{name}": load_text(name)
	for name in ["loan_permissive_truebalance.txt", "generic_mozilla.txt",
				 "loan_charges_kissht_tou.txt", "generic_signal.txt"]
}


class _Handler(BaseHTTPRequestHandler):
	def log_message(self, *args):
		pass

	def do_GET(self):
		body = SERVED.get(self.path)
		if body is None:
			self.send_response(404)
			self.send_header("Content-Length", "0")
			self.end_headers()
			return
		payload = f"<html><body><pre>{body}</pre></body></html>".encode("utf-8")
		self.send_response(200)
		self.send_header("Content-Type", "text/html; charset=utf-8")
		self.send_header("Content-Length", str(len(payload)))
		self.end_headers()
		self.wfile.write(payload)


@pytest.fixture(scope="module")
def server():
	httpd = HTTPServer(("127.0.0.1", 0), _Handler)
	threading.Thread(target=httpd.serve_forever, daemon=True).start()
	host, port = httpd.server_address
	yield f"http://{host}:{port}"
	httpd.shutdown()
	httpd.server_close()


class TestFourCombinations:
	@pytest.mark.parametrize("tag_set", ["loan_app", "generic"])
	def test_raw_text_driver(self, tag_set):
		fixture, expected = CASES[tag_set]
		verdict = run("raw_text", load_text(fixture), tag_set)

		assert verdict.decision is expected
		assert verdict.rule_set == tag_set
		assert verdict.clauses_analyzed > 20
		assert verdict.findings
		assert len(verdict.reasons) >= 1

	@pytest.mark.parametrize("tag_set", ["loan_app", "generic"])
	def test_url_driver(self, tag_set, server):
		fixture, expected = CASES[tag_set]
		verdict = run("url", f"{server}/{fixture}", tag_set)

		assert verdict.decision is expected
		assert verdict.rule_set == tag_set
		assert verdict.clauses_analyzed > 20
		assert verdict.origin.startswith("http://127.0.0.1")

	@pytest.mark.parametrize("tag_set", ["loan_app", "generic"])
	def test_both_drivers_agree_on_the_same_document(self, tag_set, server):
		"""A driver decides where text comes from, never what it means."""
		fixture, _ = CASES[tag_set]
		from_text = run("raw_text", load_text(fixture), tag_set)
		from_url = run("url", f"{server}/{fixture}", tag_set)

		assert from_text.decision is from_url.decision
		assert {f.rule_id for f in from_text.findings} == {f.rule_id for f in from_url.findings}


class TestVerdictProperties:
	@pytest.mark.parametrize("tag_set", ["loan_app", "generic"])
	@pytest.mark.parametrize("fixture", [
		"loan_permissive_truebalance.txt", "loan_compliant_kissht.txt",
		"loan_hedged_lazypay.txt", "loan_charges_kissht_tou.txt",
		"generic_mozilla.txt", "generic_signal.txt",
	])
	def test_every_fixture_produces_a_usable_verdict(self, fixture, tag_set):
		verdict = run("raw_text", load_text(fixture), tag_set)

		assert isinstance(verdict, Verdict)
		assert verdict.decision in set(Decision)
		assert 0.0 <= verdict.risk_score <= 100.0
		# Every reason is a line a person can read.
		for reason in verdict.reasons:
			assert reason.strip() and reason[0].isupper() and len(reason) < 260
		# Every finding can be expanded into its evidence.
		for finding in verdict.findings:
			assert finding.clause.text.strip()
			assert finding.rule_set == tag_set

	@pytest.mark.parametrize("tag_set", ["loan_app", "generic"])
	def test_a_verdict_survives_json(self, tag_set):
		"""The CLI, the local UI, the extension and Android all cross this
		boundary."""
		fixture, _ = CASES[tag_set]
		verdict = run("raw_text", load_text(fixture), tag_set)
		assert Verdict.from_dict(json.loads(json.dumps(verdict.to_dict()))) == verdict

	def test_deny_is_reserved_for_critical_findings(self):
		for tag_set in ["loan_app", "generic"]:
			for fixture in ["loan_permissive_truebalance.txt", "generic_signal.txt"]:
				verdict = run("raw_text", load_text(fixture), tag_set)
				if verdict.decision is Decision.DENY:
					assert verdict.highest_severity is Severity.CRITICAL


class TestRealWorldCases:
	def test_hidden_daily_interest_is_surfaced_as_a_yearly_figure(self):
		"""A lender's real schedule of charges quotes 0.2% a day, alongside
		36% p.a. for the loan itself. The daily figure is the larger one."""
		verdict = run("raw_text", load_text("loan_charges_kissht_tou.txt"), "loan_app")

		assert verdict.decision is Decision.DENY
		penal = next(f for f in verdict.findings if f.rule_id == "rbi.charges.penal_daily")
		assert "73" in penal.reason
		assert "year" in penal.reason

	def test_a_compliant_lender_is_not_flagged_for_the_permissions_it_disclaims(self):
		"""The false positive that would make this tool untrustworthy."""
		verdict = run("raw_text", load_text("loan_compliant_kissht.txt"), "loan_app")
		fired = {f.rule_id for f in verdict.findings}
		assert "rbi.permission.contacts" not in fired
		assert "rbi.permission.call_logs" not in fired

	def test_a_minimal_service_is_not_denied(self):
		verdict = run("raw_text", load_text("generic_signal.txt"), "generic")
		assert verdict.decision is not Decision.DENY

	def test_a_javascript_only_page_warns_rather_than_allowing(self):
		"""Several live lending sites return an empty shell to a plain GET."""
		verdict = run("raw_text", "<html><body><div id='root'></div></body></html>", "loan_app")
		assert verdict.decision is Decision.WARNING
		assert verdict.metadata["empty_document"] is True
		assert "not an all-clear" in verdict.reasons[0]


class TestErrorsSurface:
	def test_an_unknown_driver_raises(self):
		with pytest.raises(UnknownDriverError):
			run("carrier_pigeon", "text", "generic")

	def test_an_unknown_rule_set_raises(self):
		with pytest.raises(UnknownTagSetError):
			run("raw_text", "some text", "nonexistent_rules")

	def test_a_failed_fetch_raises_rather_than_reporting_allow(self):
		"""A caller who asked for a check and silently got an Allow because
		the fetch failed has been actively misled."""
		from core.scraper import DriverError

		with pytest.raises(DriverError):
			run("raw_text", "", "generic")
