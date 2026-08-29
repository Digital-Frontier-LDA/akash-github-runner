#!/usr/bin/env python3
"""A teardown that always runs and receives nothing is reachable, and inert.

`check_pool_owns_teardown.py` checks the lifecycle SHAPE — pool → work → always-teardown.
It says so itself, in the caveat this module exists to retire:

    "it cannot verify WHEN the identity is published. A pool that publishes `dseq` only
     after validation succeeds hands an EMPTY identity to a teardown that runs faithfully
     and closes nothing."

⛔ MEASURED TWICE, IN TWO REPOS, AT REAL COST.

just-akash published `dseq` only on the success path; 13 leases outlived their runs for
23.5h (census 2026-08-23: 13 × just-akash-runner.<hash> = 65 ACT). It is fixed there now —
`runner-pool.yml` publishes the moment the identity exists, before the tag and before the
registration wait.

Blazing-Back never got that fix and paid it again (Blazing-Back#1468): a lease WON, then
`jq: Cannot iterate over null` exited 5 mid-wait, both close jobs SKIPPED, two deployments
billing for 32 hours. Its containers stayed alive re-registering GitHub runners, so three
registration sweeps in a row looked like they had failed when they had worked.

⚠ NOTHING FLAGGED THAT ONE REPO WAS MISSING A FIX THE OTHER HAD SHIPPED. That is the gap.

⛔⛔ THE RULE MUST REJECT THE REALISTIC WRONG SHAPE, NOT MERELY FIND THE FIELD. Both repos
DID declare a `dseq` output. A rule that greps for "an output named dseq exists somewhere"
passes the broken form and certifies the exact workflows that leaked. The discriminator is
WHERE the write sits relative to the assignment that produced it:

    just-akash (correct)          Blazing-Back (broken)
    DSEQ=$(awk ... ja.log)        ... registration wait ...
    echo "dseq=$DSEQ" >> OUT      if [ "$online" -eq 1 ]; then
    ^ same nesting as the             echo "dseq=$DSEQ" >> OUT
      assignment, nothing              ^ nested INSIDE the success
      between them can exit              branch: a run that dies
                                         mid-wait never reaches it

⚠ ANSWERING THE OBJECTION #141 RAISED AGAINST EXACTLY THIS CHECK — "a positional proxy is
defeatable, and shipping one would assert a property it does not implement". It is
defeatable, and the answer is the DIRECTION in which it fails:

  * an unconditional emit written so this cannot see it (`if true; then`, a helper
    function, a sourced file) → FALSE POSITIVE. The repo is told to hoist the emit, which
    is the shape we want anyway. Annoying, safe, and fixable in one line.
  * a conditional emit this wrongly accepts → FALSE NEGATIVE, and the one that costs
    escrow. So every branch below fails CLOSED: no unconditional emit FOUND is a FAIL,
    never a pass-by-default. "I could not prove it" and "it is fine" are different
    answers and this module never conflates them.

⇒ This does NOT attempt the full control-flow analysis #141 correctly said would be
needed to be SOUND. It implements a weaker property that is checkable offline and whose
failures land on the safe side, and it names that limit rather than implying more.

⛔ WHAT THIS RULE DELIBERATELY DOES NOT CHECK, and why — see #151's assertion (2).

#151 proposes "the teardown is gated on that identity being non-empty, not on the
provisioning job's result == 'success'". The second half is already enforced by
`check_pool_owns_teardown.py`, in a STRICTLY STRONGER form: that rule requires the
teardown to be UNCONDITIONAL, and rejects a precondition on the identity as well as a
result gate.

⚠ THAT RULE'S PREMISE IS A PROPERTY OF THE TEARDOWN, NOT OF WORKFLOWS GENERALLY — and a
repo whose teardown lacks it CANNOT satisfy the unconditional requirement yet. The premise
is "an empty identity is a safe no-op". MEASURED 2026-08-24, and it splits:

    just-akash   runner-teardown.yml:140   `if [ -z "${DSEQ}" ]` -> "nothing to close"
                                            no-op. Unconditional teardown is safe.
    Blazing-Back scripts/ci_close_akash_deployment.sh:43
                                            `DSEQ="${DSEQ:?DSEQ not set}"` -> exit 1.
                                            Unconditional teardown FAILS the job on every
                                            run that never published a dseq.

Blazing-Back's close path is fail-closed BY DESIGN (#1390, "unverifiable is NOT closed"),
which is correct for a close that was attempted and could not be verified — and wrong for
a close that was never needed. ⇒ The sequencing for such a repo is: make the close a no-op
on an EMPTY identity first (nothing to close is not a failure), THEN go unconditional.
Reversing those two fails every run instead of leaking one lease, so the order is not a
matter of taste.

⚠ Reproducing that measurement needs the other required env vars set. With CONSOLE_API
unset the script exits 1 at line 41 for an unrelated reason, and reading that as "it
fail-closes on DSEQ" confirms the right conclusion from the wrong evidence.

⇒ So requiring an identity gate here would REJECT what the merged rule REQUIRES, and
every conforming repo would fail one of the two, forever. It would also reintroduce the
defect: `if: needs.pool.outputs.dseq != ''` SKIPS the teardown exactly when the identity
is empty — which is precisely when a lease has leaked. #151 says as much itself: "(2)
without (1) is worse than neither". With (1) enforced here, (2) is unnecessary; without
it, (2) is harmful. Either way the gate is wrong, so this module implements (1) only and
leaves the teardown's gating to the rule that already owns it.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

import yaml

try:  # dual-mode import: script (python3 akash_runner/check_x.py) and package (-m) invocations
    import cli_aliases
except ImportError:  # pragma: no cover - package mode only
    from akash_runner import cli_aliases

# The lifecycle identity a teardown needs in order to close anything.
IDENTITY = "dseq"

# `DSEQ=...` — the shell assignment that first holds the identity.
ASSIGNS_IDENTITY = re.compile(rf"^\s*{IDENTITY.upper()}=", re.I)

# `echo "dseq=..." >> "$GITHUB_OUTPUT"`, and the `echo "dseq=..."` line of a
# `{ ... } >> "$GITHUB_OUTPUT"` block.
EMITS_IDENTITY = re.compile(rf"""["']?{IDENTITY}=""", re.I)
GITHUB_OUTPUT = re.compile(r"\$\{?GITHUB_OUTPUT\}?")

# Anything that can leave the current path before the next line runs.
# ⚠ NOT anchored to the start of the line. The realistic spelling is `validate || exit 1`,
# and a start-anchored pattern misses every one of them — caught by its own test, which is
# why that test asserts on a `||` form rather than a bare `exit`.
ESCAPES = re.compile(r"(?:^|\||&|;)\s*(?:exit|return|continue|break)\b")

# ⛔ BRANCHING AND GROUPING ARE DIFFERENT THINGS, and conflating them made this rule
# reject the CORRECT shape. Only `if`/`for`/`while`/`until`/`case` make a line
# conditionally reached. A `{ ... } >> "$GITHUB_OUTPUT"` brace group is a REDIRECTION
# wrapper — its contents run unconditionally — and it is precisely how just-akash
# publishes its outputs. Counting the brace as depth flagged the reference implementation
# as broken, which would have made this rule's first real verdict a false positive
# against the repo it was written from.
OPENS_BRANCH = re.compile(r"^\s*(?:if|for|while|until|case)\b")
CLOSES_BRANCH = re.compile(r"^\s*(?:fi|done|esac)\b")

# Tracked ONLY to find the end of a redirected group, never for depth.
# ⚠ NO `\b` after the brace: `}` is non-word and a following space is non-word, so there
# is no boundary between them — `\}\b` cannot match `} >> "$GITHUB_OUTPUT"`.
CLOSES_GROUP = re.compile(r"^\s*\}")


def _steps(document: dict[str, Any]) -> list[tuple[str, dict]]:
    out: list[tuple[str, dict]] = []
    for job_name, job in (document.get("jobs") or {}).items():
        if not isinstance(job, dict):
            continue
        for step in job.get("steps") or []:
            if isinstance(step, dict) and step.get("run"):
                out.append((str(job_name), step))
    return out


def _depths(lines: list[str]) -> list[int]:
    """Shell nesting depth per line, counting the line's OWN opener as still outside.

    `if ...; then` is recorded at the depth it sits in; the lines it guards are deeper.
    A one-line `if x; then y; fi` opens and closes on the same line and nets to zero.
    """
    depths: list[int] = []
    depth = 0
    for line in lines:
        opens = 1 if OPENS_BRANCH.search(line) else 0
        closes = 1 if CLOSES_BRANCH.search(line) else 0
        if opens and re.search(r";\s*fi\s*$", line):  # single-line `if x; then y; fi`
            opens = closes = 0
        depth -= closes
        depths.append(max(depth, 0))
        depth += opens
    return depths


def _emit_lines(lines: list[str]) -> set[int]:
    """Indices whose line writes the identity into $GITHUB_OUTPUT.

    Handles both `echo "dseq=..." >> "$GITHUB_OUTPUT"` and the `echo "dseq=..."` line
    inside a `{ ... } >> "$GITHUB_OUTPUT"` group — the latter by scanning forward for the
    closing redirect without leaving the group.
    """
    found: set[int] = set()
    for i, line in enumerate(lines):
        if not EMITS_IDENTITY.search(line):
            continue
        if GITHUB_OUTPUT.search(line):
            found.add(i)
            continue
        for j in range(i + 1, min(i + 40, len(lines))):
            if CLOSES_GROUP.search(lines[j]):
                if GITHUB_OUTPUT.search(lines[j]):
                    found.add(i)
                break
    return found


def check_run_block(script: str) -> list[str]:
    """Findings for one `run:` block that assigns the identity."""
    lines = script.splitlines()
    assigns = [i for i, ln in enumerate(lines) if ASSIGNS_IDENTITY.search(ln)]
    if not assigns:
        return []
    depths = _depths(lines)
    emits = _emit_lines(lines)

    if not emits:
        return [
            f"assigns {IDENTITY.upper()} (line {assigns[0] + 1} of the run block) but never "
            f"writes it to $GITHUB_OUTPUT. A teardown cannot close what it cannot name."
        ]

    for a in assigns:
        for e in sorted(emits):
            if e <= a:
                continue
            if depths[e] > depths[a]:
                continue  # nested deeper than the assignment: conditional
            escaped = [
                k
                for k in range(a + 1, e)
                if ESCAPES.search(lines[k]) and depths[k] <= depths[a]
            ]
            if escaped:
                continue
            return []  # an unconditional emit reachable from this assignment

    first = sorted(emits)[0]
    return [
        f"publishes {IDENTITY!r} only from a CONDITIONAL path (run-block line "
        f"{first + 1}, nesting depth {depths[first]}, while {IDENTITY.upper()} is assigned "
        f"at depth {depths[assigns[0]]} on line {assigns[0] + 1}). A run that dies between "
        f"the two — cancellation, timeout, a mid-wait error — leaves the teardown with NO "
        f"identity to close, and the lease bills on. Publish it the moment it exists, at "
        f"the assignment's own nesting level."
    ]


def check_document(document: dict[str, Any]) -> list[str]:
    findings: list[str] = []
    for job_name, step in _steps(document):
        for finding in check_run_block(str(step.get("run") or "")):
            name = step.get("name") or "<unnamed step>"
            findings.append(f"{job_name} / {name}: {finding}")
    return findings


def main() -> int:
    parser = argparse.ArgumentParser()
    cli_aliases.add_workflow_file(parser)
    args = parser.parse_args()
    cli_aliases.require_file(args, "workflow", parser)
    try:
        document = yaml.safe_load(args.workflow.read_text()) or {}
    except (OSError, yaml.YAMLError) as exc:
        print(f"Teardown can identify: could not read workflow: {exc}", file=sys.stderr)
        return 2
    if not isinstance(document, dict) or not document.get("jobs"):
        # ⛔ NON-VACUITY FLOOR — the same one #144 had to add twice. A document with no
        # jobs satisfies every rule below while observing nothing.
        print(
            f"Teardown can identify: FAIL — {args.workflow} declares no jobs, so nothing "
            "was judged. A pass over an empty document is not compliance; check the path.",
            file=sys.stderr,
        )
        return 1
    findings = check_document(document)
    for finding in findings:
        print(f"::error title=Teardown can identify::{finding}")
    if findings:
        print(f"Teardown can identify: FAIL ({len(findings)} finding(s))")
        return 1
    steps_seen = len(_steps(document))
    print(f"Teardown can identify: PASS — {steps_seen} run-step(s) examined")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
