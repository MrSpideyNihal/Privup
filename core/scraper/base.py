"""Driver contract.

A driver is the only part of PrivUp allowed to touch the outside world, and
only from inside ``fetch``. Everything downstream sees a ``DriverResult`` and
has no idea whether it came from a URL, a paste buffer, an APK or a PDF.

To add a driver:

	from core.models import DriverResult
	from core.scraper.base import Driver
	from core.scraper.registry import register_driver

	@register_driver
	class PlayStoreDriver(Driver):
		name = "play_store"

		def fetch(self, target: str) -> DriverResult:
			...
			return self.build_result(text, origin=target)

Nothing in ``core/analyzer``, ``core/scorer`` or ``core/main.py`` changes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar, Mapping

from core.models import DriverResult

__all__ = ["Driver", "DriverError"]


class DriverError(RuntimeError):
	"""A driver could not produce text for the given target.

	Raised for an unreachable URL, an unreadable file, an empty paste. It is
	deliberately not a silent empty result: refusing to analyze is honest,
	analyzing nothing and reporting Allow is not.
	"""


class Driver(ABC):
	"""Base class for every source of policy text."""

	#: Registry key. Must be unique and stable, it is a public CLI value.
	name: ClassVar[str] = ""

	#: What ``fetch`` normally returns. Override per call via build_result.
	default_content_type: ClassVar[str] = "text/plain"

	#: One line shown by the CLI's driver listing.
	description: ClassVar[str] = ""

	@abstractmethod
	def fetch(self, target: str) -> DriverResult:
		"""Return the policy text for ``target`` plus where it came from.

		``target`` is whatever the driver declares it understands: a URL, a
		blob of pasted text, a package name. Raise ``DriverError`` if the
		target cannot be read. Never return an empty DriverResult to signal
		failure.
		"""
		raise NotImplementedError

	def build_result(
		self,
		raw_text: str,
		origin: str,
		content_type: str | None = None,
		metadata: Mapping[str, Any] | None = None,
	) -> DriverResult:
		"""Helper so subclasses do not each re-stamp driver name and time."""
		return DriverResult(
			raw_text=raw_text,
			origin=origin,
			driver=self.name,
			content_type=content_type or self.default_content_type,
			metadata=dict(metadata or {}),
		)
