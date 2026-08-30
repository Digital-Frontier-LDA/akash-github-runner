#!/usr/bin/env python3
"""A repo that spends on Akash must ADOPT the canonical escrow reaper, not merely have one.

⛔ THE DEFECT THIS EXISTS FOR, AND IT IS NOT "A REPO HAS NO REAPER". Measured 2026-08-30:

    repo                       escrow reaper             scheduled?          closes on schedule?
    Blazing-Back               cleanup-stale-akash.yml   yes, 0 */6          NO
    just-akash                 cleanup-stale.yml         yes, 23 0,6,12,18   NO

BOTH had a reaper. BOTH ran on a 6h cron. NEITHER closed anything, and the two were
independently written with different ownership vocabularies. 20 runner leases sat 14-21h
through four scheduled runs that each reported them; a hand dispatch then closed 20/20 and
returned 109.11 -> 233.54 ACT, lifting the concurrency budget from 6 runs to 14 against ~10
in flight. The CI that was blocked was blocked on escrow those crons had already found.

⇒ So "has a reaper" is the wrong predicate — it was TRUE of both repos while the leak ran.
This checks ADOPTION of the shared one, which is the property that actually converges the
two ownership predicates.

⛔ AND ADOPTION IS EXACTLY THE RUNG THAT FAILS HERE. `reusable-stale-runner-reaper.yml` has
been canonical in this repo since 2026-08-23 and, a week later, NEITHER consumer calls it:
just-akash points at df-cicd's copy (internal visibility, unreachable cross-org, and GitHub
reports that as "not found" rather than "forbidden"), and Blazing-Back calls nothing. A
reusable workflow with no callers is a file, not a standard. This checker is what makes the
difference observable.

⚠ SCOPE. Only repos that CREATE Akash deployments are in scope. A repo that merely reads
them has nothing to leak, and demanding a reaper of it would be a rule that fails on
correct code — the shape `check_reaper_schedule.py` already refuses for `workflow_call`
per-run teardowns.
"""

from __future__ import annotations

import argparse

import _cli
import re
from pathlib import Path

CANONICAL = "Digital-Frontier-LDA/akash-github-runner/.github/workflows/reusable-akash-escrow-reaper.yml"

# A caller must pin by 40-hex SHA. A branch or tag ref resolves at RUN time, so the closing
# logic can change under a consumer that changed nothing — the same trap the workflow's own
# `just-akash-ref` input refuses a default for.
ADOPTION = re.compile(
    r"uses:\s*" + re.escape(CANONICAL) + r"@(?P<ref>[A-Za-z0-9._/-]+)",
)
SHA40 = re.compile(r"^[0-9a-f]{40}$")

# Evidence that a repo creates deployments at all. Deliberately the CREATE verbs only:
# `balance`, `list` and `tag` read or annotate and leak nothing.
CREATES = re.compile(r"just-akash\s+deploy\b|just_akash\.deploy\b|deploy_custom_sdl\b")


def _executable(text: str) -> str:
    """The workflow with COMMENT LINES STRIPPED.

    ⛔ A COMMENT IS NOT EVIDENCE, IN EITHER DIRECTION. Scanning raw YAML let a comment
    decide the verdict twice over: `# uses: <canonical>@<sha>` in a note would have counted
    as an ADOPTER and passed a repo with no caller at all, and a `just-akash deploy` quoted
    in a comment would have pulled a repo that creates nothing INTO scope.

    ⚠ This is the third instance of the same class found in one day — a rule keyed to a
    quotable string retargets onto the prose describing it, and a guard whose own docstring
    quotes its pattern can never fail. Stripping is line-based on purpose: a YAML parse would
    also discard the `uses:` lines this rule reads when a workflow fails to parse, turning an
    unparseable file into a silent pass.
    """
    return "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )


def audit(d: Path) -> tuple[list[str], bool]:
    """Return (findings, in_scope) for one `.github/workflows` directory."""
    files = sorted(d.glob("*.yml")) + sorted(d.glob("*.yaml"))
    if not files:
        # ⚠ An empty directory is NOT a clean repo. Judging nothing and returning 0 is the
        # shape that makes a rule look adopted everywhere it was never actually run.
        return ([f"no workflow files under {d} — cannot judge, refusing to pass"], True)

    texts = {p: _executable(p.read_text(encoding="utf-8", errors="replace")) for p in files}
    creators = [p.name for p, t in texts.items() if CREATES.search(t)]
    if not creators:
        return ([], False)

    findings: list[str] = []
    adopters: list[str] = []
    for p, t in texts.items():
        for m in ADOPTION.finditer(t):
            adopters.append(p.name)
            ref = m.group("ref")
            if not SHA40.match(ref):
                findings.append(
                    f"{p.name}: adopts the canonical escrow reaper but pins `@{ref}`, not a "
                    "40-hex SHA. A branch/tag ref resolves at run time, so the closing logic "
                    "can change under a consumer that changed nothing."
                )
    if not adopters:
        findings.append(
            f"creates Akash deployments ({', '.join(sorted(creators))}) but no workflow calls "
            f"`{CANONICAL}`. A repo-local reaper does NOT satisfy this: both consumers had one "
            "on a 6h cron and neither closed anything."
        )
    return (findings, True)


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

    findings, in_scope = audit(d)
    label = d.resolve().parent.parent.name
    if not in_scope:
        # ⚠ NOT-APPLICABLE IS PRINTED, NEVER SILENT. A rule that skips quietly is
        # indistinguishable from one that passed, and this repo has already shipped a checker
        # that reported NOT APPLICABLE on the very repo it was written for.
        print(f"NOT APPLICABLE: {label} creates no Akash deployments — nothing to leak.")
        return 0
    if findings:
        for f in findings:
            print(f"::error::{label}: {f}")
        return 1
    print(f"OK: {label} adopts {CANONICAL} at a pinned SHA.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
