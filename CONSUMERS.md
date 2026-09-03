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
| `reusable-akash-runner-conformance.yml` | `Digital-Frontier-LDA/just-akash`, `Borduas-Holdings/Blazing-Back`, `Borduas-Holdings/blazing` — each `.github/workflows/runner-conformance.yml` | `GREEN` | Runs `33748069252` (just-akash), `33725444826` (Blazing-Back), `33726415072` (blazing), all 2026-09-03, all with jobs. This row read `NEVER-GREEN` on 8 runs / 8 failures / `jobs=0`, whose measured cause was that a public repo cannot call a reusable from a private/internal one. Publishing this repo removed the blocker — which is what the row predicted — and these three ids are the executions that close it. |

| `reusable-akash-escrow-reaper.yml` | `Borduas-Holdings/Blazing-Back` → `escrow-reaper.yml`; `Borduas-Holdings/blazing` → `akash-escrow-reaper.yml` | `GREEN` | Runs `33729677214` (Blazing-Back, 07:44) and `33734472017` (blazing, 08:38), 2026-09-03; both pin `@fcc385a6`. This row read `NONE` and called its checker ADVISORY — it is **ENFORCING** (`akash-runner-conformance/action.yml:209`). ⚠ blazing's fast/e2e pools remain OUTSIDE its `placement-prefix`: `runner-pool.yml` hardcoded the pool's placement key until just-akash#246, so those leases carry a marker no consumer can claim. |
| `reusable-stale-runner-reaper.yml` | `Borduas-Holdings/blazing` → `akash-runner-registration-reaper.yml`; `Digital-Frontier-LDA/just-akash` → `reap-stale-runners.yml` | `GREEN` | Run `33751716199` (blazing, 11:48, hourly) — also the cross-org transport proof this file asks for: `Borduas-Holdings` → `Digital-Frontier-LDA`, resolving and running WITH jobs. blazing retired its repo-local `scripts/akash-runner-reaper.sh` in the same change, carrying all six prefixes to `name-prefixes`. just-akash's caller is adopted at a pinned SHA with no scheduled execution observed yet. ⚠ `Blazing-Back` is NOT a consumer despite matching a naive grep — its only mention is a COMMENT naming df-cicd's deleted copy (`stale-runner-reaper.yml:6`), which is why the rule strips comments before judging. |

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

| repo | emitted prefixes | claimable by a reaper | offline registrations |
|---|---|---|---|
| `Borduas-Holdings/blazing` | `df-flow-`, `akash-integration-`, `akash-fast-pool-`, `akash-e2epool-` | **all claimable** | 167 |
| `Borduas-Holdings/Blazing-Back` | `df-core-`, plus `akash-*` from any pre-`30fcc2c84` ref | `df-core-` only | 175 |

342 offline registrations across the two, and the rule that detects exactly this defect has been
enforcing the whole time.

⚠ **This section recorded that neither repo called the standard.** True when written on
2026-08-25; both do now. The row is corrected in place rather than deleted — the gap it
describes, a standard whose own subjects did not consume it, is exactly what this file
exists to make observable, and removing the evidence once it closes leaves nobody able to
see that it was ever open.

| repo | consumes conformance? | evidence | was |
|---|---|---|---|
| `Borduas-Holdings/blazing` | ✅ `runner-conformance.yml` @ `f6bf24ec` | run `33726415072` | **NONE** on 2026-08-25 |
| `Borduas-Holdings/Blazing-Back` | ✅ `runner-conformance.yml` @ `f6bf24ec` | run `33725444826` | **NONE** on 2026-08-25 |

⚠ Both rows are an EXECUTABLE `uses:` read with comment lines stripped, and each cites an
EXECUTION rather than the file's existence. "The file exists", "the pin resolves" and "the
contract matches" were all true of the conformance reusable while it had never run.

### `df-cicd` — the author, measured 2026-08-25

`Digital-Frontier-LDA/df-cicd` wrote this standard and hosted it until the split. It is the
sharpest version of the gap above, and the answer is **not** "it should adopt and doesn't".
Measured, not assumed:

| question | measured answer |
|---|---|
| calls the canonical `runner-pool.yml`? | **no** — zero references in `.github/` |
| emits runner registrations? | **no** — `RUNNER_NAME_PREFIX` appears nowhere in the repo |
| provisions an Akash lease? | **no** — `df-akash-gate.yml`'s `just-akash deploy` is commented out and the step writes `dseq=` unconditionally |
| `runs-on: [self-hosted, sentinel]` | pre-existing long-lived runners; **not** registrations this repo mints |

⇒ **The registration-leak rules are NOT APPLICABLE to `df-cicd`.** It has no producers, so
`check_backstop_covers_producers` has nothing to cover. Wiring it would produce a green that
certifies nothing — the precise defect this campaign exists to remove, installed by the campaign.
A `NONE` row here is the honest state.

⚠ **`NOT APPLICABLE` is a per-rule verdict, not a per-repo one.** The dir-scoped rules were run
against `df-cicd`'s 25 workflows on 2026-08-25 and 8 of 10 pass **non-vacuously** (25 files
examined each). Two report real defects, both ADVISORY:

| rule | finding |
|---|---|
| `check_teardown_cannot_be_silenced` | `df-akash-gate.yml:82` — `[ -n "${DSEQ:-}" ] && just-akash close "$DSEQ" 2>/dev/null \|\| true`. Already named in this rule's own ADVISORY entry as the only instance repo-wide. |
| `check_schedule_inputs_are_empty` | `ci-unrunnable-tracker.yml`, `secret-sweep-full-history.yml` |

So the standard is not inapplicable to `df-cicd` as a whole — only its registration half is.

### ⛔ Why `df-cicd` cannot adopt the dir-scoped half today

`check_standard.py` is **ENFORCING** and reports `no canonical just-akash runner-pool reusable job
found` against **every** `df-cicd` workflow — measured on `df-akash-gate.yml`, `ci.yml` and
`sentinel-engagement.yml`, exit 1 each. `df-cicd` is neither a consumer of the pool nor the pool,
so pool-as-target mode does not reach it either. Adding the conformance workflow as it stands would
make the repo **permanently red for a defect it does not have**, which is a miswiring, not a
finding.

The composite action already anticipates this: `workflow` is `required: false` there and
`check_standard` runs only `if [ -n "$WORKFLOW" ]`. **The reusable does not mirror it** —
`workflow` is `required: true` in `reusable-akash-runner-conformance.yml`, so a consumer calling
the reusable cannot select the dir-scoped-only adoption the action supports.

⇒ That mismatch, not `df-cicd`, is what blocks an honest partial adoption. Until it is closed, the
row below is the accurate one.

| repo | consumes conformance? | why |
|---|---|---|
| `Digital-Frontier-LDA/df-cicd` | **NONE** | registration rules not applicable (no producers); dir-scoped-only adoption not expressible through the reusable |

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
**composition** is the durable finding, the totals are not. ⛔ **CORRECTION (2026-08-25).** An earlier revision of this row read **`1 of 4`**. That was
measured against a **stale local branch**, not `origin/main`. Verified on `origin/main`,
`scripts/akash-runner-reaper.sh:66-71` allowlists **six** prefixes and both leaking ones are in
it. Re-running `check_backstop_covers_producers.py` against `origin/main` for both repos:
`Blazing-Back exit=0 (56 workflows)`, `blazing exit=0 (21 workflows)` — **PASS/PASS**. Every
`covered: NO` row in that rule's 2026-08-24 docstring has since been fixed (Blazing-Back's
`runner-time-to-ready.yml` in `ab615607b` / #1480; blazing's by the `df-flow-` rename).

⚠ **PASS means every emitted prefix is CLAIMABLE. It does not mean nothing leaks.** blazing
still carries ~167 offline registrations under prefixes its reaper does cover — a production
RATE problem the coverage rule cannot see, and the reason blazing#689 is still the right fix.

⇒ The adoption gap below stands unchanged and is the real finding: neither repo consumes this
standard, so the rule that would have caught the original defect never runs for them.
2026-08-25; it moves as either repo changes its labels.
