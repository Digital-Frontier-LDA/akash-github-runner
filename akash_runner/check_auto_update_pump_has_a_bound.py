#!/usr/bin/env python3
"""Auto-update is MANDATED by this standard; nothing yet bounds what it costs when it fails.

⛔⛔ THE GAP THIS RULE CLOSES. `check_disable_auto_update_absent` requires
`DISABLE_AUTO_UPDATE` to be ABSENT, i.e. it MANDATES runner auto-update, and its stated
reason is correct: GitHub deprecates a runner version on a DATE, so a static floor passes
today and rots tomorrow. Auto-update is the only mechanism that survives the NEXT
deprecation.

That rationale is TRUE and INCOMPLETE. It weighs one pump and mandates the other:

    PUMP A (deprecated runner)  just-akash deployment 1787733947684, 4x in ~63s
        "Disable auto update option is enabled" / version 2.334.0 / "Listening for Jobs"
        -> "Runner version v2.334.0 is deprecated and cannot receive messages"
        -> listener exits -> restart -> RE-REGISTER

    PUMP B (auto-update itself)  borduas-pool deployment 1788575148893, 2026-09-05
        "Current runner version: '2.336.0'" / "Listening for Jobs"   <- HEALTHY, NOT deprecated
        -> "Downloading 2.337.0 runner" -> "Runner will exit shortly for update"
        -> "Caught EXIT - Deregistering runner"
        -> "Failed: Removing runner from the server"
        -> "Could not load file or assembly 'System.Linq.Parallel, Version=8.0.0.0'"

Pump A is what `disable-auto-update-absent` prevents. Pump B is what it CAUSES: 2.337.0
shipped 2026-08-26, and the update killed a runner that had already registered and was
listening. No deprecation message appears anywhere in that log — the runner was fine until
the mandated update ran.

★ THE TWO PUMPS SHARE ONE PRECONDITION, AND THAT IS WHAT THIS RULE TARGETS. Both need a
container that can REGISTER but never WORK, restarted without bound. Neither symptom is the
invariant; the unbounded restart is. A rule aimed at either version string would be a rule
aimed at today's instance — the same defect as a static floor, one level up.

⇒ SO THE MANDATE MUST BE PAIRED WITH A BOUND. Either bound is accepted:

  (a) A LANDING GATE — the provisioner reads the registered runners' `.version` back from
      `orgs/.../actions/runners` after the pool reports online, and closes the lease when a
      runner reports a version that is not the expected one. `null` is the important case:
      a runner that registered and then died reports NO version, which is precisely pump B's
      corpse. (This is the mechanism of Blazing-Back #1590 Part 1.)

  (b) A RESTART BOUND — a deployment `restart:` policy that is not `always`, so the pump
      cannot run indefinitely even unobserved.

⚠ WHY THE COST IS NOT LOCAL TO THE FAILING REPO. Every restart adds an org runner
registration, and the org listing's PAGE COUNT sets the pre-strike CI quota floor.
Measured 2026-09-05: 1,732 registrations org-wide, a 300-runner sample 300/300 `offline`,
0 busy, `version: null`. The pool that produced them belongs to one repo; the quota floor
it inflates is read by EVERY repo on the shared PAT. A repo can therefore be refused CI by
a pump it does not run and cannot see.

⚠ A COMMENT DOES NOT SATISFY THE BOUND. The repos in scope carry long analyses of exactly
this failure in comments — Blazing-Back's `akash-runner.yml` holds the whole hypothesis.
Accepting a commented mention would certify the analysis as the fix. Comment lines are
stripped before the bound is looked for, and `test_a_commented_gate_is_not_a_bound` pins it.

⛔ WHAT A PASS DOES **NOT** CERTIFY — READ THIS BEFORE PROMOTING THE RULE.
This rule proves the evidence is READ. It does not prove the evidence is ACTED ON. Those
are different claims and only the first is statically checkable here.

Demonstrated by DEV1 while building just-akash#262: adding the `.version` projection alone
flipped this rule to exit 0 BEFORE any decision, any comparison, any lease close existed.
A workflow can therefore satisfy this rule while discarding nothing. Had the rule been
promoted to ENFORCING on that state, it would have certified an unbounded pool.

⇒ SO THE PROMOTION CONDITION IS NOT "consumers go green". A green here means the consumer
stopped being blind, not that it stopped pumping. Promote only against a gate whose
DECISION has been exercised — including the degenerate read that the same PR found and
fixed: N runner ids with ZERO versions is a read disagreeing with itself, and it was
rendering as a healthy pool. The gate's own failure mode was the failure the gate exists
to stop.

The honest framing of this rule is: it removes the excuse of not looking. Closing the loop
from "looked" to "acted" needs a behavioural test in the consumer, and that test belongs
there, not here — a conformance checker reading workflow text cannot run the decision.

⚠ NOT APPLICABLE IS A THIRD STATE AND IS PRINTED. A repo that defines no runner container
is not thereby compliant; it is out of scope, and saying "PASS" would let a scope bug read
as a clean bill. `check_runner_image_digest_floor` reported NOT APPLICABLE on the exact
repo it was built for; this rule prints its scope population so that failure is visible.
"""

from __future__ import annotations

import _cli

import argparse
import importlib.util
import re
import sys
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "check_conformance_shim",
    Path(__file__).resolve().parents[1] / "baseline" / "check_conformance.py",
)
assert _SPEC and _SPEC.loader
_cc = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _cc
_SPEC.loader.exec_module(_cc)

Finding = _cc.Finding

# ⛔ SCOPE = a file that DEFINES a runner container, not one that CALLS a pool.
# Measured against the live fleet: `runner-pool.yml`, `akash-runner.yml` and
# `sdl/github-runner-probe.yaml` all ship the token as an env-list item; `blazing/ci.yml`
# passes `GH_RUNNER_PAT` as a SECRET to a reusable workflow and defines no container.
# Scoping on the secret name instead would pull in every caller and make the rule
# unsatisfiable for repos that correctly delegate provisioning.
_DEFINES_RUNNER = re.compile(
    r"""^\s*
        (?:-\s*)?                                   # env-list item, or a mapping key
        (?:ACCESS_TOKEN|RUNNER_TOKEN|\{\{TOKEN_ENV\}\})
        \s*[:=]
    """,
    re.VERBOSE,
)

# (a) the landing gate: read the listing AND project the version back out of THAT read.
#
# ⛔ FILE-LEVEL `AND` IS NOT ENOUGH — MEASURED, IT PASSED A REPO WITH NO GATE.
# The first draft asked only "does this file mention actions/runners AND .version". Run
# against blazing/akash-ci.yml (1,400+ lines) it reported a landing gate that does not
# exist: `.version` matched `.application_version.version` (an Akash NODE query, line 132)
# and `sys.version` (line 1415), while the file's actual runner listing read at line 1213
# projects `.labels[].name`. A rule that certifies an ungated repo is worse than no rule.
#
# ⇒ PROXIMITY IS THE DISCRIMINATOR, AND BOTH CONTROLS ARE PINNED. The projection must sit
# near the read, because a gate reads the listing and inspects it in the same step:
#     POSITIVE  Blazing-Back #1590's real gate: listing read and `map(.version // "NULL")`
#               are 11 lines apart.
#     NEGATIVE  blazing/akash-ci.yml: nearest `.version` is 202 lines from the read.
# _WINDOW sits between them. It is deliberately generous — a false NEGATIVE here only asks
# a compliant repo to move two lines together, while a false POSITIVE hands out the
# certificate this rule exists to withhold.
_READS_LISTING = re.compile(r"actions/runners")
_PROJECTS_VERSION = re.compile(r"\.version\b|runner_version\b")
_WINDOW = 40

# (b) the restart bound: any restart policy that is not `always`.
_RESTART = re.compile(r"^\s*restart\s*:\s*(?P<v>[A-Za-z-]+)")


def _uncommented(text: str) -> list[str]:
    """Lines with whole-line comments dropped — a commented gate is not a gate."""
    return [ln for ln in text.splitlines() if not ln.strip().startswith("#")]


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _targets(workflows_dir: Path) -> list[Path]:
    """Workflow YAML plus any sibling `sdl/` — the runner container lives at both sites."""
    files = sorted(workflows_dir.glob("*.yml")) + sorted(workflows_dir.glob("*.yaml"))
    root = workflows_dir.parent.parent
    sdl = root / "sdl"
    if sdl.is_dir():
        files += sorted(sdl.glob("*.yml")) + sorted(sdl.glob("*.yaml"))
    return files


def _has_bound(lines: list[str]) -> str | None:
    """Return the name of the bound this file provides, or None."""
    reads = [i for i, ln in enumerate(lines) if _READS_LISTING.search(ln)]
    projects = [i for i, ln in enumerate(lines) if _PROJECTS_VERSION.search(ln)]
    for r in reads:
        if any(abs(v - r) <= _WINDOW for v in projects):
            return "landing-gate"
    for ln in lines:
        m = _RESTART.match(ln)
        if m and m.group("v").lower() != "always":
            return "restart-bound"
    return None


def check(workflows_dir: Path) -> tuple[list[Finding], list[Path], list[str]]:
    """Findings are PER RUNNER CONTAINER, not per repo.

    ⛔ THE FIRST VERSION SUPPRESSED EVERY FINDING WHEN ANY FILE HAD A BOUND —
    `if not in_scope or bounds: return []`. One bounded file silenced every unbounded runner
    container beside it, so a repo could add a gate to one workflow and go clean while the
    other still pumped. Reported independently by Copilot and CodeRabbit on #69, and the
    blast radius this rule itself printed names the case: **Blazing-Back FAIL (2 —
    akash-runner.yml AND runner-time-to-ready.yml)**. Bound either one and the other vanished.

    ⚠ THE ORIGINAL INSTINCT WAS NOT BASELESS, AND THAT IS WHY IT SURVIVED REVIEW ONCE.
    A gate legitimately lives in a different file from the container it protects —
    just-akash's container is in `sdl/github-runner-probe.yaml` while its landing gate is in
    `runner-pool.yml`. So a strictly per-file rule would flag that SDL forever.

    ⇒ THE RULE CANNOT PROVE ASSOCIATION FROM WORKFLOW TEXT, so it says so rather than
    guessing in either direction: a container with no bound of its own is REPORTED, and when
    a bound exists elsewhere in the repo the finding NAMES it and asks for the association to
    be stated. A false positive costs a sentence; the false clean cost the whole rule.
    """
    files = _targets(workflows_dir)
    in_scope: list[Path] = []
    bounds: list[str] = []
    bound_of: dict[Path, str] = {}
    for f in files:
        lines = _uncommented(_read(f))
        if any(_DEFINES_RUNNER.search(ln) for ln in lines):
            in_scope.append(f)
        b = _has_bound(lines)
        if b:
            bounds.append(f"{f.name}:{b}")
            bound_of[f] = b

    unbounded = [p for p in in_scope if p not in bound_of]
    if not in_scope or not unbounded:
        return [], in_scope, bounds

    elsewhere = ", ".join(sorted(f"{f.name}:{b}" for f, b in bound_of.items()))

    return (
        [
            Finding(
                rule="auto-update-pump-has-a-bound",
                severity="required",
                path=str(p),
                line=1,
                message=(
                    (
                        f"A bound EXISTS elsewhere in this repo ({elsewhere}), but this rule "
                        "cannot prove from workflow text that it protects THIS container. "
                        "If it does, say so; if it does not, this container is unbounded. "
                        if elsewhere
                        else ""
                    )
                    + "This file defines a runner container, and the standard MANDATES "
                    "auto-update (disable-auto-update-absent). THIS container has no bound on "
                    "the register->die->restart pump that a failed update produces: no "
                    "landing gate (read `.version` back from orgs/.../actions/runners after "
                    "the pool reports online and close the lease on a mismatch or null) and "
                    "no restart bound (a deployment `restart:` that is not `always`). Every "
                    "restart adds an org registration, and the listing's page count sets the "
                    "CI quota floor for EVERY repo on the shared PAT."
                ),
            )
            for p in unbounded
        ],
        in_scope,
        bounds,
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workflows-dir", required=True)
    _cli.add_dir_positional(ap)
    args = ap.parse_args()
    _cli.resolve_dir_positional(ap, args)

    wd = Path(args.workflows_dir)
    findings, in_scope, bounds = check(wd)

    if not in_scope:
        print(
            "auto-update-pump-has-a-bound: NOT APPLICABLE — no file under "
            f"{wd} (or its sibling sdl/) defines a runner container "
            "(no ACCESS_TOKEN / RUNNER_TOKEN / {{TOKEN_ENV}} assignment). "
            "This is NOT a pass; nothing was judged."
        )
        # ⛔ EXIT 3, NOT 0. The conformance action's `advisory()` maps 0 -> PASS and
        # 3 -> NOT-JUDGEABLE. Returning 0 here printed "This is NOT a pass" and was
        # then reported as a PASS by the harness — the message said one thing and the
        # exit code said the opposite, and the exit code is what the action reads.
        return 3

    print(
        "auto-update-pump-has-a-bound: in scope -> "
        + ", ".join(p.name for p in in_scope)
    )
    if bounds:
        # ⛔ INFORMATIONAL ONLY. This printed and then `return 0`, so ONE bound anywhere
        # exited clean no matter how many runner containers were unbounded — the same
        # fail-open as `check()`'s old `or bounds`, duplicated at the exit code. The
        # verdict is now derived from FINDINGS, which is the only thing that knows
        # whether a container was left unprotected. (Copilot, #69.)
        print("  bound(s) found: " + ", ".join(bounds))

    if not findings:
        return 0

    for f in findings:
        print(f"{f.path}:{f.line}: [{f.rule}] {f.message}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
