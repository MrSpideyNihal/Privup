"""STUB: cross-reference a lender against RBI's public DLA directory.

Not implemented. This module exists so that the integration has a defined
shape and a single call site before anyone builds it.

Background. RBI's Digital Lending Directions 2025 require every Regulated
Entity to report the Digital Lending Apps it deploys to the Centralised
Information Management System, and RBI publishes the resulting directory
publicly (in effect from 01 November 2025). That directory is the difference
between two questions PrivUp currently cannot tell apart:

	"this app asks for things a regulated lender may not ask for"
	"this app is not a regulated lender at all"

The second is the more serious answer, and it is the one a borrower facing an
unlicensed lender most needs.

What implementing this must not do:

  - It must not make a network call from here. Every network call in PrivUp
    happens inside a driver's ``fetch``. A live directory lookup belongs in a
    driver, or behind a locally cached snapshot shipped with the app, so that
    the analyzer stays offline and deterministic.
  - It must not change any other module. ``lookup`` is already called by the
    analyzer for every ``loan_app`` finding and its result is recorded on
    ``Finding.metadata['dla_directory']``. Returning a real
    ``DirectoryEntry`` instead of ``None`` is the whole change.

Until then ``lookup`` returns ``None``, which means "not checked" and never
"not found". Those must not be confused: reporting an unlisted lender as
verified, or a verified lender as unlisted, are both harmful and neither is
better than saying nothing.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["DirectoryEntry", "lookup", "IMPLEMENTED"]

#: Flag so callers and tests can assert on the stub rather than guess.
IMPLEMENTED = False


@dataclass(frozen=True, slots=True)
class DirectoryEntry:
	"""One row of RBI's published DLA directory.

	Defined now so the field names are settled before anything depends on
	them. Nothing constructs this yet.
	"""

	app_name: str
	regulated_entity: str
	entity_type: str
	listed: bool
	source_url: str | None = None
	as_of: str | None = None


def lookup(origin: str) -> DirectoryEntry | None:
	"""Return the directory entry for ``origin``, or None if not checked.

	``origin`` is whatever the driver recorded: a URL, a package name, an app
	name. Resolving those to a directory row is part of the work that has not
	been done.

	Always returns ``None`` in this phase. ``None`` means "no check was
	performed". It does not mean the lender is absent from the directory.
	"""
	del origin  # Deliberately unused until this is implemented.
	return None
