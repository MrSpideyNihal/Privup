"""Python and JavaScript must agree, field for field.

This is the test that makes a second implementation defensible. Two
implementations of the same logic drift; that is the normal outcome, and here
it would mean two verdicts for the same policy differing by platform with no
way to tell which is right.

So the same fixtures run through both and the resulting Verdicts are compared
exactly. When they disagree, the Python is right and the JavaScript is wrong.

Skipped when Node is unavailable rather than failing, so a contributor with no
Node installed can still work on the Python. CI has Node.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from core.main import run
from tests.fixtures import load_html, load_text, text_fixtures

REPO_ROOT = Path(__file__).resolve().parents[1]
JS_RUNNER = REPO_ROOT / "tools" / "js_verdict.mjs"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="Node is not installed")

# Set by the pipeline at analysis time, so it can never match across two
# processes. Everything else must.
VOLATILE = {"analyzed_at"}

RULE_SETS = ["generic", "loan_app"]


def js_verdict(text: str, tag_set: str, as_html: bool = False) -> dict:
	command = [NODE, str(JS_RUNNER), tag_set]
	if as_html:
		command.append("--html")

	completed = subprocess.run(
		command,
		input=text.encode("utf-8"),
		capture_output=True,
		cwd=REPO_ROOT,
		timeout=120,
	)
	if completed.returncode != 0:
		raise AssertionError(
			f"js core failed for {tag_set}: {completed.stderr.decode('utf-8', 'replace')}"
		)
	return json.loads(completed.stdout.decode("utf-8"))


def strip_volatile(verdict: dict) -> dict:
	return {k: v for k, v in verdict.items() if k not in VOLATILE}


def describe(label: str, python_value, js_value) -> str:
	return (
		f"{label} differs between implementations.\n"
		f"  python: {python_value!r}\n"
		f"  js    : {js_value!r}\n"
		"The Python is the source of truth; fix extension/src/core/."
	)


class TestRuleSetsAreSingleSource:
	def test_the_generated_mirror_is_in_sync(self):
		"""A rule changed without being mirrored would ship an extension that
		quietly disagrees with the CLI."""
		completed = subprocess.run(
			["python", str(REPO_ROOT / "tools" / "sync_rulesets.py"), "--check"],
			capture_output=True, text=True, cwd=REPO_ROOT, timeout=60,
		)
		assert completed.returncode == 0, completed.stderr

	def test_the_generated_file_says_not_to_edit_it(self):
		generated = (REPO_ROOT / "extension" / "src" / "core" / "rulesets.generated.js")
		head = generated.read_text(encoding="utf-8")[:600]
		assert "DO NOT EDIT" in head
		assert "sync_rulesets" in head

	def test_no_rule_is_defined_anywhere_but_the_json(self):
		"""The extension must not carry a hand-written copy of a rule.

		Checks for rule ids rather than for the word "patterns", which the
		loader legitimately uses as a field name.
		"""
		core_dir = REPO_ROOT / "extension" / "src" / "core"
		for path in core_dir.glob("*.js"):
			if path.name == "rulesets.generated.js":
				continue
			text = path.read_text(encoding="utf-8")
			for marker in ("rbi.permission", "rbi.charges", "gdpr.sharing", "gdpr.tracking"):
				assert marker not in text, f"{path.name} hardcodes rule {marker}"

	def test_both_implementations_see_the_same_rule_sets(self):
		from core.tags import available_tag_sets

		completed = subprocess.run(
			[NODE, "-e",
			 "import('./extension/src/core/main.js').then(m => "
			 "console.log(JSON.stringify(m.availableTagSets())))"],
			capture_output=True, text=True, cwd=REPO_ROOT, timeout=60,
		)
		assert json.loads(completed.stdout) == available_tag_sets()

	def test_both_implementations_count_the_same_rules(self):
		from core.tags import describe_tag_sets

		completed = subprocess.run(
			[NODE, "-e",
			 "import('./extension/src/core/main.js').then(m => "
			 "console.log(JSON.stringify(m.describeTagSets())))"],
			capture_output=True, text=True, cwd=REPO_ROOT, timeout=60,
		)
		js = {entry["name"]: entry["rules"] for entry in json.loads(completed.stdout)}
		py = {name: count for name, _, count in describe_tag_sets()}
		assert js == py


@pytest.mark.parametrize("fixture", text_fixtures())
@pytest.mark.parametrize("tag_set", RULE_SETS)
class TestVerdictParity:
	"""Every fixture, both rule sets."""

	def test_the_decision_matches(self, fixture, tag_set):
		text = load_text(fixture)
		python = run("raw_text", text, tag_set).to_dict()
		js = js_verdict(text, tag_set)
		assert python["decision"] == js["decision"], describe(
			f"{fixture}/{tag_set} decision", python["decision"], js["decision"]
		)

	def test_the_same_rules_fire_on_the_same_clauses(self, fixture, tag_set):
		text = load_text(fixture)
		python = run("raw_text", text, tag_set).to_dict()
		js = js_verdict(text, tag_set)

		def signature(verdict):
			return sorted(
				(f["rule_id"], f["clause"]["index"], f["severity"])
				for f in verdict["findings"]
			)

		py_sig, js_sig = signature(python), signature(js)
		only_python = [s for s in py_sig if s not in js_sig]
		only_js = [s for s in js_sig if s not in py_sig]
		assert not only_python and not only_js, (
			f"{fixture}/{tag_set} findings diverge.\n"
			f"  python only: {only_python}\n"
			f"  js only    : {only_js}\n"
			"The Python is the source of truth; fix extension/src/core/."
		)

	def test_the_reasons_match_exactly(self, fixture, tag_set):
		"""These are the sentences a user reads. A wording difference between
		platforms is a real defect even when the decision agrees."""
		text = load_text(fixture)
		python = run("raw_text", text, tag_set).to_dict()
		js = js_verdict(text, tag_set)
		assert python["reasons"] == js["reasons"], describe(
			f"{fixture}/{tag_set} reasons", python["reasons"], js["reasons"]
		)

	def test_the_risk_score_matches(self, fixture, tag_set):
		text = load_text(fixture)
		python = run("raw_text", text, tag_set).to_dict()
		js = js_verdict(text, tag_set)
		assert python["risk_score"] == pytest.approx(js["risk_score"], abs=0.05), describe(
			f"{fixture}/{tag_set} risk_score", python["risk_score"], js["risk_score"]
		)

	def test_segmentation_produces_the_same_clause_count(self, fixture, tag_set):
		"""Cleaning and segmentation are ported code too, and a divergence
		there moves every clause index underneath the findings."""
		text = load_text(fixture)
		python = run("raw_text", text, tag_set).to_dict()
		js = js_verdict(text, tag_set)
		assert python["clauses_analyzed"] == js["clauses_analyzed"], describe(
			f"{fixture}/{tag_set} clauses_analyzed",
			python["clauses_analyzed"], js["clauses_analyzed"],
		)

	def test_the_whole_verdict_matches(self, fixture, tag_set):
		text = load_text(fixture)
		python = strip_volatile(run("raw_text", text, tag_set).to_dict())
		js = strip_volatile(js_verdict(text, tag_set))
		assert python == js, f"{fixture}/{tag_set}: verdicts differ"


class TestHtmlPathParity:
	"""The HTML cleaner is the most intricate ported component."""

	def test_a_real_page_with_chrome_matches(self):
		html = load_html("page_with_chrome.html")
		python = strip_volatile(run("raw_text", html, "generic").to_dict())
		js = strip_volatile(js_verdict(html, "generic", as_html=True))
		assert python["clauses_analyzed"] == js["clauses_analyzed"], describe(
			"page_with_chrome clauses", python["clauses_analyzed"], js["clauses_analyzed"]
		)
		assert python == js

	@pytest.mark.parametrize("html,note", [
		('<body class="index has-navbar-fixed-top"><p>%s</p></body>', "body is never chrome"),
		('<div class="mzp-l-content mzp-has-sidebar"><p>%s</p></div>', "content wrapper kept"),
		("<nav><a>Home</a></nav><p>%s</p>", "nav dropped"),
		("<table><tr><td>Processing fees</td><td>Up to 7%%</td></tr></table><p>%s</p>", "cells joined"),
		("<div class=nav><span>menu</div><p>%s</p>", "unbalanced markup"),
	])
	def test_cleaner_edge_cases_match(self, html, note):
		filler = "We collect your personal data and share it with partners. " * 12
		document = html % filler
		python = run("raw_text", document, "generic").to_dict()
		js = js_verdict(document, "generic", as_html=True)
		assert python["clauses_analyzed"] == js["clauses_analyzed"], describe(
			f"{note}: clauses", python["clauses_analyzed"], js["clauses_analyzed"]
		)


class TestBehaviourParityOnKnownCases:
	"""The cases that shaped the rules must behave the same on both."""

	@pytest.mark.parametrize("text,tag_set", [
		# Kissht's denial must not produce a finding on either platform.
		("We also do not access your mobile phone resources such as contact list, "
		 "call logs, telephony Functions, etc.", "loan_app"),
		# The curly-apostrophe negation bug.
		("We don’t share information that personally identifies you with advertisers.", "generic"),
		# "profile picture" is not profiling.
		('You can add other information to your account, such as a profile picture.', "generic"),
		# LazyPay's hedge must downgrade, not suppress, identically.
		("In accordance with applicable laws, we ideally restrain from accessing mobile "
		 "phone resources like file and media, contact list, call logs.", "loan_app"),
		# The daily penal rate must annualise the same way.
		("Penal Charges: Daily charges of up to 0.2% of the overdue principal amount.", "loan_app"),
		# Abbreviations must not split sentences differently.
		("Charges apply (e.g. a processing fee of Rs. 500). We may share data with Acme Inc. "
		 "and its partners.", "generic"),
	])
	def test_matches(self, text, tag_set):
		python = strip_volatile(run("raw_text", text, tag_set).to_dict())
		js = strip_volatile(js_verdict(text, tag_set))
		assert python == js

	def test_an_empty_document_warns_on_both(self):
		"""Never Allow for a page nobody could read."""
		text = "   "
		js = js_verdict(text, "generic")
		assert js["decision"] == "warning"
		assert js["metadata"]["empty_document"] is True

	def test_the_relevance_notice_matches(self):
		text = load_text("generic_signal.txt")
		python = run("raw_text", text, "loan_app").to_dict()
		js = js_verdict(text, "loan_app")
		assert python["metadata"]["relevance"] == js["metadata"]["relevance"]


class TestJavaScriptOwnTests:
	"""The DOM-only logic, which Python cannot reach.

	Banner detection reads computed styles and element structure, so it has no
	Python counterpart and the parity harness cannot cover it. Its own tests
	run here so a single `pytest` covers both languages.
	"""

	def test_the_js_suite_passes(self):
		suite = REPO_ROOT / "extension" / "tests" / "banner.test.mjs"
		completed = subprocess.run(
			[NODE, "--test", str(suite)],
			capture_output=True, text=True, cwd=REPO_ROOT, timeout=120,
		)
		assert completed.returncode == 0, completed.stdout + completed.stderr
		assert "# fail 0" in completed.stdout

	def test_the_extension_core_imports_cleanly(self):
		"""A syntax error in a module the parity harness does not touch would
		otherwise only show up when a user loads the extension."""
		for module in ["dom.js", "panel.js", "content.js", "loader.js", "worker.js"]:
			completed = subprocess.run(
				[NODE, "--check", str(REPO_ROOT / "extension" / "src" / module)],
				capture_output=True, text=True, cwd=REPO_ROOT, timeout=60,
			)
			assert completed.returncode == 0, f"{module}: {completed.stderr}"


class TestManifest:
	def test_is_manifest_v3(self):
		manifest = json.loads(
			(REPO_ROOT / "extension" / "manifest.json").read_text(encoding="utf-8")
		)
		assert manifest["manifest_version"] == 3

	def test_requests_no_host_permissions(self):
		"""The extension reads the page it is already on. Broad host access
		would let it fetch anything, which is not what it does and not what a
		reviewer should have to take on trust."""
		manifest = json.loads(
			(REPO_ROOT / "extension" / "manifest.json").read_text(encoding="utf-8")
		)
		assert manifest["host_permissions"] == []
		assert set(manifest["permissions"]) <= {"activeTab", "scripting", "storage"}

	def test_every_referenced_file_exists(self):
		root = REPO_ROOT / "extension"
		manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
		referenced = [manifest["background"]["service_worker"]]
		for entry in manifest["content_scripts"]:
			referenced.extend(entry["js"])
		for path in referenced:
			assert (root / path).is_file(), path
