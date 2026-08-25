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
