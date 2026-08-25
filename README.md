# akash-github-runner

Conformance rules and shared lifecycle for **GitHub Actions runners on Akash**.

Split out of `Digital-Frontier-LDA/df-cicd` for one measured reason: **df-cicd is `internal`, and a
`public` repository cannot call a reusable workflow from a private or internal one.** GitHub refuses
the pairing before any job is created, so the call fails with `conclusion=failure`, **`jobs: 0`**,
no annotation and no log.

## The evidence for the split

`reusable-akash-runner-conformance.yml` had **8 runs, 8 failures, all `jobs=0`** from
`Digital-Frontier-LDA/just-akash`. Everything a reviewer would check was correct — pinned SHA
resolves, callee declares `workflow_call`, inputs match, same organisation,
`access_level="organization"` set. The broken property is the **pairing** of caller and callee
visibility, which nothing reports.

A natural control settles it. Same callee, same org, same access level — only the *consumer's*
visibility differs:

| consumer | visibility | result |
|---|---|---|
| `Digital-Frontier-LDA/infra-dns` | **internal** | **GREEN** — run `31657702638`, `jobs=1` |
| `Digital-Frontier-LDA/just-akash` | **public** | **NEVER-GREEN** — 8 runs, `jobs=0` |

⇒ The transport is healthy. `jobs=0` is GitHub refusing one specific pairing.

Two of the four intended consumers (`Borduas-Holdings/Blazing-Back`, `Borduas-Holdings/blazing`)
are in a **different organisation**, where an internal repo's reusables are not shareable at any
access level. So a consumer-side fix cannot cover more than half the problem — the callee has to be
reachable, which is what this repo is for.

## What lives here

### ⚠ Routing: this repo is the canonical home of the CHECKER

The **standard's text** lives in `df-cicd/standards/AKASH-RUNNER-CI.md`. The **rules that
enforce it** — `akash_runner/check_*.py` — live here, and df-cicd consumes them through
`.github/workflows/runner-conformance.yml`.

**A new rule goes here.** df-cicd#177 deleted that repo's entire `akash_runner/` suite when it
adopted this reusable, so a rule added to df-cicd is removed by the next consolidation — with
its own tests still green in the deleted copy, which is what makes it silent.

⚠ Measured 2026-08-25: df-cicd#170's eight files are ABSENT from df-cicd `main` and PRESENT
here, the rule is invoked at `.github/actions/akash-runner-conformance/action.yml`, and its
call-site guard travelled with it. That pattern reads exactly like merged-then-silently-deleted
and is not: **the value travelled; only the address changed.** Check which repo before
concluding either.


```
akash_runner/     14 conformance rules + 23 test modules + workflow_corpus.py
baseline/         check_conformance.py — shared Finding/RuleResult types (leaf dependency)
.github/actions/akash-runner-conformance/   the composite action
.github/workflows/reusable-akash-runner-conformance.yml
.github/workflows/reusable-stale-runner-reaper.yml
```

The rules are plain Python and can also be consumed as a package, independent of workflow
visibility entirely — the same distribution shape `akash-lease-core` already uses successfully
across orgs and visibilities.

## What the rules assert

Each rule is structural: it reads workflow YAML and rejects a shape, with a known-positive and a
known-negative behind it. Highlights:

- `check_teardown_cannot_be_silenced.py` — a billable close must not be `|| true`-swallowed
- `check_teardown_can_identify.py` — teardown must receive an identifier it can actually close
- `check_pool_owns_teardown.py` — the pool, not each consumer, owns teardown
- `check_dereg_backstop.py` — a deregistration backstop must exist and declare a cadence
- `check_reaper_schedule.py` — a backstop reaper declares a schedule, or declares why it does not

⚠ **A known gap, tracked upstream:** these assert a backstop *exists and runs*. Nothing yet asserts
it **keeps up**. A measured case: a reaper reporting `Reaped 254` while 245 matching registrations
returned within 54 minutes is fully conformant and losing. Outcome (residual) is the missing
signal; cadence is only an input.

## Consumers

See `CONSUMERS.md`. A reusable with no consumers must still appear there, saying so — an untested
standard that admits it is untested is better than one implying adoption it does not have.
