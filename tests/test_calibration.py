"""The verdict has to tell a private service from an invasive one.

Run over 20 real policies, from Signal to Microsoft, the generic rule set
used to return Warning for every one, with risk scores that mostly measured
length: Microsoft's and Wikipedia's both came to 100. A verdict that never
changes tells a user nothing, so these tests pin it down.

Two kinds of test. The sentences are the exact real ones that misfired, so a
rule change that brings a false positive back fails here by name. The
fixtures pin the verdict for whole documents, so a change that makes
everything a Warning again cannot pass quietly.

The fixtures are excerpts: every sentence that fired on the real policy plus
real surrounding text, checked to produce the same verdict and risk score as
the complete document.
"""

from __future__ import annotations

import pytest

from core.main import run
from core.models import Decision
from tests.fixtures import load_text


def rules_fired(text: str, tags: str = "generic") -> dict[str, str]:
	"""Rule id -> severity for each rule that fired on ``text``."""
	verdict = run("raw_text", text, tags)
	return {f.rule_id: f.severity.value for f in verdict.findings}


# ------------------------------------------------- sentences that misfired


class TestFalsePositivesFromRealPolicies:
	@pytest.mark.parametrize("sentence", [
		"No user data is ever shared with third parties in that process.",
		"This Privacy Policy does not apply to information that You provide to, or that is collected by, any third-party.",
		"DOES PAYTM SHARE PERSONAL DATA WITH THIRD PARTIES/ SUBSIDIARIES/AFFILIATES?",
	])
	def test_a_denial_or_a_question_is_not_third_party_sharing(self, sentence):
		assert "gdpr.sharing.third_party" not in rules_fired(sentence)

	def test_not_to_sell_is_not_a_sale(self):
		"""Paytm: this was a high finding for selling data."""
		assert "gdpr.sharing.sale" not in rules_fired("Not to sell your Personal Data to any third party.")

	def test_buying_from_data_brokers_is_not_selling_to_them(self):
		"""Microsoft: this was a high finding for selling data."""
		text = "Data brokers from which we purchase demographic data and contact information to supplement the data we collect."
		assert "gdpr.sharing.sale" not in rules_fired(text)

	def test_a_commitment_not_to_profile_is_not_targeted_advertising(self):
		"""DuckDuckGo."""
		text = (
			"Ad clicks are managed by Microsoft's ad network and Microsoft has committed to not "
			"associate your ad-click behavior with a user profile and to not store or share that information."
		)
		assert "gdpr.tracking.targeted_ads" not in rules_fired(text)

	def test_non_personal_information_kept_indefinitely_is_not_a_finding(self):
		"""Wikimedia."""
		assert "gdpr.retention.indefinite" not in rules_fired("Non-Personal Information may be retained indefinitely as appropriate.")

	def test_a_bare_right_to_update_the_policy_is_not_a_unilateral_change(self):
		"""Proton, and nearly every other policy."""
		text = "Within the limits of applicable law, the Company reserves the right to review and change this Privacy Policy at any time."
		assert "gdpr.change.unilateral" not in rules_fired(text)


class TestWhatStillFires:
	"""Loosening a rule must not blind it. Each of these should still be caught."""

	def test_selling_data_is_still_a_high_finding(self):
		assert rules_fired("We sell your personal information to other companies.").get("gdpr.sharing.sale") == "high"

	def test_selling_to_data_brokers_is_still_a_sale(self):
		assert "gdpr.sharing.sale" in rules_fired("We may sell your information to data brokers for marketing.")

	def test_sharing_with_advertisers_is_still_flagged(self):
		fired = rules_fired("We may share your information with advertising partners.")
		assert fired.get("gdpr.tracking.targeted_ads") == "medium"

	def test_changing_terms_without_notice_is_still_flagged(self):
		text = "We may modify these terms at our sole discretion and without prior notice."
		assert "gdpr.change.unilateral" in rules_fired(text)

	def test_keeping_personal_data_forever_is_still_flagged(self):
		assert "gdpr.retention.indefinite" in rules_fired("We keep your personal data forever, even after you close your account.")

	def test_training_models_on_your_data_is_still_flagged(self):
		text = "We may use your data to develop and train our AI models."
		assert rules_fired(text).get("ai.training_on_user_content") == "high"

	def test_sharing_with_a_vague_third_party_is_still_a_medium_finding(self):
		fired = rules_fired("We may share your personal data with third parties for their own marketing purposes.")
		assert fired.get("gdpr.sharing.third_party") == "medium"


class TestSharingWithProcessorsIsOnlyANote:
	"""Fired on every one of 20 real policies, so it carried no information."""

	@pytest.mark.parametrize("sentence", [
		"We work with third parties to provide some of our Services.",
		"We rely on service providers to process payments on our behalf.",
		"For information voluntarily provided in surveys, we sometimes use additional vendors for processing.",
	])
	def test_is_low(self, sentence):
		assert rules_fired(sentence).get("gdpr.sharing.third_party") == "low"


# ------------------------------------------------------ whole-document verdicts


PRIVATE = ["generic_duckduckgo.txt", "generic_proton.txt", "generic_signal.txt"]
INVASIVE = ["generic_microsoft.txt", "generic_github.txt"]


class TestVerdictsTellServicesApart:
	@pytest.mark.parametrize("fixture", PRIVATE)
	def test_a_privacy_focused_service_is_an_allow(self, fixture):
		verdict = run("raw_text", load_text(fixture), "generic")
		assert verdict.decision is Decision.ALLOW, [f.rule_id for f in verdict.findings]

	@pytest.mark.parametrize("fixture", INVASIVE)
	def test_an_advertising_and_ai_business_is_a_warning(self, fixture):
		verdict = run("raw_text", load_text(fixture), "generic")
		assert verdict.decision is Decision.WARNING

	def test_notes_on_an_allow_are_still_listed(self):
		"""Allow does not hide anything: the findings are there to read."""
		verdict = run("raw_text", load_text("generic_proton.txt"), "generic")
		assert verdict.decision is Decision.ALLOW
		assert verdict.findings, "Proton still has things worth knowing"
		assert verdict.metadata["notes_only"] is True
		assert verdict.metadata["headline"] == "No red flags detected in this policy."

	def test_the_risk_score_orders_them(self):
		private = max(run("raw_text", load_text(f), "generic").risk_score for f in PRIVATE)
		invasive = min(run("raw_text", load_text(f), "generic").risk_score for f in INVASIVE)
		assert invasive > private

	@pytest.mark.parametrize("fixture", PRIVATE + INVASIVE)
	def test_no_real_policy_scores_100_just_for_matching_often(self, fixture):
		"""The score used to add every matching sentence, so length alone
		pushed it to the cap."""
		assert run("raw_text", load_text(fixture), "generic").risk_score < 100

	def test_a_lender_is_still_denied_under_the_lending_rules(self):
		"""The calibration is for the generic set. RBI's rules stay as strict."""
		verdict = run("raw_text", load_text("loan_permissive_truebalance.txt"), "loan_app")
		assert verdict.decision is Decision.DENY
