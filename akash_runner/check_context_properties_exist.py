#!/usr/bin/env python3
"""A context property that does not exist resolves to the EMPTY STRING, never an error.

⛔ THE DEFECT, MEASURED TWICE. Instance 1 (just-akash #182): a teardown job passed
`github.organization` — which the `github` context does not define — as its org
identity. It resolved to "" silently; six required checks were green over it; the
de-registration called the wrong URL until review threads caught it by eye.

Instance 2 (just-akash #184): `runner-pool.yml` pinned its provisioning checkout with

    repository: ${{ job.workflow_repository || 'Digital-Frontier-LDA/just-akash' }}
    ref:        ${{ job.workflow_sha }}

The `job` context carries ONLY {check_run_id, container, services, status}. Both
properties resolved empty — `ref:` fell back to the default branch — so EVERY runner
was provisioned from main's tip at deploy-second while every caller believed their pin
held. An unpinned provisioning binary: a mid-run push changed what the pool built,
invisibly.

⚠ WHY GREEN CHECKS COULD NOT SEE IT. The failure is not a test failure; it is a
missing-value failure, and the expression language's contract is that a nonexistent
property dereference yields the empty string. No runner, no linter in the standard set,
no required context reads workflow expressions. The value was wrong on every run the
check was green on.

⭐ THE GENERAL SHAPE: a typo-shaped or believed-to-exist property is INDISTINGUISHABLE
from a valid one until you diff it against the documented context schema. The language
will never error; the only error surface is a list of names that actually exist. That
is what this rule holds: the CLOSED vocabularies (`job`, `runner`, `strategy`) and the
documented `github.*` leaf set, transcribed from GitHub's contexts reference — the same
source actionlint's grammar is built from.

⇒ WHAT THIS RULE DEMANDS. Every `${{ ... }}` reference rooted at `job.`, `runner.`,
`strategy.` must name a documented first-segment property of that context; every
`github.<leaf>` (first segment only, NOT `github.event.**`) must be in the documented
set. Anything else fails with the property named, or is exempted in
CONTEXT_PROPERTY_EXEMPT with a reason.

⚠ SCOPE IS DELIBERATELY NARROW — A FALSE POSITIVE ON A VALID PROPERTY IS WORSE THAN A
MISS, so this rule checks only what has a CLOSED, documented vocabulary:
  * `github` — first segment against the documented leaf list below. `github.event.**`
    (the webhook payload) is deliberately UNCHECKED: it is open, event-shaped, and a
    rule that flags valid payload paths would be noise on first contact.
  * `job`, `runner`, `strategy` — first segment against their complete documented
    sets. Deeper paths under object leaves (`job.container.*`, `job.services.<id>.*`)
    are UNCHECKED: `services.<id>` is workflow-defined, so depth is an open vocabulary.
  * DELIBERATELY NOT CHECKED AT ALL: `needs.*`, `steps.*`, `inputs.*`, `matrix.*`,
    `env.*`, `vars.*`, `secrets.*` (all open vocabularies — repo- and
    workflow-defined); the `jobs` context (reusable-workflow outputs need a call
    graph); function-call names (a call form like `format(...)` is not a property
    reference); index syntax `[...]`.

★ THE PROPERTY WORTH KEEPING: existence-checking is only possible where the schema is
closed, and the closed sets are few and small. When GitHub documents a new property,
add it to the set IN THE SAME CHANGE that first uses it — the diff that introduces the
usage is the moment a human vouches the name exists. The set is the error surface the
expression language refuses to give you.
"""

from __future__ import annotations

import argparse

import _cli
import re
import sys
from pathlib import Path

# ── The closed vocabularies ─────────────────────────────────────────────────────
# Transcribed from GitHub's "Accessing contextual information about workflow runs"
# (contexts reference): the `job` context table is {check_run_id, container, services,
# status} — actionlint's runtime-derived grammar agrees. The same page documents
# `runner` and `strategy`. Where docs and actionlint disagreed historically the
# DOCUMENTED set is used, because a consumer's author reads the docs.

JOB_LEAVES = {"check_run_id", "container", "services", "status"}
RUNNER_LEAVES = {"name", "os", "arch", "temp", "tool_cache", "debug", "environment"}
STRATEGY_LEAVES = {"fail-fast", "job-index", "job-total", "max-parallel"}

# The documented `github` first segments. `event` is in the set (it exists); the
# PAYLOAD under it is deliberately unvalidated (open vocabulary).
GITHUB_LEAVES = {
    "action",
    "action_path",
    "action_ref",
    "action_repository",
    "action_status",
    "actor",
    "actor_id",
    "api_url",
    "base_ref",
    "env",
    "event",
    "event_name",
    "event_path",
    "graphql_url",
    "head_ref",
    "job",
    "path",
    "ref",
    "ref_name",
    "ref_protected",
    "ref_type",
    "repository",
    "repository_id",
    "repository_owner",
    "repository_owner_id",
    "repositoryUrl",
    "retention_days",
    "run_id",
    "run_number",
    "run_attempt",
    "secret_source",
    "server_url",
    "sha",
    "token",
    "triggering_actor",
    "workflow",
    "workflow_ref",
    "workflow_sha",
    "workspace",
}

CLOSED_ROOTS = {"job": JOB_LEAVES, "runner": RUNNER_LEAVES, "strategy": STRATEGY_LEAVES}

# An exemption must name the property AND why it is trusted. An exemption without a
# reason is a permanent silence; this file makes the reason readable.
CONTEXT_PROPERTY_EXEMPT: dict[str, str] = {}

_EXPR = re.compile(r"\$\{\{(.*?)\}\}", re.S)
# A dotted reference rooted at a checked context — ANCHORED. First segment only; the
# second group is the leaf under judgement. Hyphens allowed (strategy.fail-fast).
#
# ⛔ THE ANCHOR IS LOAD-BEARING, measured 2026-08-24 by TEAMLEAD across real repos:
# Blazing-Back 8 findings, blazing 7, df-cicd 0 — ALL the same shape, and ALL false:
# `\b` is a WORD boundary, and hyphen→letter IS one, so `needs.deploy-runner.outputs.dseq`
# matched `runner.outputs` — a phantom `runner` context conjured from a JOB NAME. That
# also defeated the documented scope: the rule reached into `needs.*`, an open
# vocabulary it explicitly does not check, through the substring. The negative
# lookbehind forbids the delimiters that make a substring — word chars, `.` and `-` —
# so the context name must start at a token boundary (expression start, whitespace,
# `(`, `!`, `&&`/`||`, `,`), exactly the positions where a context reference can
# legitimately begin.
_REF = re.compile(
    r"(?<![\w.\-])(github|job|runner|strategy)\.([A-Za-z_][A-Za-z0-9_\-]*)"
)


def offending_expressions(text: str) -> list[tuple[str, str]]:
    """(property, expression) pairs where a checked-context property does not exist."""
    out: list[tuple[str, str]] = []
    for m in _EXPR.finditer(text):
        expr = m.group(0).strip()
        for ref in _REF.finditer(m.group(1)):
            root, leaf = ref.group(1), ref.group(2)
            if root == "github":
                if leaf == "event":
                    continue  # the payload under github.event is an open vocabulary
                valid = leaf in GITHUB_LEAVES
            else:
                valid = leaf in CLOSED_ROOTS[root]
            if valid:
                continue
            if f"{root}.{leaf}" in CONTEXT_PROPERTY_EXEMPT:
                continue
            out.append((f"{root}.{leaf}", expr))
    return out


def check_workflow(path: Path) -> list[tuple[str, str]]:
    return offending_expressions(path.read_text())


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--workflows-dir", default=".github/workflows")
    _cli.add_dir_positional(ap)
    args = ap.parse_args(argv)

    _cli.resolve_dir_positional(ap, args)
    d = Path(args.workflows_dir)
    if not d.is_dir():
        print(f"::warning::{d} is not a directory — nothing to check")
        return 0

    files = sorted(d.glob("*.yml")) + sorted(d.glob("*.yaml"))
    bad = 0
    for p in files:
        for prop, expr in check_workflow(p):
            bad += 1
            print(
                f"::error file={p}::{prop} does not exist in its context — it resolves "
                f"to the EMPTY STRING silently, in: {expr}"
            )
    if bad:
        print(
            "::error::A nonexistent context property is indistinguishable from a valid "
            "one at runtime. Fix the property name, or add it to CONTEXT_PROPERTY_EXEMPT "
            "with a reason."
        )
        return 1
    print(
        f"OK: every checked context property in {len(files)} workflow(s) is documented."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
