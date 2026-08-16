"""Shared data schemas."""

from dataclasses import dataclass, field


@dataclass
class Findings:
    """Structured findings from analysis."""

    tags: list[str] = field(default_factory=list)
    highlights: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)


@dataclass
class Result:
    """Final output container."""

    input_service: str
    score: float
    summary: str
    findings: Findings
