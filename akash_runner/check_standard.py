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

POOL = "Digital-Frontier-LDA/just-akash/.github/workflows/runner-pool.yml@"
TEARDOWN = "Digital-Frontier-LDA/just-akash/.github/workflows/runner-teardown.yml@"
IMMUTABLE = re.compile(r"(?:v\d+\.\d+\.\d+|[0-9a-f]{40})$")
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


def check(document: dict[str, Any]) -> list[str]:
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
    parser.add_argument("workflow", type=Path)
    args = parser.parse_args()
    try:
        document = yaml.safe_load(args.workflow.read_text()) or {}
    except (OSError, yaml.YAMLError) as exc:
        print(f"Akash runner standard: could not read workflow: {exc}", file=sys.stderr)
        return 2
    findings = check(document)
    for finding in findings:
        print(f"::error title=Akash runner standard::{finding}")
    if findings:
        print(f"Akash runner standard: FAIL ({len(findings)} finding(s))")
        return 1
    print("Akash runner standard: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
