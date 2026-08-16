"""Minimal summarizer implementation."""

from core.summarizer.base import BaseSummarizer


class SimpleSummarizer(BaseSummarizer):
    """Basic summarizer placeholder for early development."""

    def summarize(self, text: str, tags: list[str] | None = None) -> str:
        if tags:
            return f"Summary placeholder for tags: {', '.join(tags)}"
        return "Summary placeholder: pipeline skeleton ready"
