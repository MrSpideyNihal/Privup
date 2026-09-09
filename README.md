# PrivUp

An on-device privacy policy intelligence engine.

When you hit a consent banner or a permission request, PrivUp retrieves the
relevant policy, analyzes it entirely on your device, and gives you a plain
**Allow / Warning / Deny** with one readable line per problem, before you
accept anything.

Nothing leaves the device. The only network request in the whole pipeline
happens inside a driver's `fetch()`.

## Why

A specific case this is built for: predatory digital lending apps in India.
They routinely ask for contacts, call logs and file access that RBI's Digital
Lending Directions 2025 do not permit a regulated lender to request, and they
quote the costs that matter in a form designed not to be read.

From a real lender's published schedule of charges:

> Daily charges of up to **0.2%** of the overdue principal amount

That is roughly **73% a year**, against the 36% p.a. the same document quotes
for the loan itself. PrivUp reports it as a yearly figure, because that is the
number a borrower is actually agreeing to.

## Status

Part 1 is complete: the core pipeline runs end to end on both drivers and both
rule sets. A CLI and a local UI are next.

```bash
python core/main.py "We access your contact list to assess creditworthiness." --tags loan_app
```

```
DENY  (raw_text)
risk 76/100 from 3 finding(s) across 1 clause(s), rule set 'loan_app'
  - This lender says it reads your phone contacts. RBI does not permit lending apps to access your contact list.
  - This policy never explains how to withdraw your consent or have your data deleted. RBI requires a lender to offer both.
  - This app never names the regulated bank or NBFC actually lending the money. You are entitled to know who your lender is.
```

Also works on a URL, and follows a policy link if you give it a homepage:

```bash
python core/main.py https://example.com --driver url --tags generic --format json
```

Exit status is non-zero on Deny, so it is usable from a script.

## How it works

```
target ──▶ driver.fetch() ──▶ summarizer.clean() ──▶ analyzer.classify() ──▶ scorer.score() ──▶ Verdict
```

Drivers and rule sets are pluggable. Adding a rule set means adding a JSON
file to `core/tags/rulesets/`; adding a driver means writing one class. Neither
requires changing the analyzer, the scorer, or `main.py`.

Rule-based only in this phase, no ML. Standard library only, no runtime
dependencies.

See [docs/README.md](docs/README.md) for the architecture, the driver
contract, and how to write a rule set.

## Tests

```bash
python -m pytest
```

Fixtures are real excerpts from live policy pages, never invented text. That
rule matters more than it sounds: made-up policy text is uniformly
incriminating, and real policies are full of sentences like *"we do **not**
access your contact list"* and *"we **ideally restrain** from accessing"* that
a naive keyword matcher gets exactly backwards.

## Contributing

Raise an issue first and close it with the PR. See
[Agents&Contributors.md](Agents&Contributors.md).
