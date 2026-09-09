"""Analyzer components: clauses plus a rule set in, findings out.

Classification is a composition. ``RuleAnalyzer`` is the deterministic member
of that composition, not the whole of it; see ``core/analyzer/base.py`` for
why the seam exists.
"""

from core.analyzer.base import BaseAnalyzer, Classifier
from core.analyzer.composite import CompositeAnalyzer, default_analyzer
from core.analyzer.numeric import RateMatch, extract
from core.analyzer.simple import RuleAnalyzer

__all__ = [
	"BaseAnalyzer",
	"Classifier",
	"CompositeAnalyzer",
	"RateMatch",
	"RuleAnalyzer",
	"default_analyzer",
	"extract",
]
