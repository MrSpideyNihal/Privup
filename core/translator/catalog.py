"""Translated message catalogs, one JSON file per language.

Everything PrivUp says to a user is written in advance: the reason line of
each rule, the headline label of each rule, and a handful of fixed messages.
Nothing is generated at runtime. So a translation is a lookup, done on the
device, with no model and no network call, and it behaves the same on a
laptop and on the cheapest Android phone.

``locales/en.json`` defines every message key. A rule's English text is not
in it: that lives in the rule set, which stays the one definition of a rule.
Every other catalog carries the same message keys plus, per rule id, the
translated ``label``, ``reason`` and, where the rule has one,
``hedge_reason``.

Anything a catalog is missing falls back to English rather than failing. A
rule added in English shows in English until someone translates it, and a
test lists exactly what is missing.

Catalogs may be drafted with a translation model such as IndicTrans2, offline
and ahead of time. Never at runtime: that would send the user's text off the
device.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from core.models import fill_template

__all__ = [
	"LOCALE_DIR",
	"SOURCE_LANGUAGE",
	"Catalog",
	"CatalogError",
	"UnknownLanguageError",
	"available_languages",
	"describe_languages",
	"get_catalog",
	"message",
	"messages",
	"reload_catalogs",
]

LOCALE_DIR = Path(__file__).parent / "locales"

#: The language rule sets are written in, and the one every catalog falls
#: back to.
SOURCE_LANGUAGE = "en"

_LOADED: dict[str, "Catalog"] = {}
_SCANNED = False


class CatalogError(ValueError):
	"""A locale file is malformed. Raised with the file name."""


class UnknownLanguageError(KeyError):
	"""Asked for a language that has no catalog."""

	def __init__(self, code: str) -> None:
		known = ", ".join(available_languages()) or "none"
		super().__init__(f"unknown language {code!r}; available languages: {known}")
		self.code = code


@dataclass(frozen=True, slots=True)
class Catalog:
	"""Every translated string for one language."""

	language: str
	name: str
	native_name: str
	reviewed: bool
	messages: Mapping[str, str]
	rules: Mapping[str, Mapping[str, str]] = field(default_factory=dict)
	rule_sets: Mapping[str, Mapping[str, str]] = field(default_factory=dict)

	def rule_text(self, rule_id: str, variant: str) -> str | None:
		"""The translated ``reason``, ``hedge_reason`` or ``label`` of a rule."""
		return (self.rules.get(rule_id) or {}).get(variant)

	@classmethod
	def from_dict(cls, data: Mapping[str, Any], source: str) -> "Catalog":
		for key in ("language", "name", "native_name"):
			if not isinstance(data.get(key), str) or not data[key].strip():
				raise CatalogError(f"{source}: '{key}' is required")
		messages = data.get("messages")
		if not isinstance(messages, dict):
			raise CatalogError(f"{source}: 'messages' must be an object")
		rules = data.get("rules") or {}
		rule_sets = data.get("rule_sets") or {}
		if not isinstance(rules, dict) or not isinstance(rule_sets, dict):
			raise CatalogError(f"{source}: 'rules' and 'rule_sets' must be objects")
		return cls(
			language=data["language"],
			name=data["name"],
			native_name=data["native_name"],
			reviewed=bool(data.get("reviewed", False)),
			messages=dict(messages),
			rules={k: dict(v) for k, v in rules.items()},
			rule_sets={k: dict(v) for k, v in rule_sets.items()},
		)


def _scan() -> None:
	"""Load every catalog once. A malformed file raises rather than being
	skipped, so a broken translation cannot quietly turn into English."""
	global _SCANNED
	if _SCANNED:
		return
	for path in sorted(LOCALE_DIR.glob("*.json")):
		try:
			data = json.loads(path.read_text(encoding="utf-8"))
		except json.JSONDecodeError as exc:
			raise CatalogError(f"{path.name}: invalid JSON ({exc})") from None
		catalog = Catalog.from_dict(data, path.name)
		if catalog.language != path.stem:
			raise CatalogError(
				f"{path.name}: declares language {catalog.language!r}, "
				f"but the file name says {path.stem!r}"
			)
		_LOADED[catalog.language] = catalog
	_SCANNED = True


def reload_catalogs() -> None:
	"""Forget loaded catalogs. Used by tests."""
	global _SCANNED
	_LOADED.clear()
	_SCANNED = False


def available_languages() -> list[str]:
	"""Codes of every language with a catalog, sorted."""
	_scan()
	return sorted(_LOADED)


def describe_languages() -> list[dict[str, Any]]:
	"""Code, English name, native name and review status of each language."""
	_scan()
	return [
		{
			"code": c.language,
			"name": c.name,
			"native_name": c.native_name,
			"reviewed": c.reviewed,
		}
		for c in (_LOADED[code] for code in available_languages())
	]


def get_catalog(code: str) -> Catalog:
	_scan()
	try:
		return _LOADED[code]
	except KeyError:
		raise UnknownLanguageError(code) from None


def message(language: str, key: str, **values: Any) -> str:
	"""One UI message in ``language``, falling back to English, then to the key.

	For front ends: the CLI, the local UI, the extension panel and the
	Android result screen all draw their fixed text from here.
	"""
	_scan()
	for code in (language, SOURCE_LANGUAGE):
		catalog = _LOADED.get(code)
		if catalog is not None and key in catalog.messages:
			return fill_template(catalog.messages[key], values)
	return key


def messages(language: str) -> dict[str, str]:
	"""Every UI message in ``language``, English where it has none.

	For a front end that renders on its own side of a process boundary, such
	as the local UI's browser page, and needs the whole set at once.
	"""
	_scan()
	merged = dict(_LOADED[SOURCE_LANGUAGE].messages) if SOURCE_LANGUAGE in _LOADED else {}
	if language in _LOADED:
		merged.update(_LOADED[language].messages)
	return merged
