"""Resolve service names or domains to policy URLs."""


class Resolver:
	"""Basic resolver placeholder."""

	def resolve_policy_url(self, service_or_url: str) -> str:
		"""Return URL input directly for now.

		In later versions this will map service names to known policy URLs.
		"""
		return service_or_url
