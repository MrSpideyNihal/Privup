"""The command line interface.

Exit status is part of the contract here, not an afterthought: the point of a
scriptable interface is that a script can branch on it.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from cli.format import render_text
from cli.main import EXIT_DENY, EXIT_ERROR, EXIT_OK, EXIT_USAGE, main
from core.main import run
from tests.fixtures import load_text

REPO_ROOT = Path(__file__).resolve().parents[1]

CLEAN_TEXT = (
	"We do not collect your personal data. We never share information with third parties. "
	"You can withdraw your consent at any time and request deletion of your account."
)
LENDER_TEXT = (
	"We access your contact list and call logs to assess creditworthiness. "
	"Daily charges of up to 0.2% of the overdue principal amount apply to your loan. "
	"Rate of Interest Up to 36% p.a. for every borrower."
)


def invoke(args, capsys):
	"""Call main() in-process and return (status, stdout, stderr)."""
	status = main(args)
	captured = capsys.readouterr()
	return status, captured.out, captured.err


def flat(text: str) -> str:
	"""Collapse wrapping so a phrase assertion is not a line-width assertion."""
	return " ".join(text.split())


class TestExitStatus:
	def test_deny_exits_non_zero(self, capsys):
		status, _, _ = invoke(["scan", LENDER_TEXT, "--tags", "loan_app"], capsys)
		assert status == EXIT_DENY

	def test_warning_exits_zero(self, capsys):
		status, _, _ = invoke(
			["scan", load_text("generic_mozilla.txt"), "--tags", "generic"], capsys
		)
		assert status == EXIT_OK

	def test_allow_exits_zero(self, capsys):
		status, out, _ = invoke(["scan", CLEAN_TEXT, "--tags", "generic"], capsys)
		assert status == EXIT_OK
		assert "ALLOW" in out

	def test_an_unreadable_target_is_an_error_not_a_deny(self, capsys):
		"""A build that fails because a policy is bad and one that fails
		because a URL 404'd need different responses."""
		status, _, err = invoke(["scan", "", "--tags", "generic"], capsys)
		assert status == EXIT_ERROR
		assert "privup:" in err

	def test_an_unknown_rule_set_is_a_usage_error(self, capsys):
		with pytest.raises(SystemExit) as exit_info:
			main(["scan", "text", "--tags", "does_not_exist"])
		assert exit_info.value.code == EXIT_USAGE

	def test_no_subcommand_prints_help(self, capsys):
		status, out, _ = invoke([], capsys)
		assert status == EXIT_USAGE
		assert "usage: privup" in out


class TestListing:
	def test_list_tags_names_both_shipped_rule_sets(self, capsys):
		status, out, _ = invoke(["--list-tags"], capsys)
		assert status == EXIT_OK
		assert "generic" in out
		assert "loan_app" in out

	def test_list_tags_reports_rule_counts(self, capsys):
		"""This doubles as a check that a contributor's rule set was found."""
		_, out, _ = invoke(["--list-tags"], capsys)
		assert "rules)" in out

	def test_list_drivers_names_both_drivers(self, capsys):
		status, out, _ = invoke(["--list-drivers"], capsys)
		assert status == EXIT_OK
		assert "raw_text" in out
		assert "url" in out


class TestTextFormat:
	def test_leads_with_the_decision(self, capsys):
		_, out, _ = invoke(["scan", LENDER_TEXT, "--tags", "loan_app"], capsys)
		assert out.startswith("DENY")

	def test_prints_one_reason_per_line(self, capsys):
		_, out, _ = invoke(["scan", LENDER_TEXT, "--tags", "loan_app"], capsys)
		bullets = [line for line in out.splitlines() if line.startswith("- ")]
		assert len(bullets) >= 3

	def test_is_plain_ascii_by_default(self, capsys):
		"""This output gets piped, pasted into issues and read over SSH."""
		_, out, _ = invoke(["scan", LENDER_TEXT, "--tags", "loan_app"], capsys)
		assert "\033[" not in out

	def test_color_is_opt_in(self, capsys):
		_, out, _ = invoke(["scan", LENDER_TEXT, "--tags", "loan_app", "--color"], capsys)
		assert "\033[" in out

	def test_verbose_shows_the_clause_behind_a_finding(self, capsys):
		_, plain, _ = invoke(["scan", LENDER_TEXT, "--tags", "loan_app"], capsys)
		_, loud, _ = invoke(["scan", LENDER_TEXT, "--tags", "loan_app", "--verbose"], capsys)
		assert len(loud) > len(plain)
		assert "0.2%" in loud

	def test_quiet_prints_nothing_but_still_signals(self, capsys):
		status, out, err = invoke(["scan", LENDER_TEXT, "--tags", "loan_app", "--quiet"], capsys)
		assert out == "" and err == ""
		assert status == EXIT_DENY

	def test_an_allow_says_so_plainly(self, capsys):
		_, out, _ = invoke(["scan", CLEAN_TEXT, "--tags", "generic"], capsys)
		assert "No red flags matched." in flat(out)


class TestJsonFormat:
	def test_emits_the_whole_verdict(self, capsys):
		_, out, _ = invoke(
			["scan", LENDER_TEXT, "--tags", "loan_app", "--format", "json"], capsys
		)
		payload = json.loads(out)
		assert payload["decision"] == "deny"
		assert payload["rule_set"] == "loan_app"
		assert payload["findings"]
		assert payload["findings"][0]["clause"]["text"]

	def test_is_valid_json_for_every_rule_set(self, capsys):
		for tag_set in ["generic", "loan_app"]:
			_, out, _ = invoke(
				["scan", load_text("loan_hedged_lazypay.txt"), "--tags", tag_set,
				 "--format", "json"], capsys
			)
			assert json.loads(out)["rule_set"] == tag_set

	def test_carries_the_citation_a_reader_can_check(self, capsys):
		_, out, _ = invoke(
			["scan", LENDER_TEXT, "--tags", "loan_app", "--format", "json"], capsys
		)
		references = [f["reference"] for f in json.loads(out)["findings"]]
		assert any(r and "RBI" in r for r in references)


class TestRuleSetMismatchNotice:
	"""Warn, never block. Running a rule set against something it was not
	written for is allowed; being confidently wrong about it is not."""

	def test_notice_appears_for_an_obvious_mismatch(self, capsys):
		_, out, _ = invoke(
			["scan", load_text("generic_signal.txt"), "--tags", "loan_app"], capsys
		)
		assert "Note:" in out
		assert "may not apply well here" in flat(out)

	def test_the_findings_are_still_shown(self, capsys):
		status, out, _ = invoke(
			["scan", load_text("generic_signal.txt"), "--tags", "loan_app"], capsys
		)
		assert [line for line in out.splitlines() if line.startswith("- ")]
		assert status == EXIT_DENY  # not softened, not blocked

	def test_no_notice_for_a_real_lender(self, capsys):
		_, out, _ = invoke(
			["scan", load_text("loan_charges_kissht_tou.txt"), "--tags", "loan_app"], capsys
		)
		assert "Note:" not in out

	def test_no_notice_from_the_generic_rule_set(self, capsys):
		"""generic is meant to apply to anything, so it declares no signals."""
		_, out, _ = invoke(
			["scan", load_text("generic_signal.txt"), "--tags", "generic"], capsys
		)
		assert "Note:" not in out


class TestNoDuplicatedPipelineLogic:
	def test_the_cli_reports_exactly_what_core_decided(self, capsys):
		"""If these ever diverge, the CLI has grown logic it should not have."""
		for tag_set, text in [("loan_app", LENDER_TEXT), ("generic", CLEAN_TEXT)]:
			_, out, _ = invoke(["scan", text, "--tags", tag_set, "--format", "json"], capsys)
			from_cli = json.loads(out)
			from_core = run("raw_text", text, tag_set).to_dict()

			assert from_cli["decision"] == from_core["decision"]
			assert from_cli["reasons"] == from_core["reasons"]
			assert from_cli["risk_score"] == from_core["risk_score"]


class TestFormatting:
	def test_wraps_without_breaking_words(self):
		verdict = run("raw_text", LENDER_TEXT, "loan_app")
		for line in render_text(verdict, width=60).splitlines():
			assert len(line) <= 62

	def test_an_absence_finding_says_it_is_an_absence(self):
		verdict = run("raw_text", LENDER_TEXT, "loan_app")
		rendered = render_text(verdict, verbose=True)
		assert "nothing in the document covers this" in flat(rendered)


class TestRunsAsASubprocess:
	"""The real integration surface: another tool shelling out to privup."""

	def test_python_m_cli_works_from_a_checkout(self):
		completed = subprocess.run(
			[sys.executable, "-m", "cli", "scan", LENDER_TEXT, "--tags", "loan_app",
			 "--format", "json"],
			cwd=REPO_ROOT, capture_output=True, text=True, timeout=90,
		)
		assert completed.returncode == EXIT_DENY
		assert json.loads(completed.stdout)["decision"] == "deny"

	def test_reads_a_policy_from_stdin(self):
		completed = subprocess.run(
			[sys.executable, "-m", "cli", "scan", "-", "--tags", "loan_app"],
			cwd=REPO_ROOT, input=LENDER_TEXT, capture_output=True, text=True, timeout=90,
		)
		assert completed.returncode == EXIT_DENY
		assert completed.stdout.startswith("DENY")

	def test_never_blocks_waiting_for_input(self):
		"""No interactive prompts, ever. A hang here would wedge a CI job."""
		completed = subprocess.run(
			[sys.executable, "-m", "cli", "scan", "-", "--tags", "generic"],
			cwd=REPO_ROOT, input="", capture_output=True, text=True, timeout=60,
		)
		assert completed.returncode == EXIT_ERROR
