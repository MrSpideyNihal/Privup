"""Base analyzer contract."""

from abc import ABC, abstractmethod


class BaseAnalyzer(ABC):
    """Analyze policy text and return structured findings."""

    @abstractmethod
    def analyze(self, text: str, tags: list[str] | None = None) -> dict:
        """Return findings extracted from policy text."""
        raise NotImplementedError
