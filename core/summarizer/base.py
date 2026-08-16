"""Base summarizer contract."""

from abc import ABC, abstractmethod


class BaseSummarizer(ABC):
    """Summarize policy text into concise output."""

    @abstractmethod
    def summarize(self, text: str, tags: list[str] | None = None) -> str:
        """Return summary text."""
        raise NotImplementedError
