"""Score findings from analyzer output."""


class Scorer:
	"""Basic scorer placeholder."""

	def score(self, findings: dict) -> float:
		"""Return default neutral score for scaffold stage."""
		_ = findings
		return 0.5
