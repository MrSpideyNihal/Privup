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

"""Dataset manager for curated privacy policy records."""

import difflib
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger("privacy_url_finder")


class DatasetManager:
    """Manages the catalog of known entities, domains, and privacy URLs."""

    def __init__(self, data_path: Optional[str] = None):
        if data_path is None:
            dir_path = os.path.dirname(os.path.abspath(__file__))
            data_path = os.path.join(dir_path, "policies.json")
        self.data_path = data_path
        self.entries: List[Dict[str, Any]] = []
        self._name_index: Dict[str, Dict[str, Any]] = {}
        self._alias_index: Dict[str, Dict[str, Any]] = {}
        self._domain_index: Dict[str, Dict[str, Any]] = {}
        self._all_lookup_keys: List[str] = []
        self.load()

    def load(self) -> None:
        """Load and index entries from policies.json."""
        if not os.path.exists(self.data_path):
            self.entries = []
            return

        with open(self.data_path, "r", encoding="utf-8") as f:
            self.entries = json.load(f)

        self._build_indices()

    def _normalize(self, text: str) -> str:
        """Normalize key for lookup: lowercase, strip punctuation and whitespace."""
        return re.sub(r"[^a-zA-Z0-9]", "", text).lower()

    def _build_indices(self) -> None:
        self._name_index.clear()
        self._alias_index.clear()
        self._domain_index.clear()
        self._all_lookup_keys.clear()

        for entry in self.entries:
            # Index by primary name and id
            norm_name = self._normalize(entry["name"])
            self._name_index[norm_name] = entry
            self._all_lookup_keys.append(norm_name)

            if "id" in entry:
                norm_id = self._normalize(entry["id"])
                self._name_index[norm_id] = entry
                self._all_lookup_keys.append(norm_id)

            # Index by domain
            if "domain" in entry and entry["domain"]:
                dom = entry["domain"].lower().strip()
                self._domain_index[dom] = entry
                # also without www
                if dom.startswith("www."):
                    self._domain_index[dom[4:]] = entry

            # Index by aliases
            for alias in entry.get("aliases", []):
                norm_alias = self._normalize(alias)
                self._alias_index[norm_alias] = entry
                self._all_lookup_keys.append(norm_alias)

        self._all_lookup_keys = list(set(self._all_lookup_keys))

    def lookup(self, query: str, fuzzy: bool = True, cutoff: float = 0.8) -> Optional[Dict[str, Any]]:
        """
        Find an entry by name, alias, domain, or fuzzy match.
        Returns the matching entry dict or None.
        """
        if not query:
            return None

        # 1. Check if query is domain
        clean_q = query.strip().lower()
        if clean_q.startswith("https://") or clean_q.startswith("http://"):
            from ..utils import extract_domain
            clean_q = extract_domain(clean_q)

        if clean_q in self._domain_index:
            return self._domain_index[clean_q]
        if clean_q.startswith("www.") and clean_q[4:] in self._domain_index:
            return self._domain_index[clean_q[4:]]

        # 2. Check normalized name / ID
        norm = self._normalize(query)
        if norm in self._name_index:
            return self._name_index[norm]

        # 3. Check alias index
        if norm in self._alias_index:
            return self._alias_index[norm]

        # 4. Partial substring match in names (with tightened overlap requirement)
        if norm and len(norm) >= 4:
            for k, entry in self._name_index.items():
                if norm in k or k in norm:
                    # Require ≥80% overlap to prevent false positives
                    # (e.g., "cred" matching "credential")
                    shorter, longer = (norm, k) if len(norm) <= len(k) else (k, norm)
                    if len(shorter) / len(longer) >= 0.8:
                        return entry

        # 5. Fuzzy match against all keys
        if fuzzy and norm:
            matches = difflib.get_close_matches(norm, self._all_lookup_keys, n=1, cutoff=cutoff)
            if matches:
                best_match = matches[0]
                if best_match in self._name_index:
                    return self._name_index[best_match]
                if best_match in self._alias_index:
                    return self._alias_index[best_match]

        return None

    def search(self, term: str) -> List[Dict[str, Any]]:
        """Search all entries containing term in name, category, or aliases."""
        term_clean = term.lower().strip()
        results = []
        for entry in self.entries:
            if (
                term_clean in entry["name"].lower()
                or term_clean in entry.get("domain", "").lower()
                or term_clean in entry.get("category", "").lower()
                or any(term_clean in a.lower() for a in entry.get("aliases", []))
            ):
                results.append(entry)
        return results

    def add_entry(self, entry: Dict[str, Any]) -> None:
        """Add a new entry to the in-memory dataset and rebuild indices."""
        self.entries.append(entry)
        self._build_indices()

    def save_entry(self, entry: Dict[str, Any], persist: bool = True) -> bool:
        """
        Add a verified entry to the dataset and optionally persist it to disk.
        Avoids duplicates by checking domain and normalized name.
        Returns True if a new entry was added and saved, False if already exists.
        """
        if not entry or not entry.get("privacy_url"):
            return False

        # Check for existing entry by domain or name
        domain = entry.get("domain", "").lower().strip()
        norm_name = self._normalize(entry.get("name", ""))

        if domain and domain in self._domain_index:
            existing = self._domain_index[domain]
            # Update privacy url if existing was empty
            if not existing.get("privacy_url"):
                existing["privacy_url"] = entry["privacy_url"]
                if persist:
                    self._persist()
            return False

        if norm_name and norm_name in self._name_index:
            return False

        # Generate id if missing
        if "id" not in entry or not entry["id"]:
            entry["id"] = norm_name or re.sub(r"[^a-zA-Z0-9]", "", domain)

        self.entries.append(entry)
        self._build_indices()

        if persist:
            self._persist()
        return True

    def _persist(self) -> None:
        """Write current entries back to policies.json on disk."""
        try:
            temp_path = f"{self.data_path}.tmp"
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(self.entries, f, indent=2, ensure_ascii=False)
            # Atomic replace
            os.replace(temp_path, self.data_path)
        except Exception as e:
            # In-memory copy remains valid, but log the failure so it's not invisible
            logger.warning("Failed to persist dataset to %s: %s", self.data_path, e)
