# /*
#  *  ╔════════════════════════════════════════════════════════════╗
#  *  ║                                                            ║
#  *  ║                     PRIVACY-URL-FINDER                     ║
#  *  ║                                                            ║
#  *  ║                         by Nihal Rodge                     ║
#  *  ║                                                            ║
#  *  ║  GitHub: github.com/MrSpideyNihal/privacy-url-finder       ║
#  *  ║                                                            ║
#  *  ╚════════════════════════════════════════════════════════════╝
#  */
#
# This code integrates privacy-url-finder for company search and link resolution:
# https://github.com/MrSpideyNihal/privacy-url-finder
#

"""Fetch a policy from the web.

Give it a policy URL and it reads it. Give it a homepage and it looks for the
policy link and follows it once, because that is what users actually paste.
Give it a company or app name (e.g. "KreditBee", "Swiggy", or an Android
package name) and it automatically discovers and verifies the official policy
link using the integrated Privacy URL Finder engine.

This driver is the only component in PrivUp that makes a network request.
Everything downstream receives a ``DriverResult`` and cannot tell the
difference between this and a pasted string, which is the point.

A known limit, worth stating rather than discovering later: several Indian
lending sites render their policy entirely in JavaScript and return an empty
shell to a plain HTTP GET. Of the pages this was built against, navi.com,
kreditbee.in and stashfin.com all do. This driver reports what it actually
received, and the scorer turns an empty document into a Warning rather than
an Allow. Making those pages readable needs a headless browser, which is a
separate driver and a heavy dependency, not a change here.
"""

from __future__ import annotations

from core.models import DriverResult
from core.scraper.base import Driver, DriverError
from core.scraper.extractor import decode, looks_like_policy
from core.scraper.fetcher import DEFAULT_TIMEOUT, fetch_url, normalize_url
from core.scraper.finder import PrivacyURLFinder, ResolutionStatus
from core.scraper.finder.utils import is_android_package
from core.scraper.registry import register_driver
from core.scraper.resolver import find_policy_links

__all__ = ["UrlDriver", "CompanyDriver"]

# Only worth following a link if the page we landed on is clearly not the
# policy. Below this score the guess is not good enough to spend a request.
_MIN_LINK_SCORE = 80


def _is_company_query(target: str) -> bool:
	"""Determine whether target represents a company/app name rather than a URL."""
	clean = target.strip()
	if "://" in clean:
		return False
	if "/" in clean or "?" in clean or "#" in clean:
		return False
	if is_android_package(clean):
		return True
	if " " in clean or "." not in clean:
		return True
	return False


@register_driver
class UrlDriver(Driver):
	"""HTTP driver. Follows redirects, and one policy link if needed."""

	name = "url"
	default_content_type = "text/html"
	description = "Fetch a policy over HTTP by URL, domain, or company name."

	def __init__(self, timeout: float = DEFAULT_TIMEOUT, follow_policy_link: bool = True) -> None:
		self.timeout = timeout
		self.follow_policy_link = follow_policy_link

	def _fetch_company(self, company_name: str) -> DriverResult:
		"""Discover and verify the privacy policy URL for a company name."""
		finder = PrivacyURLFinder(verify=True, timeout=self.timeout, auto_save=False)
		res = finder.find(company_name)

		if res.status not in (ResolutionStatus.FOUND, ResolutionStatus.PROBABLE, ResolutionStatus.UNVERIFIED) or not res.url:
			raise DriverError(f"Could not find a verified privacy policy for '{company_name}'")

		response = fetch_url(res.url, timeout=self.timeout)
		text = decode(response.body, response.charset)

		if not text.strip():
			raise DriverError(f"{response.final_url} returned an empty document")

		return self.build_result(
			raw_text=text,
			origin=response.final_url,
			content_type=response.content_type,
			metadata={
				"requested_target": company_name,
				"resolved_policy_url": res.url,
				"final_url": response.final_url,
				"status": response.status,
				"bytes": len(response.body),
				"entity_name": res.entity_name or company_name,
				"finder_status": res.status.value,
				"finder_confidence": res.confidence,
				"resolved_via": res.method,
				"finder_title": res.title,
				"domain": res.domain,
			},
		)

	def fetch(self, target: str) -> DriverResult:
		if not isinstance(target, str) or not target.strip():
			raise DriverError("url driver needs a URL")

		target_clean = target.strip()
		if _is_company_query(target_clean):
			return self._fetch_company(target_clean)

		requested = normalize_url(target_clean)
		response = fetch_url(requested, timeout=self.timeout)
		text = decode(response.body, response.charset)

		followed_from: str | None = None
		if self.follow_policy_link and not looks_like_policy(text):
			candidate = self._best_link(text, response.final_url)
			if candidate is not None:
				try:
					linked = fetch_url(candidate, timeout=self.timeout)
				except DriverError:
					# The landing page is still a real document. Reporting
					# what we have beats failing because a guess did not
					# pan out.
					linked = None
				if linked is not None:
					followed_from = response.final_url
					response = linked
					text = decode(linked.body, linked.charset)

		if not text.strip():
			raise DriverError(f"{response.final_url} returned an empty document")

		return self.build_result(
			raw_text=text,
			origin=response.final_url,
			content_type=response.content_type,
			metadata={
				"requested_url": requested,
				"final_url": response.final_url,
				"status": response.status,
				"followed_policy_link_from": followed_from,
				"bytes": len(response.body),
			},
		)

	@staticmethod
	def _best_link(html: str, base_url: str) -> str | None:
		for link in find_policy_links(html, base_url):
			if link.score >= _MIN_LINK_SCORE and link.url != base_url:
				return link.url
		return None


@register_driver
class CompanyDriver(UrlDriver):
	"""Fetch a privacy policy by company name or app ID using Privacy URL Finder."""

	name = "company"
	default_content_type = "text/html"
	description = "Discover and fetch a policy by company/app name using Privacy URL Finder."

	def fetch(self, target: str) -> DriverResult:
		if not isinstance(target, str) or not target.strip():
			raise DriverError("company driver needs a company or app name")
		return self._fetch_company(target.strip())
