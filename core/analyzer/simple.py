"""Minimal analyzer implementation."""

from core.analyzer.base import BaseAnalyzer


class SimpleAnalyzer(BaseAnalyzer):
    """Basic analyzer placeholder for early development."""

    def analyze(self, text: str, tags: list[str] | None = None) -> dict:
        return {
            "tags": tags or [],
            "highlights": [],
            "risks": [],
            "notes": ["Analyzer skeleton in place"],
        }
