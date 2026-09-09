"""Preprocessing contract.

The summarizer stage sits between a driver and the analyzer. It takes the
``DriverResult`` a driver produced and returns the ``Clause`` list the
analyzer classifies.

It is called "summarizer" because that is what this slot is named in the
project architecture. In this phase it does not summarize in the generative
sense; it reduces a page to the sentences worth reading, which is the same
job done honestly. A model-backed implementation can be dropped in later by
subclassing this and registering it, without any other stage changing.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from core.models import Clause, DriverResult

__all__ = ["BaseSummarizer"]


class BaseSummarizer(ABC):
	"""Turn raw driver output into clauses ready for classification."""

	@abstractmethod
	def clean(self, result: DriverResult) -> list[Clause]:
		"""Return the ordered clauses found in ``result``.

		Must return an empty list rather than raise when the document simply
		contains no prose. It is the caller's job to decide what an empty
		document means; a JavaScript-only page that yields nothing is a real
		outcome the pipeline has to report, not an error to swallow.
		"""
		raise NotImplementedError
