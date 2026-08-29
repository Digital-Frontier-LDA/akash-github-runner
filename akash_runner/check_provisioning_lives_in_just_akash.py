#!/usr/bin/env python3
"""Runner provisioning workflows live ONLY in just-akash — df-wiki §1, made checkable.

⛔ THE GAP THIS RULE CLOSES (df-wiki#222, gap G1). `content/platform/akash-github-runners.md`
§1 mandates:

    Runner provisioning workflows live only in `just-akash`, consumed via `uses:` at a
    pinned tag. … A repo-local `akash-runner.yml` is a defect, not a customisation.

Its opening sentence — "Two repos independently grew an `akash-runner.yml`" — is still true
on both mains today, and the obvious explanation is refuted: it is NOT that they cannot
adopt. Blazing-Back runs this conformance suite today, cross-org, at pin a49af714. A repo
can run every rule the suite has, at main, and still violate the standard's first mandate —
because nothing checked it. The gap was in the rule set, not in consumer uptake.

⛔ THE DETECTION IS CAPABILITY, NOT FILENAME. A rule keyed to the string `akash-runner.yml`
is disarmed by a rename, and the defect already ships under other names. What this rule
matches is runner-REGISTRATION machinery in comment-stripped `run:` text — the discriminator
`check_dereg_backstop` measured across the fleet (its CREATES_REGISTRATIONS, imported, so
the two rules cannot drift apart on what "creating registrations" means).

MEASURED 2026-08-29 across the six origin/main trees, run-text only, comments stripped:

    repo                                        files carrying the machinery
    Borduas-Holdings/Blazing-Back @a5eb173e     akash-runner.yml, runner-time-to-ready.yml
    Borduas-Holdings/blazing      @1083b71e     akash-ci.yml, akash-integration-new.yml,
                                                akash-runner.yml
    Digital-Frontier-LDA/just-akash @4d8dc9b    runner-pool.yml   ← THE PUBLISHER, exempt
    Digital-Frontier-LDA/df-cicd  @1d2e7fe      none (its reaper only DELETEs)
    Digital-Frontier-LDA/akash-lease-core       none
    Digital-Frontier-LDA/akash-github-runner    none

⚠ TWO FALSE-POSITIVE SHAPES ARE MEASURED AND EXCLUDED, both by matching against
`workflow_corpus` comment-stripped code rather than raw text:

  1. Blazing-Back ci-pr.yml names both runner images inside full-line COMMENTS in a run
     block ("# names a recognized runner repository (myoung34/github-runner, …)"). It
     provisions nothing. A rule reading comments reds a consumer's main CI file for prose.
  2. blazing's akash-runner-registration-reaper.yml delegates to scripts/
     akash-runner-reaper.sh, whose only marker hit is itself a COMMENT ("# RUNNER_NAME_PREFIX
     values misses that, which is how it got in."). Delegation is followed (the dereg rule
     was once blind to it), but the delegated text is comment-stripped too.

⚠ THE PUBLISHER EXEMPTION IS IDENTITY, NOT STRUCTURE. blazing's repo-local
`akash-runner.yml` is `workflow_call` today — if being callable exempted a repo, the exact
file the standard was written about would pass. (df-wiki#222 records the open question of
whether the mandate should narrow for a repo-local reusable others consume; until the
standard says so, this rule reports it.) The one repo allowed to HOST the machinery is
Digital-Frontier-LDA/just-akash, identified by repo slug:

  * In CI the slug comes from GITHUB_REPOSITORY, which the platform sets and a workflow
    author CANNOT override (GITHUB_* is reserved) — so the exemption is verified there,
    not claimed. The conformance action passes it explicitly (`--repo "$GITHUB_REPOSITORY"`)
    so the dependency is visible at the call site.
  * Locally, pass --repo yourself; that value is a claim, which is fine for measurement
    and worthless for evasion — a consumer evading in CI would have to forge the platform.
  * UNKNOWN identity is fail-closed: machinery with no slug is reported. The common case
    is a consumer; the publisher's own CI always has the slug.

⚠ KNOWN LIMITS, stated rather than papered over:

  * A workflow that deploys a runner SDL kept in a SEPARATE FILE (`just-akash deploy
    --sdl runner.sdl.yaml` with the image/env living outside the workflow) leaves no
    marker in run text. No repo in the fleet does this today (all five machinery files
    embed the SDL inline — measured); if one appears, extend the corpus to the SDL file,
    don't loosen the marker.
  * An unreadable delegated script is reported only where the workflow ALREADY shows
    machinery (runner-adjacent). Unconditional reporting was measured at 4 false findings
    across two repos (the dereg rule's count). The residual hole — a clean-looking
    workflow whose entire payload sits in an unreadable script — is accepted and stated.
  * The PIN FORM of a compliant `uses:` (the wiki says "pinned tag"; the dereg rule
    demands 40-hex for the reaper, because a tag moves) is deliberately OUT OF SCOPE.
    Resolving that disagreement is a standards-page decision; this rule's job is the
    first mandate's other half — WHERE the machinery lives.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import sys
from pathlib import Path
from typing import Any

import yaml

# The marker set and the workflow-population floor are IMPORTED, not re-derived:
# check_dereg_backstop measured both across this fleet (its docstring carries the table),
# and a second copy would be two sources of truth for one measured instrument.
# Flat imports, not `akash_runner.` — CI invokes this file as a script with
# sys.path[0] set to this directory, where the package prefix does not resolve.
from check_dereg_backstop import (
    CREATES_REGISTRATIONS,
    DELEGATES_TO_SCRIPT,
    _workflow_documents,
)
from conformance_exit import not_judgeable
from workflow_corpus import run_blocks, strip_comments

# The one repo the mandate allows to HOST the machinery. Compared lower-cased: GitHub
# treats repo slugs case-insensitively, and GITHUB_REPOSITORY's case is the platform's.
PUBLISHER = "digital-frontier-lda/just-akash"


def _is_publisher(repo: str | None) -> bool:
    return repo is not None and repo.lower() == PUBLISHER


def _delegated_scripts(body: str, workflows: Path) -> tuple[list[tuple[str, str]], list[str]]:
    """(readable (relpath, text), unreadable relpaths) for scripts a run-block hands off to.

    Same resolution contract as check_dereg_backstop._delegated_text — repo-root-relative,
    absolute paths and `..` excluded (they name the runner HOST, not this tree), unreadable
    returned as a problem rather than skipped. Per-script granularity so a finding can name
    the file that actually carries the machinery. The guards mirror that function's
    docstring; if its semantics move, move these too.
    """
    root = workflows.parent.parent
    readable: list[tuple[str, str]] = []
    unreadable: list[str] = []
    for match in DELEGATES_TO_SCRIPT.finditer(body):
        rel = match.group("path") or match.group("rel") or ""
        if rel.startswith("./"):
            rel = rel[2:]
        if not rel or rel.startswith("/") or ".." in pathlib.PurePosixPath(rel).parts:
            continue
        try:
            readable.append((rel, (root / rel).read_text()))
        except OSError:
            unreadable.append(rel)
    return readable, unreadable


def check_directory(workflows: Path, repo: str | None = None) -> list[str]:
    findings: list[str] = []
    publisher = _is_publisher(repo)

    for path in sorted(workflows.glob("*.yml")) + sorted(workflows.glob("*.yaml")):
        try:
            blocks = run_blocks(path)
        except (OSError, yaml.YAMLError) as exc:
            # ⚠ Unreadable is not clean: a provisioning workflow that failed to parse must
            # not read as its own absence.
            findings.append(
                f"{path.name}: could not be read, so it was NOT checked: {exc}"
            )
            continue

        hits: list[tuple[int, str, str]] = []
        for block in blocks:
            match = CREATES_REGISTRATIONS.search(block.code)
            if match is not None:
                line = block.start_line + block.code[: match.start()].count("\n")
                hits.append((line, block.job_id, match.group(0)))

        body = "\n".join(block.script for block in blocks)
        delegated, unreadable = _delegated_scripts(body, workflows)
        delegated_hits = [
            (rel, CREATES_REGISTRATIONS.search(strip_comments(text)))
            for rel, text in delegated
        ]
        delegated_hits = [(rel, m) for rel, m in delegated_hits if m is not None]

        if publisher:
            # The machinery living HERE is the standard, not the defect. Parse-failure
            # findings above still stand — an unreadable publisher workflow is not checked.
            continue

        for line, job_id, marker in hits:
            findings.append(
                f"{path.name}:{line}: job '{job_id}' runs runner-registration machinery "
                f"({marker}) — df-wiki content/platform/akash-github-runners.md §1: runner "
                f"provisioning workflows live ONLY in Digital-Frontier-LDA/just-akash, "
                f"consumed via job-level `uses:` at a pinned ref. A repo-local provisioning "
                f"workflow is a defect, not a customisation — move the mechanism into "
                f"just-akash and push the differences into `with:` inputs (provider list, "
                f"pool size, tag prefix are POLICY; the workflow is MECHANISM)."
            )
        for rel, match in delegated_hits:
            findings.append(
                f"{path.name}: delegates to {rel}, which runs runner-registration "
                f"machinery ({match.group(0)}) — the same §1 mandate applies; the machinery "
                f"being one hop away in a script changes nothing."
            )
        if unreadable and (hits or delegated_hits):
            findings.append(
                f"{path.name}: shows runner-registration machinery AND delegates to "
                f"{', '.join(repr(r) for r in unreadable)}, which could not be read — so "
                f"it may hide further provisioning this check cannot see. Unreadable is "
                f"not empty."
            )
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("workflows", type=Path, help="a .github/workflows directory")
    parser.add_argument(
        "--repo",
        default=None,
        help=(
            "repo slug (org/name) of the tree being judged. Default: GITHUB_REPOSITORY "
            "from the environment — platform-set in CI, where it cannot be overridden. "
            "Pass it explicitly only for local measurement."
        ),
    )
    args = parser.parse_args(argv)
    if not args.workflows.is_dir():
        print(f"Provisioning home: not a directory: {args.workflows}", file=sys.stderr)
        return 2
    repo = args.repo if args.repo is not None else os.environ.get("GITHUB_REPOSITORY")
    matched = len(list(args.workflows.glob("*.yml"))) + len(
        list(args.workflows.glob("*.yaml"))
    )
    examined = len(_workflow_documents(args.workflows))
    if examined == 0:
        # ⛔ NON-VACUITY FLOOR (same incident as the dereg rule's): a wrong path or a
        # checkout that omitted .github yields an empty population, and "nothing to check"
        # must not read as "complies". Exit NOT_JUDGEABLE (3), not 1: an empty population
        # is not a defect in the repo, and a fleet sweep must be able to tell the
        # difference without reading prose.
        print(
            f"Provisioning home: FAIL — found 0 WORKFLOW documents under {args.workflows} "
            f"({matched} yaml file(s) matched, none declaring `on:` or `jobs:`). "
            "A pass over an empty population is not compliance; check the path.",
            file=sys.stderr,
        )
        return not_judgeable(
            "check_provisioning_lives_in_just_akash.py",
            "the rule observed nothing — see the message above.",
        )
    findings = check_directory(args.workflows, repo=repo)
    for finding in findings:
        print(f"::error title=Provisioning home::{finding}")
    if findings:
        print(f"Provisioning home: FAIL ({len(findings)} finding(s))")
        return 1
    print(f"Provisioning home: PASS — {examined} workflow file(s) examined")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
