# Consumers

⛔ **Why this file exists.** A standard that has never been consumed has never been tested. This
registry makes the difference between *shipped* and *running* impossible to skip, and every
`reusable-*.yml` in this repo must appear here — **even to say it has no consumers**.

⚠ `GREEN` requires a **run id**. "The file exists", "the pin resolves", "the tests pass",
"the contract matches" and "access is configured" were all simultaneously true of the conformance
reusable while it had **never once executed**. None of them is evidence of a run.

| status | meaning |
|---|---|
| `GREEN` | a run of this reusable, invoked from the named consumer, completed successfully — run id recorded |
| `NEVER-GREEN` | a consumer exists and calls it, but no successful run has ever been observed |
| `NONE` | no consumer calls it |
| `UNVERIFIED` | not yet enumerated |

⚠ A row of `NONE` **passes** deliberately. An untested standard that admits it is untested is far
better than one that implies adoption it does not have.

| reusable | consumer | status | evidence |
|---|---|---|---|
| `reusable-akash-runner-conformance.yml` | `Digital-Frontier-LDA/just-akash` → `.github/workflows/runner-conformance.yml` | `NEVER-GREEN` | 8 runs, 8 failures, all `jobs=0`. Root cause measured: a **public** repo cannot call a reusable from a **private/internal** one. This repo exists to remove that blocker. See "Why this repo exists" in the README. |

| `reusable-stale-runner-reaper.yml` | — | `NONE` | `workflow_call`-only. No consumer calls it from this repo yet; it moved here with the conformance reusable because it is the same domain. A row of `NONE` is the honest state, not a placeholder. |

## Why the status above is not a defect in this code

The transport is healthy and there is a known-positive proving it: `df-cicd`'s
`reusable-checkov.yml`, invoked from the **internal** repo `Digital-Frontier-LDA/infra-dns`, is
`GREEN` (run `31657702638`, `jobs=1`). Same callee visibility, same organisation, same access
level — the only variable that differs is the **consumer's** visibility:

| consumer | visibility | result |
|---|---|---|
| `infra-dns` | internal | **GREEN** (`jobs=1`) |
| `just-akash` | public | **NEVER-GREEN** (`jobs=0`) |

⇒ `jobs=0` is GitHub refusing one specific pairing, not this repository failing. Publishing this
repo is what changes the row above, and the row must not be edited to `GREEN` until a run id
exists for it.

## ⛔ The repos this standard is ABOUT do not consume it

`check_backstop_covers_producers.py` is **ENFORCING**, and its docstring already records — measured
**2026-08-24** — that `blazing` emits `akash-ci-` and `akash-` with no backstop, and that
`Blazing-Back`'s `runner-time-to-ready.yml` emits `akash-` with no backstop.

It was right. Measured again **2026-08-25 10:01Z**, org runner listing streamed and counted once:

⚠ **That table is now stale, and I first mis-read it.** Re-measured **2026-08-25** by running
the rule against each repo's `origin/main`:

| repo | `check_backstop_covers_producers` | why |
|---|---|---|
| `Borduas-Holdings/Blazing-Back` | **PASS** (exit 0, 56 files) | `runner-time-to-ready.yml` fixed same-day in `ab615607b` (#1480) |
| `Borduas-Holdings/blazing` | **PASS** (exit 0, 21 files) | producers renamed `df-flow-*`; reaper allowlists six prefixes incl. both pool prefixes |

⛔ My first run reported blazing as FAIL with 2 findings. That run was against a **stale local
feature branch**, not `main` — the reaper script and both producer workflows differ between them.
The rule was right both times; I pointed it at the wrong tree. Recorded because reading content
off whatever ref happens to be checked out is the same defect this repo's rules exist to catch.

⇒ **So the coverage defect this rule named on 2026-08-24 has since been fixed in both repos.**
The rule worked. What follows is about a different gap.

⚠ And `PASS` here means **every emitted prefix is claimable — not that nothing leaks.** At the
2026-08-25 10:01Z sample, `blazing` still held 167 offline registrations under prefixes its reaper
*does* cover: a production-rate problem (a pool re-registers on every container restart, so
orphans scale with idle time) that a coverage rule cannot see and is not meant to.

⚠ **Neither repo calls this standard.** Verified 2026-08-25: no reference to
`akash-github-runner` or `reusable-akash-runner-conformance.yml` in either repo's `.github/`.

| repo | consumes conformance? |
|---|---|
| `Borduas-Holdings/blazing` | **NONE** |
| `Borduas-Holdings/Blazing-Back` | **NONE** |

### The rung this adds to #154's ladder

This file's own header already says it: *"A standard that has never been consumed has never been
tested"*, and *"GREEN requires a run id"*. `check_backstop_covers_producers.py` extends the ladder
to `merged != tested != invoked != enforced != SUFFICIENT`. The measurement above adds one more:

> **`ENFORCED` in the standard is not `ADOPTED` at the consumer.**

A rule can be merged, tested, invoked, enforcing, *and correct about a live defect it has already
identified by name*, while the repo carrying that defect never executes it. Promotion to ENFORCING
raises confidence in the **rule**; it says nothing about **coverage of the fleet**. Recorded here
rather than in a commit message because this file is where the difference between *shipped* and
*running* is supposed to be impossible to skip.

⚠ Counts are a single 10:01Z sample of a population an hourly reaper is draining — the
**composition** is the durable finding, the totals are not. And the `1 of 4` figure is `main` as of
2026-08-25; it moves as either repo changes its labels.
