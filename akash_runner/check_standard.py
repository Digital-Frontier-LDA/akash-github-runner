#!/usr/bin/env python3
"""Validate the DF Akash GitHub-runner lifecycle contract."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml

try:  # dual-mode import: script (python3 akash_runner/check_x.py) and package (-m) invocations
    import cli_aliases
except ImportError:  # pragma: no cover - package mode only
    from akash_runner import cli_aliases

POOL = "Digital-Frontier-LDA/just-akash/.github/workflows/runner-pool.yml@"
TEARDOWN = "Digital-Frontier-LDA/just-akash/.github/workflows/runner-teardown.yml@"
IMMUTABLE = re.compile(r"(?:v\d+\.\d+\.\d+|[0-9a-f]{40})$")

# ── The pool's side of the same contract ────────────────────────────────────────────
# Consumer mode (below) requires a consumer to PASS these inputs, MAP these secrets, and
# dereference these outputs. Nothing verified that the pool actually OFFERS them — the
# canonical pool was judged by no rule at all, because the locator selects jobs that
# `uses:` the pool and a pool does not `uses:` itself (measured: just-akash#200).
#
# ⚠ Keep these three tuples in step with consumer mode. They are deliberately the SAME
# names the consumer rules enforce: a contract checked on only one side is not checked.
POOL_REQUIRED_INPUTS = ("runner-label", "tag-prefix", "github-org", "providers")
POOL_REQUIRED_SECRETS = ("AKASH_API_KEY", "AKASH_API_KEYS", "GH_RUNNER_PAT")
# `dseq` pairs a consumer's teardown (`needs.<pool>.outputs.dseq`); `runner-targets` is
# what a consumer puts in runs-on. Dropping either silently breaks every consumer.
POOL_REQUIRED_OUTPUTS = ("dseq", "runner-targets")
# ── Teardown predicate rule ─────────────────────────────────────────────────────────
# A job that tears down / closes / reaps a provisioned resource must not be gated on the
# PROVISIONER'S RESULT. A provision that creates a lease and then fails or is cancelled
# never reaches `success`, so a success-gated closer skips and the lease outlives the run.
#
# ⚠ The rule reads the PREDICATE, never the prose. Conditioning on "the docstring claims
# always-runs" is satisfiable by deleting the comment — the fix becomes "stop promising"
# instead of "start reaping" — and is unenforceable on a repo with no comments at all.
TEARDOWN_NAME = re.compile(
    r"(?:^|-)(?:close|teardown|cleanup|reap|destroy)(?:$|-)", re.I
)
RESULT_GATE = re.compile(r"needs\.[A-Za-z0-9_-]+\.result")

# Explicit exceptions only, each carrying a REASON. An inferred exception is how the next
# instance hides; `test_every_allowlist_entry_states_a_reason` keeps this honest.
RESULT_GATE_ALLOWLIST: dict[str, str] = {}

DF_PREFERRED = {
    "akash1hgulk6aekakqzc0v6wukrd3dy9n90f5gkl4ezk",
    "akash1z9nr23cgweu45g2jktfx95v7g2xp8qlsa3ys2x",
    "akash1aaul837r7en7hpk9wv2svg8u78fdq0t2j2e82z",
}


def _text(value: Any) -> str:
    return str(value or "")


def _needs(job: dict[str, Any]) -> set[str]:
    value = job.get("needs", [])
    return {value} if isinstance(value, str) else set(value or [])


def _ref(uses: str) -> str:
    return uses.rsplit("@", 1)[-1] if "@" in uses else ""


def _result_gated_teardowns(jobs: dict[str, Any]) -> list[str]:
    """Teardown-shaped jobs whose `if:` gates on a provisioner's result.

    ⚠ Selection is by JOB NAME, and that is a heuristic — the only signal available in a
    repo that does not use the canonical reusable teardown. It is deliberately narrow:
    flagging every result-gated job would flag ordinary test sequencing and the rule would
    be turned off. `test_known_good_non_teardown_job_is_not_in_scope` pins that boundary.

    Gating on OUTPUT PRESENCE (`needs.pool.outputs.dseq != ''`) is permitted — that is the
    correct way to express "do not close a lease that was never opened", and it is what the
    result gate is usually mistaken for.
    """
    findings: list[str] = []
    for name, job in jobs.items():
        if not TEARDOWN_NAME.search(name):
            continue
        condition = _text((job or {}).get("if"))
        if not RESULT_GATE.search(condition):
            continue
        if name in RESULT_GATE_ALLOWLIST:
            continue
        findings.append(
            f"{name}: teardown must not be gated on its provisioner's result "
            f"({condition!r}) — a provision that creates a resource and then fails or is "
            f"cancelled never reaches success, so its own closer is skipped and the "
            f"resource leaks. Use if: always(), gating on output presence if needed."
        )
    return findings


def _workflow_call(document: dict[str, Any]) -> dict[str, Any] | None:
    """The `on: workflow_call` mapping, or None.

    PyYAML parses an unquoted `on:` key as the BOOLEAN True (the YAML 1.1 y/n/on/off
    rule), which is how every GitHub workflow in the wild is written. Reading only
    `document["on"]` silently sees nothing on real files and the whole mode would be
    inert — the exact vacuous-pass shape `test_no_vacuous_pass` exists to prevent.
    """
    triggers = document.get("on", document.get(True))
    if not isinstance(triggers, dict):
        return None
    call = triggers.get("workflow_call")
    return call if isinstance(call, dict) else None


def _looks_like_the_canonical_pool(document: dict[str, Any]) -> bool:
    """Whether this document IS the pool, rather than a workflow that calls one.

    ⚠ NARROW ON PURPOSE, and the boundary is pinned by
    `test_an_unrelated_reusable_workflow_is_not_mistaken_for_the_pool`. `workflow_call`
    ALONE must not select pool mode, or every reusable workflow in the org silently
    starts being judged against the Akash pool contract — a scope widening disguised as
    a bug fix, which is the shape the characterisation tests in
    test_teardown_not_result_gated.py exist to catch.

    ⇒ The signature is `workflow_call` + the distinctive AKASH_API_KEY secret. It keys on
    ONE secret while the rule then checks all three, so a pool that is missing a required
    secret is still recognised AS a pool and told which one is missing. A signature drawn
    from the things being checked would make every non-conforming pool undetectable —
    the rule would pass by failing to look.
    """
    call = _workflow_call(document)
    if call is None:
        return False
    secrets = call.get("secrets")
    return isinstance(secrets, dict) and "AKASH_API_KEY" in secrets


def _check_pool_contract(document: dict[str, Any]) -> list[str]:
    """Judge the canonical pool: does it OFFER what consumer mode requires consumers use?"""
    findings: list[str] = []
    call = _workflow_call(document) or {}

    def _declared(section: str) -> set[str]:
        value = call.get(section)
        return set(value) if isinstance(value, dict) else set()

    inputs, secrets, outputs = (
        _declared("inputs"),
        _declared("secrets"),
        _declared("outputs"),
    )
    for field in POOL_REQUIRED_INPUTS:
        if field not in inputs:
            findings.append(
                f"pool: workflow_call does not declare input {field!r}, which consumer "
                f"conformance requires every consumer to pass"
            )
    for field in POOL_REQUIRED_SECRETS:
        if field not in secrets:
            findings.append(
                f"pool: workflow_call does not declare secret {field!r}, which consumer "
                f"conformance requires every consumer to map explicitly"
            )
    for field in POOL_REQUIRED_OUTPUTS:
        if field not in outputs:
            findings.append(
                f"pool: workflow_call does not publish output {field!r}; consumers "
                f"dereference needs.<pool>.outputs.{field} and would break silently"
            )
    return findings


# ⛔ THE THIRD SHAPE (#11). The standard had exactly two categories -- `pool` (it IS the
# canonical just-akash runner pool) and `consumer` (it `uses:` that pool). A workflow that
# SPENDS MONEY ON AKASH LEASES WITHOUT CONSUMING THE CANONICAL POOL fits neither, so
# `--target-kind auto` calls it a consumer and reports "no canonical just-akash runner-pool
# reusable job found" -- a true statement about a pool it was never supposed to have.
#
# The honest move today is to point nothing at such a file, and then NOTHING JUDGES IT. A
# workflow that opens and closes leases is spending money; that is exactly what this standard
# should have an opinion about. df-cicd#1553 measured 484 ACT left in unclosed orders behind
# this shape.
#
# ⚠ THE CATEGORY MUST NOT BECOME AN ESCAPE HATCH. Declaring this kind suppresses the pool
# requirement, so a real consumer could silence a genuine finding by mislabelling itself. The
# declaration is CHECKED, not trusted: a file claiming it must show lease-lifecycle evidence,
# and one that shows none is REPORTED, not passed.
_LEASE_EVIDENCE = re.compile(
    r"(just-akash\s+close|akash\s+close|/v1/deployments/|\bdseq\b|close_deployment)",
    re.I,
)


def _spends_on_leases(document: dict[str, Any]) -> bool:
    """Does this workflow manage Akash lease lifecycle at all?

    Deliberately broad: the question is "is this the third shape", not "is its teardown
    correct" -- the teardown rules judge that, and they run regardless of target kind.
    """
    return bool(_LEASE_EVIDENCE.search(json.dumps(document, default=str)))


def check(document: dict[str, Any], target_kind: str = "auto") -> list[str]:
    findings: list[str] = []
    jobs = document.get("jobs") or {}
    pools = {
        name: job
        for name, job in jobs.items()
        if _text(job.get("uses")).startswith(POOL)
    }
    teardowns = {
        name: job
        for name, job in jobs.items()
        if _text(job.get("uses")).startswith(TEARDOWN)
    }

    # ⇒ RUN BEFORE THE POOL GATE, DELIBERATELY. Every teardown rule in this file lives
    # inside the `for pool_name, pool in pools.items()` loop below, so on a repo that does
    # not call the canonical reusable pool that loop is EMPTY and no teardown rule can
    # fire. Blazing-Back is such a repo, and it is where the leak happened. A rule placed
    # below would be correct and unreachable — the same defect shape this campaign exists
    # to remove, authored into the fix for it.
    findings.extend(_result_gated_teardowns(jobs))

    # ⇒ POOL MODE. Consumer mode is everything below and is unchanged; this branch only
    # ever engages for a document that is itself the canonical pool. `auto` errs toward
    # consumer mode, so an unrecognised file keeps today's behaviour exactly.
    # ⇒ LEASE-SPENDER MODE (#11). The teardown rules above have already run -- they sit
    # before the pool gate precisely so they fire without a pool. This branch only
    # declines to demand a pool the file was never meant to have.
    if target_kind == "lease-spender":
        if not _spends_on_leases(document):
            # ⛔ NOT a pass. A file declaring this kind with no lease-lifecycle evidence
            # is mislabelled, or is using the category to silence the pool finding.
            findings.append(
                "declared --target-kind lease-spender but no Akash lease lifecycle "
                "found (no close call, no dseq, no deployment delete) — this file is "
                "not the third shape and the declaration suppresses a real finding"
            )
        return findings

    if target_kind == "pool" or (
        target_kind == "auto" and not pools and _looks_like_the_canonical_pool(document)
    ):
        findings.extend(_check_pool_contract(document))
        return findings

    if not pools:
        # ⚠ Still returns here: everything below is pool-RELATIVE, and letting it run would
        # silently widen existing rules (the local-duplication check at the job loop starts
        # firing on every non-canonical repo). Pinned by the characterisation tests.
        findings.append("no canonical just-akash runner-pool reusable job found")
        return findings

    for name, job in jobs.items():
        uses = _text(job.get("uses"))
        if uses.startswith("./.github/workflows/akash-runner"):
            findings.append(
                f"{name}: local runner workflow duplicates the shared mechanism"
            )
        for step in job.get("steps") or []:
            body = _text(step.get("run"))
            if re.search(r"\bjust-akash\s+(?:destroy|close|close-all)\b", body) or (
                "close-deployment" in _text(step.get("uses"))
            ):
                findings.append(
                    f"{name}: local close logic bypasses canonical runner-teardown"
                )

    for pool_name, pool in pools.items():
        pool_ref = _ref(_text(pool.get("uses")))
        if not IMMUTABLE.fullmatch(pool_ref):
            findings.append(
                f"{pool_name}: just-akash ref {pool_ref!r} is not immutable semver/SHA"
            )

        pool_with = pool.get("with") or {}
        if not isinstance(pool_with, dict):
            findings.append(f"{pool_name}: with must be a mapping")
            pool_with = {}
        for field in ("runner-label", "tag-prefix", "github-org", "providers"):
            if not pool_with.get(field):
                findings.append(f"{pool_name}: missing required input {field}")

        provider_spec = pool_with.get("providers")
        if provider_spec:
            try:
                providers = json.loads(_text(provider_spec))
            except (TypeError, ValueError):
                findings.append(
                    f"{pool_name}: providers must be committed structured JSON"
                )
            else:
                preferred = {
                    item.get("address")
                    for item in providers
                    if isinstance(item, dict) and item.get("preferred")
                }
                excluded = {
                    item.get("address")
                    for item in providers
                    if isinstance(item, dict) and item.get("runner_deny")
                }
                if preferred != DF_PREFERRED:
                    findings.append(
                        f"{pool_name}: preferred providers must be exactly the three-provider DF fleet"
                    )
                if preferred & excluded:
                    findings.append(
                        f"{pool_name}: preferred providers overlap standing exclusions"
                    )
                if not excluded:
                    findings.append(
                        f"{pool_name}: providers has no standing runner_deny exclusions"
                    )

        consumers = {
            name
            for name, job in jobs.items()
            if f"needs.{pool_name}.outputs.runner-targets" in _text(job.get("runs-on"))
        }
        if not consumers:
            findings.append(f"{pool_name}: no work job consumes runner-targets")

        candidates = []
        needle = f"needs.{pool_name}.outputs.dseq"
        for teardown_name, teardown in teardowns.items():
            if needle in _text((teardown.get("with") or {}).get("dseq")):
                candidates.append((teardown_name, teardown))
        if len(candidates) != 1:
            findings.append(
                f"{pool_name}: expected exactly one canonical teardown for its DSEQ, found {len(candidates)}"
            )
            continue

        teardown_name, teardown = candidates[0]
        if _ref(_text(teardown.get("uses"))) != pool_ref:
            findings.append(
                f"{teardown_name}: pool and teardown just-akash refs differ"
            )
        if "always()" not in _text(teardown.get("if")):
            findings.append(f"{teardown_name}: teardown must use if: always()")
        missing_needs = {pool_name, *consumers} - _needs(teardown)
        if missing_needs:
            findings.append(
                f"{teardown_name}: teardown must need pool and every consumer: missing {sorted(missing_needs)}"
            )

        teardown_with = teardown.get("with") or {}
        for field in ("runner-label", "tag-prefix", "github-org"):
            if teardown_with.get(field) != pool_with.get(field):
                findings.append(
                    f"{teardown_name}: {field} must exactly match {pool_name}"
                )

        pool_credentials = pool.get("secrets") or {}
        teardown_credentials = teardown.get("secrets") or {}
        if not isinstance(pool_credentials, dict) or not isinstance(
            teardown_credentials, dict
        ):
            findings.append(
                f"{teardown_name}: secrets: inherit is not allowed; map the three credentials explicitly"
            )
            continue
        for credential_field in ("AKASH_API_KEY", "AKASH_API_KEYS", "GH_RUNNER_PAT"):
            # Report only the schema field name, never either credential expression/value.
            if pool_credentials.get(credential_field) != teardown_credentials.get(
                credential_field
            ):
                findings.append(
                    f"{teardown_name}: credential field {credential_field} must match {pool_name}"
                )

    return findings


def main() -> int:
    parser = argparse.ArgumentParser()
    cli_aliases.add_workflow_file(parser)
    parser.add_argument(
        "--target-kind",
        choices=("auto", "consumer", "pool", "lease-spender"),
        default="auto",
        help=(
            "What the workflow file IS. 'consumer' calls the canonical pool; 'pool' is "
            "the canonical pool itself. 'auto' (default) picks consumer unless the file "
            "declares workflow_call with an AKASH_API_KEY secret."
        ),
    )
    args = parser.parse_args()
    try:
        document = yaml.safe_load(args.workflow.read_text()) or {}
    except (OSError, yaml.YAMLError) as exc:
        print(f"Akash runner standard: could not read workflow: {exc}", file=sys.stderr)
        return 2
    findings = check(document, target_kind=args.target_kind)
    # ⚠ The guidance is printed BESIDE the finding, never folded into it: the finding
    # string is pinned verbatim by the characterisation tests in
    # test_teardown_not_result_gated.py and test_no_vacuous_pass.py, and rewording it to
    # be friendlier would silently unpin those. What was wrong in just-akash#200 was not
    # the wording — it was that the only mode available judged the wrong thing.
    if args.target_kind == "auto" and findings == [
        "no canonical just-akash runner-pool reusable job found"
    ]:
        print(
            "Akash runner standard: no job in this file `uses:` the canonical pool. If "
            "this file IS the canonical pool rather than a consumer of it, re-run with "
            "--target-kind pool to judge the pool's own contract instead."
        )
    for finding in findings:
        print(f"::error title=Akash runner standard::{finding}")
    if findings:
        print(f"Akash runner standard: FAIL ({len(findings)} finding(s))")
        return 1
    print("Akash runner standard: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
