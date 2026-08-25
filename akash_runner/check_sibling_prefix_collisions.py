#!/usr/bin/env python3
"""One repo's reaper must not delete another repo's runners.

⛔ THIS CANNOT BE A PER-CONSUMER RULE, AND SAYING SO IS THE POINT. Measured 2026-08-24:

    Blazing-Back emits   akash-   df-core-
    blazing      emits   akash-   akash-ci-   akash-integration-

BOTH repos emit `akash-`. So from inside Blazing-Back, a filter of `akash-` selects a
prefix it GENUINELY OWNS — and also every `akash-ci-*` and `akash-integration-*`
registration belonging to blazing, because they share the org (`Borduas-Holdings`).
Nothing inside one repo distinguishes the two. The collision is visible only when both
repos' prefixes are in view.

⇒ A per-repo checker asserting "no sibling collision" would be claiming a property it
structurally cannot evaluate — the defect this standard exists to remove. So this is an
ORG-LEVEL AUDIT over several checkouts, and it is not wired into the per-consumer
conformance action.

⛔ IT IS NOT HYPOTHETICAL. `Blazing-Back/stale-runner-reaper.yml:56` records it in the past
tense: "`akash-` is shared with Borduas-Holdings/blazing, so it would select that repo's
registrations too — WHICH THIS REPO'S INLINE REAPER WAS IN FACT DOING." Narrowing to
`df-core-` was the fix.

⚠ AND A COMMENT DID NOT PREVENT THE RECURRENCE. The same file, two lines later, warns about
the identical trap one prefix over — "NOT bare `df-`: that is a proper prefix of df-flow-
and df-cicd-" — and `akash-` being a proper prefix of `akash-ci-` and `akash-integration-`
still had to be rediscovered. A warning written against one prefix does not generalise
itself to the next one. That is a comment failing at the only job a comment has, and it is
why this is a rule.

⚠ THE POPULATION IS DERIVED, NOT RESTATED. Every prefix here is read out of the repos on
disk — emitted prefixes from the producers, filters from the backstops. There is no literal
list of known prefixes to fall out of date. What IS bounded is the set of repos handed in:
a repo registering into the same org that nobody passed to this checker is invisible, and
that limit is reported rather than left implied.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys
from pathlib import Path
from typing import Any, NamedTuple

import yaml

EMITS_PREFIX = re.compile(r"RUNNER_NAME_PREFIX=([A-Za-z0-9._-]*)")
NAME_FILTER_JQ = re.compile(r"\.name\s*\|\s*startswith\(\s*[\"']([^\"']*)[\"']\s*\)")
NAME_FILTER_INPUT = re.compile(
    r"(?:name-prefixes|PREFIXES)\s*[:=]\s*[\"']?([A-Za-z0-9._,-]+)"
)
ORG_DECL = re.compile(
    r"(?:ORG|ORG_NAME|github-org)\s*[:=]\s*[\"']?([A-Za-z][A-Za-z0-9-]*)"
)
DELEGATES_TO_SCRIPT = re.compile(
    r"(?:^|\||&|;)\s*(?:bash|sh|source|\.)\s+(?P<path>[A-Za-z0-9_./-]+\.sh)\b"
    r"|(?:^|\||&|;)\s*(?P<rel>\./[A-Za-z0-9_./-]+\.sh)\b",
    re.M,
)


class Repo(NamedTuple):
    name: str
    orgs: frozenset[str]
    emits: frozenset[str]
    filters: frozenset[str]


# Keys that appear in an input DECLARATION and are never an org or a prefix.
_YAML_SCHEMA_WORDS = frozenset(
    {"description", "default", "required", "type", "string", "boolean", "number"}
)


def _values_and_envs(document: dict[str, Any]) -> list[tuple[str, str]]:
    """(with-values, env-values) per job — the places a caller supplies a VALUE.

    Declarations under `on.workflow_call.inputs` are deliberately excluded: they describe
    the parameter, they do not set it.
    """
    out: list[tuple[str, str]] = []
    for job in (document.get("jobs") or {}).values():
        if not isinstance(job, dict):
            continue
        with_block = job.get("with") if isinstance(job.get("with"), dict) else {}
        env_parts = [job.get("env") if isinstance(job.get("env"), dict) else {}]
        for step in job.get("steps") or []:
            if isinstance(step, dict) and isinstance(step.get("env"), dict):
                env_parts.append(step["env"])
        values = "\n".join(f"{k}: {v}" for k, v in with_block.items())
        envs = "\n".join(f"{k}: {v}" for part in env_parts for k, v in part.items())
        out.append((values, envs))
    return out


def _run_text(document: dict[str, Any]) -> str:
    parts: list[str] = []
    for job in (document.get("jobs") or {}).values():
        if not isinstance(job, dict):
            continue
        for step in job.get("steps") or []:
            if isinstance(step, dict):
                parts.append(str(step.get("run") or ""))
    return "\n".join(parts)


def _delegated_text(body: str, workflows: Path) -> str:
    root = workflows.parent.parent
    out: list[str] = []
    for match in DELEGATES_TO_SCRIPT.finditer(body):
        rel = match.group("path") or match.group("rel") or ""
        if rel.startswith("./"):
            rel = rel[2:]
        if not rel or rel.startswith("/") or ".." in pathlib.PurePosixPath(rel).parts:
            continue
        try:
            out.append((root / rel).read_text())
        except OSError:
            continue
    return "\n".join(out)


def describe(repo_root: Path) -> Repo | None:
    """Derive one repo's orgs, emitted prefixes and backstop filters from its workflows."""
    workflows = repo_root / ".github" / "workflows"
    if not workflows.is_dir():
        return None
    emits: set[str] = set()
    filters: set[str] = set()
    orgs: set[str] = set()
    for path in sorted(workflows.glob("*.yml")) + sorted(workflows.glob("*.yaml")):
        try:
            document = yaml.safe_load(path.read_text()) or {}
        except (OSError, yaml.YAMLError):
            continue
        if not isinstance(document, dict):
            continue
        body = _run_text(document)
        full = body + "\n" + _delegated_text(body, workflows)
        emits |= {p for p in EMITS_PREFIX.findall(body) if p}
        filters |= set(NAME_FILTER_JQ.findall(full))
        # ⛔ STRUCTURAL, NOT A REGEX OVER DUMPED YAML. Scanning `yaml.dump(document)` cannot
        # tell an input's DECLARATION from a caller's VALUE: `name-prefixes:` under
        # `inputs:` has a `description:` child, and the regex read that child as a filter —
        # so df-cicd, which declares the input and passes no value, acquired a filter of
        # 'description'. Same class for ORG: `default:` and `description:` were read as org
        # names. A rule that computes from noise reports whatever the noise happens to say,
        # which is the trap #157 warns about, here in the rule that warns about it.
        for value, env in _values_and_envs(document):
            # ⚠ BOTH `with:` AND `env:`. The reaper's own filter lives in a STEP's env
            # (`PREFIXES: df-core-`), not in a `with:` block — searching only `with:` read
            # the filter from a DIFFERENT workflow's per-run dereg instead, and a simulated
            # widening of the real reaper produced no change at all. The rule looked sound
            # and was reading the wrong file.
            for scope in (value, env):
                for raw in NAME_FILTER_INPUT.findall(scope):
                    filters |= {p for p in raw.split(",") if p}
            orgs |= {o for o in ORG_DECL.findall(env) if o not in _YAML_SCHEMA_WORDS}
        for raw in NAME_FILTER_INPUT.findall(full):
            filters |= {p for p in raw.split(",") if p}
        orgs |= {o for o in ORG_DECL.findall(full) if o not in _YAML_SCHEMA_WORDS}
    return Repo(repo_root.name, frozenset(orgs), frozenset(emits), frozenset(filters))


def check(repos: list[Repo]) -> list[str]:
    """Collisions in BOTH directions, between distinct repos sharing an org."""
    findings: list[str] = []
    for reaper in repos:
        for victim in repos:
            if reaper.name == victim.name:
                continue
            shared = reaper.orgs & victim.orgs
            if not shared:
                continue
            for flt in sorted(reaper.filters):
                for emitted in sorted(victim.emits):
                    # A reaper selects a runner when the runner's NAME starts with the
                    # filter. So the filter captures the sibling exactly when the
                    # sibling's prefix begins with it.
                    if emitted.startswith(flt):
                        findings.append(
                            f"{reaper.name} reaps {flt!r} and {victim.name} emits "
                            f"{emitted!r} into the same org "
                            f"({', '.join(sorted(shared))}): {reaper.name}'s backstop "
                            f"deletes {victim.name}'s registrations. Narrow the filter to a "
                            f"prefix {reaper.name} alone owns, or rename the producer — do "
                            f"NOT widen the filter."
                        )
    return findings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "repos", type=Path, nargs="+", help="repo roots to audit together"
    )
    args = parser.parse_args()
    described = [r for r in (describe(p) for p in args.repos) if r is not None]
    skipped = [p.name for p in args.repos if describe(p) is None]
    for name in skipped:
        print(
            f"::warning title=Sibling prefixes::{name}: no .github/workflows — not audited"
        )
    # ⛔ NON-VACUITY. A collision needs at least two repos in view; one repo can never
    # produce a finding, so a PASS over fewer than two is an answer to a question nobody
    # asked. See akash_runner/test_no_vacuous_pass.py for why this floor exists at all.
    if len(described) < 2:
        print(
            f"Sibling prefixes: FAIL — audited {len(described)} repo(s); a collision is a "
            "relation BETWEEN repos and cannot be detected in fewer than two. Pass every "
            "repo that registers into the shared org.",
            file=sys.stderr,
        )
        return 1
    findings = check(described)
    for finding in findings:
        print(f"::error title=Sibling prefixes::{finding}")
    if findings:
        print(f"Sibling prefixes: FAIL ({len(findings)} collision(s))")
        return 1
    print(
        f"Sibling prefixes: PASS — {len(described)} repo(s) audited "
        f"({', '.join(r.name for r in described)}); "
        f"{sum(len(r.emits) for r in described)} emitted prefix(es), "
        f"{sum(len(r.filters) for r in described)} filter(s) compared. "
        "⚠ A repo registering into the same org that was NOT passed here is invisible."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
