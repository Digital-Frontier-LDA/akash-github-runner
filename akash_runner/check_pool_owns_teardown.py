#!/usr/bin/env python3
"""A workflow that hands out a lifecycle identity must own the job that reclaims it.

⇒ THIS REPLACES THE RULE "every pool CONSUMER wires a teardown", which is unshippable:
`runner-pool.yml` has ZERO `workflow_call` consumers, so that rule's population is EMPTY
and it passes VACUOUSLY. A green over an empty set is not evidence, and a rule that cannot
fail is worse than no rule — it reads as coverage.

⚠ AND ITS PREMISE IS NOW OBSOLETE. just-akash #182 internalises teardown INTO the pool
(`needs: [pool]`, `if: always()`). Once the pool owns its own teardown, "did every consumer
remember to wire it?" is the wrong question — consumers inherit it and cannot forget. So
the check moves from the CONSUMER (empty, unverifiable) to the DEFINITION (present,
verifiable today).

⛔ THE DEFECT IT CATCHES. Before #182, `runner-pool.yml` leased Akash deployments, published
their `dseq`, and contained exactly one job: `pool`. Nothing in the workflow closed anything.
The pairing with `runner-teardown.yml` existed only in a docstring, and 13 leases outlived
their runs holding 65 ACT for 23.5h.

⚠ WHAT THIS RULE CANNOT SEE — AND WHAT NOW DOES. `check_teardown_can_identify.py` (#151)
implements the property described below. This rule still cannot see it; the caveat is kept
because it explains WHY the split exists, and a caveat that quietly became false is the
defect this standard is about. What changed is that the property is no longer unenforced.

It cannot verify WHEN the identity is published. A pool that
publishes `dseq` only after validation succeeds hands an EMPTY identity to a teardown that
runs faithfully and closes nothing — DEV2's measured "13 leases outlived their runs".
Verifying that needs bash control-flow analysis inside a `run:` block (tracking
`$GITHUB_OUTPUT` writes against `exit`/`continue`/`break` across retry loops, subshells and
heredocs). A positional proxy is defeatable, and shipping one would assert a property it
does not implement — the exact defect this whole standard exists to remove.
⇒ The structural mitigation is in this rule already: the teardown must be UNCONDITIONAL,
including no precondition on the identity being non-empty. `runner-teardown.yml` treats an
empty dseq as a successful no-op, so an unconditional teardown is safe on every path and
publication timing stops mattering. See Blazing-Back #1440.
"""

from __future__ import annotations

import argparse

import _cli
import re
import sys

from typing import Any

import yaml
from conformance_exit import not_judgeable

# Outputs that name a reclaimable resource. Publishing one is what puts a workflow in scope.
LIFECYCLE_IDENTITY = ("dseq",)

TEARDOWN_JOB = re.compile(
    r"(?:^|[-_])(?:teardown|close|destroy|reclaim)s?(?:$|[-_])", re.I
)

# ⚠ Duplicated from check_standard.py DELIBERATELY. That module's copy arrives with #139,
# which is unmerged, and this branch is cut from main. Consolidate once #139 lands — a
# shared import across two in-review branches would couple their review outcomes.
RESULT_GATE = re.compile(r"needs\.[A-Za-z0-9_-]+\.result")


def _text(value: Any) -> str:
    return str(value or "")


def _needs(job: dict[str, Any]) -> set[str]:
    value = job.get("needs", [])
    return {value} if isinstance(value, str) else set(value or [])


def _on(document: dict[str, Any]) -> dict[str, Any]:
    # YAML 1.1 parses a bare `on:` as the BOOLEAN True, not the string "on".
    for key in ("on", True):
        value = document.get(key)
        if isinstance(value, dict):
            return value
    return {}


def _published_identities(document: dict[str, Any]) -> dict[str, str]:
    """{output_name: producing_job} for lifecycle identities this workflow hands out."""
    call = _on(document).get("workflow_call")
    outputs = call.get("outputs") if isinstance(call, dict) else None
    if not isinstance(outputs, dict):
        return {}
    found: dict[str, str] = {}
    for name, spec in outputs.items():
        if name not in LIFECYCLE_IDENTITY:
            continue
        expression = _text(spec.get("value") if isinstance(spec, dict) else spec)
        match = re.search(r"jobs\.([A-Za-z0-9_-]+)\.outputs", expression)
        found[name] = match.group(1) if match else ""
    return found


def check(document: dict[str, Any]) -> list[str]:
    identities = _published_identities(document)
    if not identities:
        return []  # hands out no reclaimable resource — nothing to own

    jobs = document.get("jobs") or {}
    findings: list[str] = []
    for identity, producer in sorted(identities.items()):
        teardowns = [n for n in jobs if TEARDOWN_JOB.search(n)]
        if not teardowns:
            findings.append(
                f"publishes lifecycle identity {identity!r} but contains no teardown job — "
                f"the workflow hands out a resource it never reclaims, and any pairing that "
                f"exists only in a docstring is not a mechanism"
            )
            continue
        for name in sorted(teardowns):
            job = jobs.get(name) or {}
            if producer and producer not in _needs(job):
                findings.append(
                    f"{name}: must need {producer!r}, the job that creates {identity!r}; "
                    f"otherwise it can run before the resource exists"
                )
            condition = _text(job.get("if"))
            if RESULT_GATE.search(condition):
                findings.append(
                    f"{name}: teardown must not be gated on a job result ({condition!r}) — "
                    f"a pool that fails after leasing would skip its own closer"
                )
            elif condition and identity in condition:
                findings.append(
                    f"{name}: teardown must not be preconditioned on {identity!r} being "
                    f"non-empty ({condition!r}) — an empty identity is a safe no-op, and "
                    f"gating here re-trains the success-gating this rule exists to remove"
                )
    return findings


def main() -> int:
    parser = argparse.ArgumentParser()
    _cli.add_file_target(parser)
    args = parser.parse_args()
    _cli.resolve_target(parser, args, positional="workflow", flag="workflow_file")
    try:
        document = yaml.safe_load(args.workflow.read_text()) or {}
    except (OSError, yaml.YAMLError) as exc:
        print(f"Pool owns teardown: could not read workflow: {exc}", file=sys.stderr)
        return 2
    if not document.get("jobs"):
        # ⛔ NON-VACUITY FLOOR — see the directory checkers. An empty or job-less document
        # silently satisfied every rule below. Measured 2026-08-23: PASS on `{}`.
        print(
            f"Pool owns teardown: FAIL — {args.workflow} declares no jobs, so nothing was "
            "judged. A pass over an empty document is not compliance; check the path.",
            file=sys.stderr,
        )
        return not_judgeable(
            "check_pool_owns_teardown.py",
            "the rule observed nothing — see the message above.",
        )
    findings = check(document)
    for finding in findings:
        print(f"::error title=Pool owns teardown::{finding}")
    if findings:
        print(f"Pool owns teardown: FAIL ({len(findings)} finding(s))")
        return 1
    print(
        f"Pool owns teardown: PASS — {len(document.get('jobs') or {})} job(s) examined"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
