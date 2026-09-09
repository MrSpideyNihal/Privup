# PrivUp architecture

Everything runs on the device. The only outbound request in the whole
pipeline happens inside a driver's `fetch()`.

```
target ──▶ driver.fetch() ──▶ summarizer.clean() ──▶ analyzer.classify() ──▶ scorer.score() ──▶ Verdict
           DriverResult        list[Clause]          list[Finding]           Verdict
```

`core/main.py` wires those four together and does nothing else:

```python
from core.main import run

verdict = run("raw_text", policy_text, "loan_app")
print(verdict.decision.value)   # allow | warning | deny
for reason in verdict.reasons:
    print("-", reason)
```

Stages communicate only through the four schemas in `core/models/`. No stage
imports another stage. That is what makes a driver or a rule set pluggable,
and it is worth preserving.

## The four schemas

| Type | Produced by | Carries |
|---|---|---|
| `DriverResult` | `core/scraper` | raw text, origin, content type, fetch metadata |
| `Clause` | `core/summarizer` | one sentence, its heading, its offsets |
| `Finding` | `core/analyzer` | which rule fired, on which clause, why, how bad |
| `Verdict` | `core/scorer` | Allow/Warning/Deny, one plain reason per finding |

A `Finding` embeds its `Clause` rather than referencing it by id, so it is
self-contained: any front end can show the evidence without being handed the
clause list too.

All four are frozen and round-trip through `to_dict()`/`from_dict()` using
only the standard library.

## Adding a driver

A driver answers one question: where does the text come from? It decides
nothing about what the text means.

```python
from core.models import DriverResult
from core.scraper.base import Driver, DriverError
from core.scraper.registry import register_driver


@register_driver
class PlayStoreDriver(Driver):
    name = "play_store"                      # the CLI value, must be unique
    default_content_type = "text/plain"
    description = "Read policy metadata from a Play Store listing."

    def fetch(self, target: str) -> DriverResult:
        text = ...                            # network calls belong here, only here
        if not text.strip():
            raise DriverError(f"no policy text at {target}")
        return self.build_result(text, origin=target)
```

Rules for a well-behaved driver:

- **Raise, do not return empty.** A `DriverResult` with no text makes the
  scorer report Warning; returning one to signal failure hides a real error
  behind a vague verdict. Raise `DriverError` instead.
- **Set `content_type` honestly.** It is how the summarizer decides whether
  to strip HTML.
- **Put anything driver-specific in `metadata`.** No downstream stage may
  depend on a particular key existing.

Nothing in `core/analyzer`, `core/scorer` or `core/main.py` changes.

A driver shipped in a separate package registers itself without touching this
repo at all:

```toml
[project.entry-points."privup.drivers"]
play_store = "your_package.play_store_driver"
```

## Adding a rule set

Drop a JSON file into `core/tags/rulesets/`. It is discovered by globbing that
directory, so there is no list to extend and no analyzer code to edit.

```json
{
  "name": "my_rules",
  "description": "What this rule set is for.",
  "reference": "The regulation or standard it encodes.",
  "rules": [
    {
      "id": "my.rule.id",
      "category": "data_retention",
      "severity": "high",
      "reason": "One plain-language line the user reads.",
      "reference": "GDPR Art. 5(1)(e)",
      "note": "Why this rule exists. Required if there is no reference.",
      "patterns": ["\\bindefinitely\\b"],
      "requires": ["\\bretain\\w*\\b"],
      "negations": ["\\bdo not retain\\b"],
      "hedges": ["\\bgenerally\\b"],
      "hedge_severity": "medium",
      "hedge_reason": "A softer line for a softer promise.",
      "numeric": {"kind": "percent_annual", "operator": ">=", "threshold": 24.0},
      "scope": "clause"
    }
  ]
}
```

A clause fires a rule when it matches **any** `patterns` entry, **every**
`requires` entry, the `numeric` check if present, and **no** `negations`
entry. If it also matches a `hedges` entry, the finding is still produced but
at `hedge_severity` with `hedge_reason`.

### Why negations and hedges exist

They are not defensive extras. They are the difference between a useful tool
and a noisy one, and real policies are what forced them.

Kissht's live privacy policy says:

> We also do **not** access your mobile phone resources such as contact list,
> call logs, telephony Functions, etc.

A keyword rule on "contact list" flags a lender that is compliant on exactly
the point it is being flagged for. That is what `negations` prevents.

LazyPay's says:

> we **ideally restrain** from accessing mobile phone resources like file and
> media, contact list, call logs

That is neither a denial nor an admission. Suppressing it hides something a
borrower should know; reporting it at full severity overstates the case. That
is what `hedges` are for.

### Numeric checks

`numeric` extracts a figure and normalises it to a yearly rate before
comparing. Kinds: `percent_annual`, `percent_daily`, `percent_monthly`,
`percent_any`.

This exists because the worst term in a loan is usually a number quoted over
a short period. A real schedule of charges reads:

> Daily charges of up to **0.2%** of the overdue principal amount

which is about **73% a year**, against the 36% p.a. the same document quotes
for the loan itself. No keyword rule notices that.

### Document-scoped rules

`"scope": "document_absent"` inverts a rule: it fires once, for the whole
document, when **no** clause matches any of its patterns. Use it for red flags
that are about silence, such as a policy that never says how to withdraw
consent.

Absence rules do not run on an empty document. "This policy never mentions X"
is a claim about a policy, and there has to be one.

## Shipped rule sets

| Name | Covers |
|---|---|
| `generic` | GDPR-pattern red flags: retention, third-party sharing, tracking and profiling, training on user content, absent opt-out |
| `loan_app` | RBI Digital Lending Directions 2025: phone permissions outside the camera/microphone/location carve-out, cost of credit, recovery practice, absent disclosures |

```bash
python core/main.py --list-tags
python core/main.py --list-drivers
```

## Scoring

- no findings → **Allow**
- any `critical` finding → **Deny**
- anything else → **Warning**

Nothing accumulates into a Deny. Severities are set by rule authors, and
escalating on volume would let a rule set with many weak rules out-vote one
with few precise ones.

A document that produced no clauses returns **Warning**, never Allow. Several
live lending sites render their policy entirely in JavaScript and return an
empty shell to a plain fetch; a confident green light for a page nobody read
would be the worst failure this project could have.

`risk_score` (0–100) is for sorting and for showing change over time. It is
not the verdict.

## Test fixtures

Fixtures in `tests/fixtures/` are real excerpts from live pages, with
provenance headers, never invented text. That rule has already paid for
itself: invented policy text would have been uniformly incriminating, and the
first version of the analyzer would have looked excellent while being useless
on anything real.

```python
from tests.fixtures import load_text, provenance

text = load_text("loan_charges_kissht_tou.txt")   # header stripped
provenance("loan_charges_kissht_tou.txt")          # source URL, retrieval date
```

## Constraints for this phase

- Rule-based only. No ML classification yet.
- No network calls anywhere except inside a driver's `fetch()`.
- Each module imports from `core/models/` and its own peers only.
- New dependencies must be MIT or Apache 2.0. There are currently none.
