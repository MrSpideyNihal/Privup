"""Turn cleaned blocks into heading-aware, sentence-level clauses.

Sentence level is the right granularity for this pipeline, and reading real
policies is what settles it. LazyPay's phone-data section contains, a few
hundred words apart:

	"we ideally restrain from accessing mobile phone resources like file and
	media, contact list, call logs, telephony functions, etc."

	"With your permission [...] we will transmit your SMS log data to our
	internal server"

Analyze the section as one unit and those cancel out into mush. Analyze
sentence by sentence and the second one stands on its own as a finding, which
is what a borrower actually needs to be told.

Headings are carried onto every clause beneath them because a single sentence
loses the context that makes it legible. "We retain this as long as necessary"
means one thing under "Data Retention" and another under "Cookie Preferences".
"""

from __future__ import annotations

import re

from core.models import Clause
from core.summarizer.cleaner import Block, normalize_text

__all__ = ["blocks_from_text", "segment", "split_sentences"]

# Tokens ending in "." that do not end a sentence. Policy prose is dense with
# them, and splitting on "e.g." or "Rs." shreds exactly the clauses about
# charges and permissions that matter most here.
_ABBREVIATIONS = frozenset({
	"e.g.", "i.e.", "etc.", "viz.", "vs.", "cf.", "approx.", "incl.", "excl.",
	"resp.", "no.", "nos.", "art.", "arts.", "sec.", "secs.", "cl.", "para.",
	"paras.", "fig.", "ch.", "pp.", "vol.", "ed.", "al.",
	"inc.", "ltd.", "pvt.", "co.", "corp.", "llc.", "llp.", "plc.", "pte.",
	"mr.", "mrs.", "ms.", "dr.", "prof.", "sr.", "jr.", "st.",
	"u.s.", "u.k.", "u.a.e.", "a.m.", "p.m.",
	"rs.", "inr.", "usd.", "eur.",
})

# A candidate boundary: terminal punctuation, optional closing quote/bracket,
# then whitespace.
_BOUNDARY = re.compile(r'(?<=[.!?])["\'’”)\]]*\s+')

# What a real new sentence starts with.
_SENTENCE_START = re.compile(r'["\'‘“(\[]*[A-Z0-9]')

# The token immediately before a candidate boundary.
_LAST_TOKEN = re.compile(r'(\S+)\s*$')

# "4.", "4.1.", "A.", "iv." - list markers, not sentence ends.
_LIST_MARKER = re.compile(r'^\(?(?:\d+(?:\.\d+)*|[A-Za-z]|[ivxlcIVXLC]+)[.)]$')

# A heading in plain text: short, not a full sentence.
_MAX_HEADING_WORDS = 14
_SECTION_NUMBER = re.compile(r'^\s*\(?(?:\d+(?:\.\d+)*|[A-Z]|[IVXLC]+)[.)]\s+\S')

# Below this, a fragment is navigation debris or a stray label rather than a
# clause worth classifying.
_MIN_CLAUSE_WORDS = 4

# ...unless it carries a figure. A lender's schedule of charges is full of
# short, decisive fragments: "Up to 7%", "Up to 36% p.a.", "Up to Rs. 1,500".
# Those are three words and they are the whole point, so anything containing
# a percentage or a currency amount survives the length filter.
_CARRIES_A_FIGURE = re.compile(
	r"\d\s*%|%\s*\d|(?:Rs\.?|INR|₹|\$|€|£)\s*[\d,]|\bp\.?a\.?\b|\bper annum\b",
	re.IGNORECASE,
)


def _worth_keeping(sentence: str) -> bool:
	"""True when a fragment is substantial enough, or numeric enough, to keep."""
	if len(sentence.split()) >= _MIN_CLAUSE_WORDS:
		return True
	return bool(_CARRIES_A_FIGURE.search(sentence))


def _is_abbreviation(text_before: str) -> bool:
	"""True when the '.' ending ``text_before`` belongs to an abbreviation."""
	match = _LAST_TOKEN.search(text_before)
	if not match:
		return False
	token = match.group(1)
	lowered = token.lower()

	if lowered in _ABBREVIATIONS:
		return True
	if _LIST_MARKER.match(token):
		return True
	# Single initial: "J. Smith". Also catches "A." starting a lettered clause.
	if len(token) == 2 and token[0].isalpha() and token[1] == ".":
		return True
	# Dotted acronym with no lower-case letters: "U.S.A.", "R.B.I."
	if len(token) > 2 and token.endswith(".") and re.fullmatch(r"(?:[A-Za-z]\.)+", token):
		return True
	return False


def split_sentences(text: str) -> list[tuple[int, str]]:
	"""Split ``text`` into ``(offset, sentence)`` pairs.

	Offsets are relative to ``text`` so callers can map a clause back to the
	document it came from.
	"""
	text = text.strip()
	if not text:
		return []

	sentences: list[tuple[int, str]] = []
	start = 0
	for match in _BOUNDARY.finditer(text):
		end = match.start()
		if _is_abbreviation(text[start:end]):
			continue
		if not _SENTENCE_START.match(text[match.end():match.end() + 3]):
			continue
		piece = text[start:end].strip()
		if piece:
			sentences.append((start + text[start:end].index(piece[0]), piece))
		start = match.end()

	tail = text[start:].strip()
	if tail:
		sentences.append((start + text[start:].index(tail[0]), tail))
	return sentences


def _looks_like_heading(line: str) -> bool:
	"""Heuristic heading test for plain-text input, which has no <h2>."""
	words = line.split()
	if not words or len(words) > _MAX_HEADING_WORDS:
		return False
	if line.endswith((".", "!", "?", ",", ";")):
		return False

	if line.endswith(":"):
		return True
	stripped = line.rstrip(":").strip()
	if not stripped:
		return False
	# ALL CAPS section titles: "PERSONAL INFORMATION COLLECTED", "CAMERA"
	letters = [c for c in stripped if c.isalpha()]
	if letters and all(c.isupper() for c in letters):
		return True
	# "12. Collection, usage and sharing of data with third parties"
	if _SECTION_NUMBER.match(stripped):
		return True
	return False


def blocks_from_text(text: str) -> list[Block]:
	"""Build blocks from plain text, inferring headings from line shape.

	Used for the ``text/plain`` path, where the driver handed over prose with
	no markup to tell us what a heading is.
	"""
	blocks: list[Block] = []
	for raw_line in text.splitlines():
		line = normalize_text(raw_line)
		if line:
			blocks.append(Block(line, _looks_like_heading(line)))
	return blocks


def segment(blocks: list[Block]) -> list[Clause]:
	"""Flatten blocks into ordered clauses, each tagged with its heading.

	``char_start``/``char_end`` index into the document formed by joining the
	block texts with newlines, which is the text a front end would display.
	"""
	clauses: list[Clause] = []
	heading: str | None = None
	cursor = 0
	index = 0

	for block in blocks:
		if block.is_heading:
			heading = block.text
			cursor += len(block.text) + 1
			continue

		for offset, sentence in split_sentences(block.text):
			if _worth_keeping(sentence):
				start = cursor + offset
				clauses.append(
					Clause(
						text=sentence,
						index=index,
						heading=heading,
						char_start=start,
						char_end=start + len(sentence),
					)
				)
				index += 1
		cursor += len(block.text) + 1

	return clauses
