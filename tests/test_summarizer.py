"""HTML cleaning and clause segmentation.

Several of these tests encode bugs found by running against live pages. They
name the site, because a regression test whose reason is forgotten gets
deleted by the next person who finds it inconvenient.
"""

from __future__ import annotations

import pytest

from core.models import DriverResult
from core.summarizer import (
	SimpleSummarizer,
	blocks_from_text,
	clean_html,
	normalize_text,
	segment,
	split_sentences,
)
from tests.fixtures import load_html, load_text


def texts(blocks):
	return [b.text for b in blocks]


class TestCleaner:
	def test_drops_scripts_styles_nav_and_footer(self):
		blocks = clean_html("""
			<html><head><style>.a{color:red}</style><script>var x=1;</script></head>
			<body>
			  <nav class="main-nav"><a>Home</a><a>Loans</a></nav>
			  <h1>Privacy Policy</h1><p>We collect your data.</p>
			  <footer>Copyright 2026</footer>
			</body></html>""")
		assert texts(blocks) == ["Privacy Policy", "We collect your data."]

	def test_marks_headings(self):
		blocks = clean_html("<h2>Data Retention</h2><p>We keep it forever.</p>")
		assert blocks[0].is_heading is True
		assert blocks[1].is_heading is False

	def test_does_not_treat_body_as_chrome(self):
		"""Signal's <body class="index has-navbar-fixed-top"> contains 'nav'.
		Matching class substrings deleted the entire document."""
		html = '<body class="index has-navbar-fixed-top"><p>' + "word " * 60 + "</p></body>"
		assert len(clean_html(html)) == 1

	def test_does_not_treat_a_content_wrapper_as_a_sidebar(self):
		"""Mozilla wraps its policy in <div class="mzp-l-content mzp-has-sidebar">."""
		html = '<div class="mzp-l-content mzp-has-sidebar"><p>' + "word " * 60 + "</p></div>"
		assert len(clean_html(html)) == 1

	def test_does_not_treat_a_sharing_heading_as_social_chrome(self):
		"""<h2 class="how-we-share-your-personal-data"> is the most important
		heading in a privacy policy, and a 'share-' hint matched it."""
		html = (
			'<h2 class="how-we-share-your-personal-data">How we share your data</h2>'
			"<p>" + "word " * 60 + "</p>"
		)
		assert "How we share your data" in texts(clean_html(html))

	def test_falls_back_when_chrome_guessing_eats_the_document(self):
		"""A class-name guess that deletes most of a policy is wrong, and the
		right answer is to keep the noise rather than confidently analyze an
		almost-empty page."""
		html = '<div class="navbar">' + "<p>real policy text here</p>" * 40 + "</div>"
		assert len(clean_html(html)) > 0

	def test_still_drops_chrome_when_it_is_a_small_share_of_the_page(self):
		html = "<nav><a>Home</a></nav>" + "<p>" + "word " * 200 + "</p>"
		assert all("Home" not in t for t in texts(clean_html(html)))

	def test_joins_table_cells_into_one_row(self):
		"""Split per cell, 'Processing fees' and 'Up to 7%' become unrelated
		fragments and no single rule can see both."""
		html = "<table><tr><td>Processing fees</td><td>Up to 7%</td></tr></table>"
		assert texts(clean_html(html)) == ["Processing fees | Up to 7%"]

	def test_does_not_leave_a_trailing_cell_separator(self):
		html = "<table><tr><td>A</td><td>B</td><td></td></tr></table>"
		assert texts(clean_html(html)) == ["A | B"]

	def test_survives_unbalanced_markup(self):
		"""Hand-written policy pages routinely do not close their tags."""
		blocks = clean_html("<div class=nav><span>menu</div><p>Real policy text.</p>")
		assert "Real policy text." in texts(blocks)

	def test_survives_a_real_page(self):
		blocks = clean_html(load_html("page_with_chrome.html"))
		assert len(blocks) > 5
		assert all("<script" not in b.text for b in blocks)

	def test_normalizes_invisible_spaces(self):
		assert normalize_text("a b​ c﻿") == "a b c"


class TestSentenceSplitting:
	@pytest.mark.parametrize("text,expected", [
		("Charges apply (e.g. a fee of Rs. 500). We may share data with Acme Inc. and partners.", 2),
		("See para. 12 of the RBI Directions. One-time access may be taken.", 2),
		("4.1. Collecting Information: We collect data. 4.2. We keep it.", 2),
		("Contact U.S. offices. Then wait.", 2),
	])
	def test_does_not_split_on_abbreviations(self, text, expected):
		assert len(split_sentences(text)) == expected

	def test_returns_offsets_into_the_source(self):
		text = "First sentence here. Second sentence here."
		results = split_sentences(text)
		for offset, sentence in results:
			assert text[offset:offset + len(sentence)] == sentence

	def test_empty_text_yields_nothing(self):
		assert split_sentences("   ") == []

	def test_keeps_a_final_sentence_without_punctuation(self):
		assert len(split_sentences("One thing. A trailing clause with no full stop")) == 2


class TestPlainTextHeadings:
	@pytest.mark.parametrize("line", [
		"PERSONAL INFORMATION COLLECTED",
		"CAMERA",
		"Information we collect:",
		"12. Collection, usage and sharing of data",
		"A. Definitions",
	])
	def test_recognises_headings(self, line):
		assert blocks_from_text(line)[0].is_heading is True

	@pytest.mark.parametrize("line", [
		"We collect your personal information when you register.",
		"This policy explains what we do with your data, and why we do it.",
	])
	def test_does_not_mistake_prose_for_a_heading(self, line):
		assert blocks_from_text(line)[0].is_heading is False


class TestSegmentation:
	def test_carries_the_heading_onto_every_clause_beneath_it(self):
		blocks = blocks_from_text(
			"DATA RETENTION\nWe keep your data for a while. We may keep it longer."
		)
		clauses = segment(blocks)
		assert len(clauses) == 2
		assert all(c.heading == "DATA RETENTION" for c in clauses)

	def test_indexes_clauses_in_document_order(self):
		clauses = segment(blocks_from_text("First clause of the policy. Second clause of the policy."))
		assert [c.index for c in clauses] == [0, 1]

	def test_drops_short_navigation_debris(self):
		assert segment(blocks_from_text("Home\nAbout\nLogin")) == []

	def test_keeps_short_fragments_that_carry_a_figure(self):
		"""'Up to 36% p.a.' is three words and it is the entire point."""
		clauses = segment(blocks_from_text("Rate of Interest | Up to 36% p.a."))
		assert any("36%" in c.text for c in clauses)

	@pytest.mark.parametrize("fragment", ["Up to 7%", "Up to Rs. 1,500", "0.2% per day"])
	def test_keeps_charge_fragments(self, fragment):
		assert segment(blocks_from_text(fragment)), fragment

	def test_offsets_point_into_the_joined_document(self):
		blocks = blocks_from_text("HEADING\nFirst sentence here. Second sentence here.")
		document = "\n".join(b.text for b in blocks)
		for clause in segment(blocks):
			assert document[clause.char_start:clause.char_end] == clause.text


class TestSimpleSummarizer:
	@pytest.fixture
	def summarizer(self):
		return SimpleSummarizer()

	def test_empty_document_yields_no_clauses_rather_than_raising(self, summarizer):
		result = DriverResult(raw_text="   ", origin="x", driver="raw_text")
		assert summarizer.clean(result) == []

	def test_uses_the_html_path_only_when_told_it_is_html(self, summarizer):
		html = "<p>We collect your personal data from you.</p>"
		as_html = summarizer.clean(DriverResult(raw_text=html, origin="x", driver="d", content_type="text/html"))
		as_text = summarizer.clean(DriverResult(raw_text=html, origin="x", driver="d", content_type="text/plain"))
		assert as_html[0].text == "We collect your personal data from you."
		assert "<p>" in as_text[0].text

	def test_tolerates_a_content_type_with_parameters(self, summarizer):
		result = DriverResult(
			raw_text="<p>We collect your personal data here.</p>",
			origin="x", driver="d", content_type="text/html; charset=utf-8",
		)
		assert summarizer.clean(result)[0].text == "We collect your personal data here."

	@pytest.mark.parametrize("fixture", [
		"loan_permissive_truebalance.txt",
		"loan_compliant_kissht.txt",
		"loan_hedged_lazypay.txt",
		"generic_mozilla.txt",
		"generic_signal.txt",
	])
	def test_segments_real_policy_text(self, summarizer, fixture):
		clauses = summarizer.clean(
			DriverResult(raw_text=load_text(fixture), origin=fixture, driver="raw_text")
		)
		assert len(clauses) > 20
		assert all(clause.text.strip() for clause in clauses)
