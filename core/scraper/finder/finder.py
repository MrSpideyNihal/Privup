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
# This code was integrated from privacy-url-finder:
# https://github.com/MrSpideyNihal/privacy-url-finder
#

"""Main pipeline orchestrator for Privacy URL Finder."""

import logging
import time
from typing import List, Optional

logger = logging.getLogger("privacy_url_finder")

from .dataset.manager import DatasetManager
from .models import (
    CandidateLink,
    PolicyResult,
    ResolutionStatus,
    SourceType,
    ValidationResult,
)
from .resolvers.crawler import HomepageCrawlerResolver
from .resolvers.dataset_resolver import DatasetResolver
from .resolvers.heuristics import HeuristicsResolver
from .resolvers.playstore import PlayStoreResolver
from .resolvers.search import SearchResolver
from .utils import (
    extract_domain,
    guess_candidate_domains,
    is_android_package,
    is_url,
    normalize_query,
)
from .validator import PolicyValidator


class PrivacyURLFinder:
    """Multi-tiered discovery and verification pipeline for privacy policy URLs."""

    def __init__(
        self,
        verify: bool = True,
        dataset_manager: Optional[DatasetManager] = None,
        timeout: float = 6.0,
        enable_search_fallback: bool = True,
        auto_save: bool = False,
    ):
        self.verify = verify
        self.timeout = timeout
        self.enable_search_fallback = enable_search_fallback
        self.auto_save = auto_save

        self.dataset_manager = dataset_manager or DatasetManager()
        self.validator = PolicyValidator()

        # Initialize resolvers
        self.dataset_resolver = DatasetResolver(self.dataset_manager)
        self.heuristics_resolver = HeuristicsResolver(timeout=self.timeout)
        self.crawler_resolver = HomepageCrawlerResolver(timeout=self.timeout)
        self.playstore_resolver = PlayStoreResolver(timeout=self.timeout)
        self.search_resolver = SearchResolver(timeout=self.timeout)

    def _save_verified_to_dataset(self, res: PolicyResult, query: str) -> None:
        """Automatically persist verified newly discovered privacy policies to policies.json."""
        import re
        domain = res.domain
        if not domain and res.url:
            domain = extract_domain(res.url)

        entity_name = res.entity_name
        if not entity_name:
            clean_title = re.sub(
                r"(?i)(privacy\s+policy|privacy\s+notice|privacy\s+statement|terms\s+and\s+conditions|official\s+site|[-–—|•:]+)",
                " ",
                res.title or "",
            ).strip()
            if 2 < len(clean_title) <= 40:
                entity_name = clean_title
            elif domain:
                brand = domain.split(".")[0]
                entity_name = brand.capitalize()
            else:
                entity_name = query.title()

        aliases = []
        q_clean = query.strip().lower()
        if q_clean and q_clean != entity_name.lower():
            aliases.append(q_clean)

        clean_id = re.sub(r"[^a-z0-9]", "", (entity_name or domain or query).lower())

        entry = {
            "id": clean_id,
            "name": entity_name,
            "aliases": aliases,
            "domain": domain or "",
            "privacy_url": res.url,
            "category": "auto_discovered",
            "country": "GLOBAL",
        }

        saved = self.dataset_manager.save_entry(entry, persist=True)
        if saved:
            res.metadata["saved_to_dataset"] = True
            res.entity_name = entity_name

    def _finish(self, res: PolicyResult, query: str) -> PolicyResult:
        if self.auto_save and res.status in (ResolutionStatus.FOUND, ResolutionStatus.UNVERIFIED) and res.url:
            if res.source != SourceType.DATASET:
                self._save_verified_to_dataset(res, query)
        return res

    def find(self, query: str) -> PolicyResult:
        """Find the official privacy policy URL for a query."""
        start_time = time.time()
        clean_q = normalize_query(query)
        logger.info("Resolving privacy policy for: %s", query)
        if not clean_q:
            logger.warning("Empty query provided, returning NOT_FOUND")
            return PolicyResult(
                query=query,
                status=ResolutionStatus.NOT_FOUND,
                method="empty_query",
                elapsed_ms=(time.time() - start_time) * 1000,
            )

        # Identify query type
        is_query_url = is_url(clean_q)
        is_pkg = is_android_package(clean_q)
        domain = extract_domain(clean_q) if is_query_url else None

        # -------------------------------------------------------------
        # TIER 1: Curated Dataset Lookup (Fastest, zero-network)
        # -------------------------------------------------------------
        logger.debug("Tier 1: Checking curated dataset for '%s'", clean_q)
        dataset_candidates = self.dataset_resolver.resolve(clean_q, domain=domain)
        if dataset_candidates:
            cand = dataset_candidates[0]
            val_res = None
            if self.verify:
                is_valid, val_res = self.validator.validate_url(cand.url, timeout=self.timeout)
                if is_valid:
                    confidence = val_res.confidence
                else:
                    # Curated dataset entry whose live page may be SPA/JS-rendered or temporarily blocked
                    confidence = 0.90
                    val_res = ValidationResult(
                        is_valid=True,
                        confidence=0.90,
                        title=val_res.title if val_res and val_res.title else cand.meta.get("name", ""),
                        signals=(val_res.signals if val_res else []) + ["verified_by_curated_dataset"],
                        rejection_reason=None,
                    )
            else:
                confidence = 0.98

            logger.info("Tier 1 HIT: Dataset match for '%s' -> %s", query, cand.url)
            return PolicyResult(
                query=query,
                status=ResolutionStatus.FOUND,
                url=cand.url,
                source=SourceType.DATASET,
                confidence=confidence,
                title=val_res.title if val_res else cand.meta.get("name", ""),
                method="curated_dataset",
                entity_name=cand.meta.get("name"),
                domain=cand.meta.get("domain") or domain,
                validation=val_res,
                metadata=cand.meta,
                elapsed_ms=(time.time() - start_time) * 1000,
            )

        # -------------------------------------------------------------
        # TIER 2 & 3: Direct Domain Heuristics & Homepage Crawler
        # -------------------------------------------------------------
        logger.debug("Tier 2/3: Probing heuristics and crawling for '%s'", clean_q)
        domains_to_try: List[str] = []
        if domain:
            domains_to_try.append(domain)
        elif not is_pkg:
            domains_to_try.extend(guess_candidate_domains(clean_q)[:3])

        all_collected_candidates: List[CandidateLink] = []

        for d in domains_to_try:
            # 2a. Heuristic probing (/privacy, /privacy-policy)
            heur_candidates = self.heuristics_resolver.resolve(clean_q, domain=d)
            for c in heur_candidates:
                all_collected_candidates.append(c)
                if self.verify:
                    is_valid, val_res = self.validator.validate_url(c.url, timeout=self.timeout)
                    if is_valid:
                        return self._finish(
                            PolicyResult(
                                query=query,
                                status=ResolutionStatus.FOUND,
                                url=c.url,
                                source=c.source,
                                confidence=val_res.confidence,
                                title=val_res.title,
                                method="heuristics_probe",
                                domain=d,
                                validation=val_res,
                                elapsed_ms=(time.time() - start_time) * 1000,
                            ),
                            query,
                        )
                else:
                    return self._finish(
                        PolicyResult(
                            query=query,
                            status=ResolutionStatus.UNVERIFIED,
                            url=c.url,
                            source=c.source,
                            confidence=c.score,
                            method="heuristics_probe",
                            domain=d,
                            elapsed_ms=(time.time() - start_time) * 1000,
                        ),
                        query,
                    )

            # 2b. Homepage Crawler (crawl <a> tags in landing page)
            crawl_candidates = self.crawler_resolver.resolve(clean_q, domain=d)
            for c in crawl_candidates:
                all_collected_candidates.append(c)
                if self.verify:
                    is_valid, val_res = self.validator.validate_url(c.url, timeout=self.timeout)
                    if is_valid:
                        return self._finish(
                            PolicyResult(
                                query=query,
                                status=ResolutionStatus.FOUND,
                                url=c.url,
                                source=c.source,
                                confidence=val_res.confidence,
                                title=val_res.title,
                                method="homepage_crawler",
                                domain=d,
                                validation=val_res,
                                elapsed_ms=(time.time() - start_time) * 1000,
                            ),
                            query,
                        )
                else:
                    return self._finish(
                        PolicyResult(
                            query=query,
                            status=ResolutionStatus.UNVERIFIED,
                            url=c.url,
                            source=c.source,
                            confidence=c.score,
                            title=c.anchor_text,
                            method="homepage_crawler",
                            domain=d,
                            elapsed_ms=(time.time() - start_time) * 1000,
                        ),
                        query,
                    )

        # -------------------------------------------------------------
        # TIER 4: App Store / Google Play Store Resolver
        # -------------------------------------------------------------
        logger.debug("Tier 4: Checking Google Play Store for '%s'", clean_q)
        play_candidates = self.playstore_resolver.resolve(clean_q, domain=domain)
        for c in play_candidates:
            all_collected_candidates.append(c)
            if self.verify:
                is_valid, val_res = self.validator.validate_url(c.url, timeout=self.timeout)
                if is_valid:
                    return self._finish(
                        PolicyResult(
                            query=query,
                            status=ResolutionStatus.FOUND,
                            url=c.url,
                            source=c.source,
                            confidence=val_res.confidence,
                            title=val_res.title,
                            method="google_play_store",
                            validation=val_res,
                            metadata=c.meta,
                            elapsed_ms=(time.time() - start_time) * 1000,
                        ),
                        query,
                    )
            else:
                return self._finish(
                    PolicyResult(
                        query=query,
                        status=ResolutionStatus.UNVERIFIED,
                        url=c.url,
                        source=c.source,
                        confidence=c.score,
                        method="google_play_store",
                        metadata=c.meta,
                        elapsed_ms=(time.time() - start_time) * 1000,
                    ),
                    query,
                )

        # -------------------------------------------------------------
        # TIER 5: Web Search Engine Fallback
        # -------------------------------------------------------------
        if self.enable_search_fallback:
            logger.debug("Tier 5: Web search fallback for '%s'", clean_q)
            search_candidates = self.search_resolver.resolve(clean_q, domain=domain)
            for c in search_candidates:
                all_collected_candidates.append(c)
                if self.verify:
                    is_valid, val_res = self.validator.validate_url(c.url, timeout=self.timeout)
                    if is_valid:
                        return self._finish(
                            PolicyResult(
                                query=query,
                                status=ResolutionStatus.FOUND,
                                url=c.url,
                                source=c.source,
                                confidence=val_res.confidence,
                                title=val_res.title,
                                method="web_search_fallback",
                                validation=val_res,
                                elapsed_ms=(time.time() - start_time) * 1000,
                            ),
                            query,
                        )
                else:
                    return self._finish(
                        PolicyResult(
                            query=query,
                            status=ResolutionStatus.UNVERIFIED,
                            url=c.url,
                            source=c.source,
                            confidence=c.score,
                            title=c.anchor_text,
                            method="web_search_fallback",
                            elapsed_ms=(time.time() - start_time) * 1000,
                        ),
                        query,
                    )

        # -------------------------------------------------------------
        # PROBABLE / UNVERIFIED FALLBACK
        # -------------------------------------------------------------
        if all_collected_candidates:
            best_cand = max(all_collected_candidates, key=lambda x: x.score)
            other_links = [c.url for c in all_collected_candidates if c.url != best_cand.url]
            return PolicyResult(
                query=query,
                status=ResolutionStatus.PROBABLE,
                url=best_cand.url,
                source=best_cand.source,
                confidence=min(0.65, best_cand.score),
                title=best_cand.anchor_text,
                method=f"unverified_candidate_{best_cand.source.value.lower()}",
                alternate_links=other_links[:5],
                elapsed_ms=(time.time() - start_time) * 1000,
            )

        logger.info("All tiers exhausted for '%s', returning NOT_FOUND", query)
        return PolicyResult(
            query=query,
            status=ResolutionStatus.NOT_FOUND,
            method="exhausted_all_tiers",
            elapsed_ms=(time.time() - start_time) * 1000,
        )

    def find_batch(self, queries: List[str]) -> List[PolicyResult]:
        """Process multiple queries in sequence."""
        logger.info("Starting batch resolution for %d queries", len(queries))
        return [self.find(q) for q in queries]
