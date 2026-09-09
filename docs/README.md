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

Both front ends call exactly that function. The CLI in `cli/` chooses an
output format and an exit status; the UI in `ui/` renders the same `Verdict`
as HTML. Neither contains pipeline logic, and both have a test asserting they
report precisely what `core` decided. If those tests ever fail, a front end
has grown an opinion it is not entitled to.

## Running it

```bash
python -m cli scan "We access your contact list." --tags loan_app
python -m cli scan https://example.com --driver url --tags generic --format json
cat policy.txt | python -m cli scan - --tags generic
python -m cli --list-tags

python -m ui          # http://127.0.0.1:8420
```

CLI exit status, so a script can branch on it:

| Status | Meaning |
|---|---|
| 0 | allow, or warning |
| 1 | deny |
| 2 | bad usage |
| 3 | could not complete the check |

Deny and "could not check" are deliberately different. A build failing because
a policy is bad and one failing because a URL 404'd need different responses.

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

### The contract

`fetch(target) -> DriverResult` is the whole interface.

| Field | Required | Meaning |
|---|---|---|
| `raw_text` | yes | The document, as text. Never bytes, never `None`. |
| `origin` | yes | Where it came from, shown to the user. A URL, a package name, `"raw_text"`. |
| `driver` | set by `build_result` | The registry name, so a verdict can say how it was obtained. |
| `content_type` | defaults | `text/plain` or `text/html`. Decides whether the summarizer strips markup. |
| `fetched_at` | defaults | Timezone-aware UTC. |
| `metadata` | no | Anything driver-specific. |

Rules for a well-behaved driver:

- **Raise, do not return empty.** A `DriverResult` with no text makes the
  scorer report Warning; returning one to signal failure hides a real error
  behind a vague verdict. Raise `DriverError` instead.
- **Set `content_type` honestly.** Guessing wrong means either HTML tags
  reach the analyzer, or prose gets run through an HTML stripper.
- **Put anything driver-specific in `metadata`.** No downstream stage may
  depend on a particular key existing, so a driver can record whatever is
  useful without coupling anything to it.
- **The network belongs to you and only you.** No other module in PrivUp may
  open a socket. If a driver needs a cached dataset instead, ship the cache.
- **Be deterministic given the same input.** The analyzer and scorer are, and
  a reproducible verdict is worth more than a clever one.

Nothing in `core/analyzer`, `core/scorer` or `core/main.py` changes.

### A worked example

A driver that reads an installed Android app's declared permissions, which is
the Part 3 Android path. It shows the interface holding up for a source that
is not a web page at all:

```python
@register_driver
class InstalledAppDriver(Driver):
    name = "installed_app"
    default_content_type = "text/plain"
    description = "Read declared permissions from an installed package."

    # Maps a permission to the sentence a rule set already knows how to read,
    # so no new rule is needed to cover this source.
    SENTENCES = {
        "android.permission.READ_CONTACTS": "This app accesses your contact list.",
        "android.permission.READ_CALL_LOG": "This app accesses your call logs.",
        "android.permission.READ_SMS": "This app reads your SMS messages.",
    }

    def fetch(self, target: str) -> DriverResult:
        permissions = read_manifest(target)          # your platform call
        if not permissions:
            raise DriverError(f"no declared permissions for {target}")

        lines = [self.SENTENCES.get(p, f"This app requests {p}.") for p in permissions]
        return self.build_result(
            "Declared permissions\n" + "\n".join(lines),
            origin=target,
            metadata={"package": target, "permissions": permissions},
        )
```

The `loan_app` rule set then flags `READ_CONTACTS` as critical with its RBI
citation, with no change to the rule set, the analyzer or the scorer. That is
what pluggable is supposed to mean.

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

### Rule fields

| Field | Required | What it does |
|---|---|---|
| `id` | yes | Unique within the set. Appears in output, so treat it as public. |
| `category` | yes | Groups findings. Free text; reuse an existing one where it fits. |
| `severity` | yes | `info` / `low` / `medium` / `high` / `critical`. Only `critical` denies. |
| `reason` | yes | The one line the user reads. Write it for someone at a permission dialog. |
| `patterns` | yes | Any one matching fires the rule. Case-insensitive regex. |
| `requires` | no | All must also match. Gates a broad pattern. |
| `negations` | no | Any one suppresses the match entirely. |
| `hedges` | no | Any one downgrades instead of suppressing. Needs `hedge_severity` and `hedge_reason`. |
| `numeric` | no | Extract a figure and compare it to a threshold. |
| `scope` | no | `clause` (default) or `document_absent`. |
| `reference` | no | The regulation this encodes. Shown to the user. |
| `note` | no | Why the rule exists. Required if there is no `reference`. |
| `confidence` | no | Defaults to 1.0. Exists so the later ML phase needs no schema change. |

Placeholders `{matched}`, `{value}` and `{annualised}` are substituted into
`reason`. An unknown placeholder is left visible rather than raising, so a
rule author's typo does not crash in front of a user.

### How the analyzer consumes a rule

In this order, and the order matters:

1. **`patterns`** — any one must hit, or the rule is done.
2. **`requires`** — every one must also hit.
3. **`numeric`** — if present, must extract a figure and trip the threshold.
4. **`negations`** — any one hit drops the match entirely.
5. **`hedges`** — any one hit keeps the finding, at `hedge_severity`.

Negation is checked before hedging on purpose: an outright denial beats a soft
one. `"We generally do not access your contact list"` is a denial, not a hedge.

### How the scorer consumes a finding

Only `severity` and `confidence`. It never re-reads the clause. The verdict is
Deny if any finding is `critical`, Allow if there are none at all, Warning
otherwise, and `risk_score` is a weighted sum capped at 100.

This means the single highest-leverage decision a rule author makes is the
severity. Marking something `critical` denies the document.

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

### Declaring what a rule set is for

A rule set may declare the vocabulary it expects to see. If too little of it
turns up, the verdict carries a notice.

```json
"metadata": {
  "relevance": {
    "min_signals": 3,
    "notice": "This does not look like a lending app, so these rules may not apply well here.",
    "signals": ["loan", "borrower", "repayment", "rate of interest", "creditworthiness"]
  }
}
```

This warns, it never blocks. Running any rule set against any target stays
allowed, because someone testing an edge case or covering an app that fits no
category is doing something legitimate, and a tool that forbids that gets
forked. But `loan_app` against a messaging app reports critical findings for
contacts and message access, which is right for a lender and wrong for a
messenger, and a user who picked the wrong dropdown entry would be told
something untrue in the tool's most emphatic voice.

So the findings are still produced, still scored, still shown, and the notice
sits alongside them. It appears in `Verdict.metadata["relevance"]`, as a
`Note:` line in the CLI and as a banner above the findings in the UI.

The check is skipped for documents under `min_words` (120 by default), because
a one-sentence paste has too little vocabulary to judge and a false notice
trains people to ignore the real ones.

Count distinct phrases, not occurrences, so one repeated word cannot carry the
decision. Choose phrases that are specific: bare `interest` and bare `credit`
are deliberately absent from `loan_app`, because "legitimate interest",
"interest-based advertising" and "credit card" appear in ordinary privacy
policies and would make the notice useless. A rule set that declares no
`relevance` block always applies, which is correct for `generic`.

## Shipped rule sets

| Name | Covers |
|---|---|
| `generic` | GDPR-pattern red flags: retention, third-party sharing, tracking and profiling, training on user content, absent opt-out |
| `loan_app` | RBI Digital Lending Directions 2025: phone permissions outside the camera/microphone/location carve-out, cost of credit, recovery practice, absent disclosures |

```bash
python -m cli --list-tags
python -m cli --list-drivers
```

## The local UI

```bash
python -m ui
```

Serves `http://127.0.0.1:8420` from `ui/static/`: one input box, one rule-set
selector populated from the same registry `--list-tags` reads, one button. The
result is a verdict badge, a risk dial, severity counts, and one expandable
row per finding. Collapsed shows the reason; expanded shows the clause that
triggered it with the matched phrase highlighted, plus the citation.

It is local in more than intent. The server binds loopback, refuses any
request whose `Host` header is not loopback so a page on the open internet
cannot drive it, sends no CORS headers, and `--host 0.0.0.0` is refused
outright. The static files reference no webfont and no CDN, which a test
enforces: a font request would be the only thing on the page talking to the
internet.

There is no history, no storage and no accounts. Nothing you paste is written
anywhere.

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
