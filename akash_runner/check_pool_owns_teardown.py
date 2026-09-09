#!/usr/bin/env python3
"""A reusable resource producer owns rollback until successful handoff.

A workflow_call output transfers the resource to caller jobs only after this reusable
workflow finishes. Internal unconditional teardown destroys it before those jobs can
start. Roll back failed/cancelled provisioning; successful handoff leaves normal
cleanup to the caller after every consumer finishes. Identity publication and an
independent cleanup backstop are still needed when provisioning is interrupted.
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


def rollback_condition(condition: Any, producer: str) -> bool:
    """Recognize the bounded failure/cancellation contract, without permissive parsing."""
    expression = _text(condition).strip()
    if expression.startswith("${{") and expression.endswith("}}"):
        expression = expression[3:-2].strip()
    return bool(
        re.fullmatch(
            rf"always\s*\(\s*\)\s*&&\s*needs\.{re.escape(producer)}\.result\s*!=\s*(['\"])success\1",
            expression,
        )
    )


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
        match = re.fullmatch(
            r"\s*\$\{\{\s*jobs\.([A-Za-z0-9_-]+)\.outputs\.dseq\s*\}\}\s*", expression
        )
        found[name] = match.group(1) if match else ""
    return found


def _receives_identity(job: dict[str, Any], producer: str, identity: str) -> bool:
    return bool(
        re.fullmatch(
            rf"\s*\$\{{\{{\s*needs\.{re.escape(producer)}\.outputs\.{re.escape(identity)}\s*\}}\}}\s*",
            _text((job.get("with") or {}).get(identity)),
        )
    )


def rollback_jobs(document: dict[str, Any]) -> set[str]:
    """Names justified by resource-output wiring and rollback semantics, never a name allowlist."""
    jobs = document.get("jobs") or {}
    return {
        name
        for producer in _published_identities(document).values()
        for name, job in jobs.items()
        if producer in jobs
        and producer in _needs(job)
        and rollback_condition(job.get("if"), producer)
        and _receives_identity(job, producer, "dseq")
    }


def check(document: dict[str, Any]) -> list[str]:
    identities = _published_identities(document)
    if not identities:
        return []
    jobs = document.get("jobs") or {}
    findings: list[str] = []
    for identity, producer in sorted(identities.items()):
        if not producer or producer not in jobs:
            findings.append(
                f"{identity}: lifecycle output must identify an existing producer job"
            )
            continue
        teardowns = [
            name
            for name, job in jobs.items()
            if TEARDOWN_JOB.search(name)
            or "runner-teardown.yml" in _text(job.get("uses"))
        ]
        if not teardowns:
            findings.append(
                f"publishes lifecycle identity {identity!r} but contains no teardown job for failed/cancelled provisioning"
            )
            continue
        for name in sorted(teardowns):
            job = jobs.get(name) or {}
            if producer not in _needs(job):
                findings.append(
                    f"{name}: rollback must need {producer!r}, the resource producer"
                )
            if not rollback_condition(job.get("if"), producer):
                findings.append(
                    f"{name}: internal rollback must use always() && needs.{producer}.result != 'success'; "
                    "successful handoff must survive until caller consumers finish"
                )
            if not _receives_identity(job, producer, identity):
                findings.append(
                    f"{name}: rollback must receive needs.{producer}.outputs.{identity}"
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
