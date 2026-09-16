"""Build labels.json from a candidate pool of real policy clauses.

Kept in the repo so the labelled set is reproducible and reviewable rather
than appearing from nowhere. Run it only when adding clauses; the committed
labels.json is the artefact everything else reads.
"""

from __future__ import annotations

import json
import pathlib
import sys

HERE = pathlib.Path(__file__).parent

# index in the pool -> categories a careful reader would want flagged.
# An empty list is a negative example and carries as much weight as a
# positive one: precision is measured on these.
LABELS: dict[int, list[str]] = {
    1: [], 3: [], 4: [], 5: [], 10: [], 11: [], 12: [], 13: [], 18: [], 19: [],
    20: [], 21: [], 23: [], 24: [], 26: [], 33: [], 34: [], 38: [], 39: [],
    41: [], 46: [], 48: [], 49: [], 50: [], 52: [], 53: [], 57: [], 58: [],
    65: [], 67: [], 68: [], 73: [], 75: [], 76: [], 77: [], 78: [], 79: [],
    81: [], 83: [], 86: [], 87: [], 89: [], 90: [], 92: [], 94: [], 95: [],
    97: [], 98: [],

    # Negatives that specifically trap a pattern matcher.
    16: [],   # "add a profile picture" is not profiling
    27: [],   # "Profile Name And Picture" is not profiling
    80: [],   # same
    29: [],   # "We don't show you personalized ads based on sensitive categories"
    96: [],   # "We don't show you personalized ads based on your content"
    42: [],   # "We don't share information that personally identifies you"
    35: [],   # "do not provide access to emergency service providers"
    25: [],   # "storage" in a security-measures sentence
    55: [],   # "storage" in a security-measures sentence
    59: [],   # "storage" inside a definition of "Processing"
    69: [],   # telling a user how to revoke camera permission is a protection
    47: [],   # functional cookies
    15: [],   # requiring partners to have lawful rights is a protection

    # Positives.
    2: ["disallowed_permission"],
    56: ["disallowed_permission"],
    6: ["consent"],
    72: ["consent"],
    7: ["data_retention"],
    44: ["data_retention"],
    84: ["data_retention"],
    99: ["data_retention"],
    36: ["data_retention", "model_training"],
    8: ["model_training"],
    32: ["model_training"],
    43: ["model_training"],
    9: ["third_party_sharing"],
    17: ["third_party_sharing", "tracking_profiling"],
    31: ["third_party_sharing"],
    40: ["third_party_sharing"],
    45: ["third_party_sharing"],
    51: ["third_party_sharing"],
    61: ["third_party_sharing"],
    62: ["third_party_sharing"],
    64: ["third_party_sharing"],
    66: ["third_party_sharing"],
    74: ["third_party_sharing"],
    91: ["third_party_sharing"],
    93: ["third_party_sharing"],
    22: ["tracking_profiling"],
    28: ["tracking_profiling"],
    30: ["tracking_profiling"],
    37: ["tracking_profiling"],
    63: ["tracking_profiling"],
    71: ["tracking_profiling"],
    82: ["cross_border_transfer"],
    60: ["cost_of_credit"],
    85: ["cost_of_credit"],
    88: ["cost_of_credit"],
}

HEADER = {
    "review_status": "UNREVIEWED BOOTSTRAP - NOT AUTHORITATIVE",
    "warning": (
        "These labels were produced while building the classifier they are used to "
        "evaluate. Ground truth written by the system under test is circular, so "
        "treat every number derived from this file as provisional until a human has "
        "read the clauses and corrected the labels. Disagreements are expected and "
        "are the point: correct the label, do not tune the rule to match it."
    ),
    "method": (
        "Clauses were sampled from live policy pages, stratified so that roughly a "
        "third were already flagged by the rule matcher and the rest were not. "
        "Including clauses the rules miss is deliberate: a set built only from what "
        "we already catch measures nothing."
    ),
    "vocabulary": (
        "Categories are those defined by the shipped rule sets. A clause about "
        "something no rule set has a category for is left unlabelled rather than "
        "invented, so the metric measures classification rather than coverage."
    ),
    "scope": (
        "Clause-level only. Document-scope rules such as 'this policy never "
        "mentions opting out' are a different mechanism and are excluded."
    ),
}


def main() -> int:
    pool_path = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".git/pool.json")
    if not pool_path.exists():
        print(f"pool not found: {pool_path}", file=sys.stderr)
        return 1

    pool = json.loads(pool_path.read_text(encoding="utf-8"))
    clauses = []
    for index, categories in sorted(LABELS.items()):
        entry = pool[index]
        clauses.append({
            "id": f"c{index:03d}",
            "source": entry["src"],
            "retrieved": "2026-09-09",
            "rule_set": entry["ts"],
            "text": entry["txt"],
            "labels": categories,
        })

    payload = {"meta": HEADER, "clauses": clauses}
    out = HERE / "labels.json"
    out.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")

    positives = sum(1 for c in clauses if c["labels"])
    print(f"wrote {out} with {len(clauses)} clauses ({positives} positive, {len(clauses)-positives} negative)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
