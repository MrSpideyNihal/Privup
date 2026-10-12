"""Showing a verdict in the user's own language, entirely on the device.

See ``catalog.py`` for why this is a lookup rather than a model, and
``translator.py`` for what is and is not translated.
"""

from core.translator.catalog import (
	LOCALE_DIR,
	SOURCE_LANGUAGE,
	Catalog,
	CatalogError,
	UnknownLanguageError,
	available_languages,
	describe_languages,
	get_catalog,
	message,
	messages,
	reload_catalogs,
)
from core.translator.translator import translate

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
	"translate",
]
