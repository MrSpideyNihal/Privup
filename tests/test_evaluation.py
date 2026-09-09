"""The evaluation harness, and the pattern bugs it found.

The regression tests here are the valuable part. Each one is a mistake the
rule matcher actually made on live policy text, found only because there was
finally a way to look at clauses it did *not* flag. Every one of them names
the sentence, because a regression test whose reason is forgotten gets deleted
by the next person who finds it inconvenient.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from core.analyzer import RuleAnalyzer
from core.models import Clause
from core.tags import get_tag_set
from tests.evaluation import LABELS_PATH, evaluate, load_labels, rule_sets_for
from tests.evaluation.metrics import Counts, build_report

REPO_ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = Path(__file__).parent / "evaluation" / "baseline.json"


def categories(text: str, rule_set: str = "generic") -> set[str]:
	findings = RuleAnalyzer().classify(
		[Clause(text=text, index=0)], get_tag_set(rule_set), origin="test"
	)
	return {f.category for f in findings if f.clause.index >= 0}


class TestMetrics:
	def test_counts_arithmetic(self):
		counts = Counts(true_positives=3, false_positives=1, false_negatives=2)
		assert counts.support == 5
		assert counts.predicted == 4
		assert counts.precision == pytest.approx(0.75)
		assert counts.recall == pytest.approx(0.6)
		assert counts.f1 == pytest.approx(2 * 0.75 * 0.6 / 1.35)

	def test_silence_is_perfect_precision_and_zero_recall(self):
		"""A classifier that flags nothing has told no lies. Recall is what
		punishes it, and that asymmetry has to be visible."""
		counts = Counts(true_positives=0, false_positives=0, false_negatives=4)
		assert counts.precision == 1.0
		assert counts.recall == 0.0
		assert counts.f1 == 0.0

	def test_macro_and_micro_disagree_when_a_rare_category_fails(self):
		"""Micro is dominated by common categories, which is exactly how a
		rare but critical one disappears."""
		report = build_report(
			[("t", {"common"}, {"common"})] * 20
			+ [("t", set(), {"rare"})]
		)
		assert report.micro.f1 > report.macro()["f1"]

	def test_report_serializes(self):
		report = build_report([("t", {"a"}, {"a"}), ("t", {"b"}, set())])
		payload = json.loads(json.dumps(report.to_dict()))
		assert payload["by_category"]["a"]["f1"] == 1.0


class TestLabelledSet:
	def test_is_honest_about_being_unreviewed(self):
		"""Ground truth written by the system under test is circular, and the
		file has to say so rather than imply an authority it lacks."""
		meta, _ = load_labels()
		assert "UNREVIEWED" in meta["review_status"]
		assert "circular" in meta["warning"]

	def test_every_clause_carries_provenance(self):
		_, clauses = load_labels()
		for entry in clauses:
			assert entry["source"].startswith("http")
			assert entry["retrieved"]
			assert entry["text"].strip()

	def test_contains_negatives_as_well_as_positives(self):
		"""Precision is measured on the negatives. A set of only positives
		would make a classifier that flags everything look perfect."""
		_, clauses = load_labels()
		negatives = [c for c in clauses if not c["labels"]]
		assert len(negatives) >= 20
		assert len(negatives) > len(clauses) - len(negatives)

	def test_labels_use_the_shipped_category_vocabulary(self):
		known = set(get_tag_set("generic").categories()) | set(get_tag_set("loan_app").categories())
		_, clauses = load_labels()
		for entry in clauses:
			assert set(entry["labels"]) <= known, entry["id"]

	def test_lending_clauses_are_scored_under_both_rule_sets(self):
		"""generic covers any service; loan_app supplements it. Scoring a
		lender only against loan_app marks the classifier down for missing
		categories that rule set does not define."""
		assert rule_sets_for({"rule_set": "loan_app"}) == ["generic", "loan_app"]
		assert rule_sets_for({"rule_set": "generic"}) == ["generic"]


class TestPatternBugsFoundByEvaluation:
	"""Four systematic bugs, each found on live text."""

	def test_a_profile_picture_is_not_profiling(self):
		"""WhatsApp: 'You can add other information to your account, such as a
		profile picture'. Matched by a bare 'profil' pattern."""
		assert "tracking_profiling" not in categories(
			'You can add other information to your account, such as a profile picture and "about" information.'
		)
		assert "tracking_profiling" not in categories(
			"Changing Your Mobile Phone Number, Profile Name And Picture, And About Information."
		)

	def test_profiling_itself_is_still_caught(self):
		assert "tracking_profiling" in categories(
			"We use automated systems that analyze your content to provide personalized ads."
		)

	@pytest.mark.parametrize("text,category", [
		("We don’t share information that personally identifies you with advertisers.", "third_party_sharing"),
		("We don’t show you personalized ads based on your content from Drive, Gmail, or Photos.", "tracking_profiling"),
	])
	def test_a_curly_apostrophe_still_counts_as_a_denial(self, text, category):
		"""The worst of the four. Real web pages write don’t with U+2019, and
		every negation list used a straight apostrophe, so negation silently
		did not work on most live text."""
		assert category not in categories(text)

	def test_a_straight_apostrophe_also_still_counts(self):
		assert "third_party_sharing" not in categories(
			"We don't share information that personally identifies you with advertisers."
		)

	def test_refusing_to_share_counts_however_it_is_phrased(self):
		"""WhatsApp: 'Our Services do not provide access to emergency service
		providers'. The negation list only knew four verbs."""
		assert "third_party_sharing" not in categories(
			"Our Services do not provide access to emergency service providers like the police, "
			"fire department, hospitals, or other public safety organizations."
		)

	@pytest.mark.parametrize("text", [
		"To do this, BH has adopted measures like internal reviews of the data collection, "
		"storage and processing practices and security measures.",
		'"Processing" in relation to personal data means an automated operation such as '
		"collection, recording, organization, structuring, storage, adaptation.",
		"We employ industry standard security measures to protect your personal information "
		"during transmission and storage.",
	])
	def test_generic_storage_is_not_phone_storage_access(self, text):
		"""'storage' in 'collection, usage, storage, sharing' is a
		data-handling word, and it was firing an RBI phone-permission rule."""
		assert "disallowed_permission" not in categories(text, "loan_app")

	def test_real_phone_storage_access_is_still_caught(self):
		assert "disallowed_permission" in categories(
			"We access the files and media on your device to verify your documents.", "loan_app"
		)

	def test_telling_a_user_how_to_revoke_a_permission_is_not_a_risk(self):
		"""Kissht: 'you can modify permissions on your Android device for
		access to Camera'. That is self-protection advice, reported as a
		threat."""
		assert "permission_scope" not in categories(
			"For example, you can modify permissions on your Android device for access to "
			"Camera or Audio permissions.", "loan_app"
		)

	def test_retention_expressed_as_a_condition_is_caught(self):
		"""Google: 'We keep some data until you delete your Google Account'.
		A retention clause with none of the retention vocabulary."""
		assert "data_retention" in categories(
			"We keep some data until you delete your Google Account, such as information "
			"about how often you use our services."
		)

	def test_consent_by_mere_use_is_caught_for_lenders(self):
		"""loan_app had no clause-level consent rule at all, only the
		document-absence one, so this passed silently."""
		assert "consent" in categories(
			"By mere use of the Platform(s), you expressly and unconditionally agree to the "
			"terms and conditions of this Privacy Policy.", "loan_app"
		)


class TestHarness:
	def test_produces_a_report(self):
		report = evaluate()
		assert report.by_category
		assert 0.0 <= report.micro.f1 <= 1.0

	def test_is_runnable_as_a_script(self):
		completed = subprocess.run(
			[sys.executable, "-m", "tests.evaluation", "--json"],
			cwd=REPO_ROOT, capture_output=True, text=True, timeout=120,
		)
		assert completed.returncode == 0
		payload = json.loads(completed.stdout)
		assert "micro" in payload["report"]

	def test_does_not_regress_below_the_recorded_baseline(self):
		"""The baseline is committed so a rule change that trades precision
		for recall, or the reverse, is visible in review rather than
		discovered later."""
		baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
		report = evaluate().to_dict()

		for metric in ("precision", "recall", "f1"):
			recorded = baseline["micro"][metric]
			current = report["micro"][metric]
			assert current >= recorded - 0.02, (
				f"micro {metric} fell from {recorded} to {current}. If this is a "
				f"deliberate trade, update {BASELINE_PATH.name} in the same commit."
			)

	def test_precision_stays_high(self):
		"""Patterns are worth having because they are precise. A pattern
		change that costs precision has given up the only advantage."""
		assert evaluate().micro.precision >= 0.90
