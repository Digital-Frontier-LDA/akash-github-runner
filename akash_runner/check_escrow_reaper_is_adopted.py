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
import subprocess
from pathlib import Path

CANONICAL = "Digital-Frontier-LDA/akash-github-runner/.github/workflows/reusable-akash-escrow-reaper.yml"

# A caller must pin by 40-hex SHA. A branch or tag ref resolves at RUN time, so the closing
# logic can change under a consumer that changed nothing — the same trap the workflow's own
# `just-akash-ref` input refuses a default for.
ADOPTION = re.compile(
    r"uses:\s*" + re.escape(CANONICAL) + r"@(?P<ref>[A-Za-z0-9._/-]+)",
)
SHA40 = re.compile(r"^[0-9a-f]{40}$")

# The prefix a caller declares it will sweep. `with:` block, so a plain key scan suffices.
PREFIX_INPUT = re.compile(r"^\s*placement-prefix:\s*[\"']?([^\"'\s#]+)", re.M)

# The module that IS the mechanism. A repo shipping it does not consume the reusable
# workflow — it is what the reusable workflow installs.
MECHANISM = Path("just_akash") / "cleanup_stale.py"

# How the mechanism repo must invoke it instead. This is an OBLIGATION, not a hole: without
# it "ships the mechanism" would be a free pass, and the repo most able to reap would be the
# one least required to.
MECHANISM_INVOCATION = re.compile(r"just_akash\.cleanup_stale")

# Evidence that a repo creates deployments at all. Deliberately the CREATE verbs only:
# `balance`, `list` and `tag` read or annotate and leak nothing.
# Evidence that a repo creates deployments at all. Deliberately the CREATE verbs only:
# `balance`, `list` and `tag` read or annotate and leak nothing.
CREATES = re.compile(r"just-akash\s+deploy\b|just_akash\.deploy\b|deploy_custom_sdl\b")

# ⛔ THE LITERAL IS NOT HOW EVERY REPO SPELLS IT, AND THE MISS IS SILENT AND TOTAL.
# Measured 2026-09-03: `Borduas-Holdings/blazing` held 85 active deployments and this rule
# reported "creates no Akash deployments — nothing to leak". It installs the CLI into a
# variable and invokes that:
#
#     akash-runner.yml:442   JA="uvx --from git+https://…/just-akash@main just-akash"
#     akash-runner.yml:463   $JA deploy --sdl /tmp/sdl.yaml --bid-wait 60 …
#
# ⚠ AND THE CONSEQUENCE OUTLIVED THE ADOPTION. blazing adopted the reaper the same day;
# deleting that adoption again produced the IDENTICAL verdict, rc=0. So the repo this rule
# most concerns had no guard either before or after — "a ratified mechanism with zero
# executions", inside the guard written to prevent it.
#
# ⛔ WHY NOT A BARE `\$VAR deploy`. That matches `$KUBECTL deploy` and `$HELM deploy`, and
# this rule is ENFORCING: a repo deploying something that is not Akash would be pulled into
# scope and failed for not adopting an Akash escrow reaper. So the variable must be shown to
# HOLD the CLI first. Two statements, and both must be present in the same workflow.
_HOLDS_CLI = re.compile(r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)=\(?[^\n]*\bjust-akash\b")


def _invokes(name: str) -> re.Pattern[str]:
    """`$JA deploy`, `${JA} deploy`, and the array form this fleet also writes."""
    return re.compile(
        r"\$\{?" + re.escape(name) + r"\}?\s+deploy\b"
        r"|\"\$\{" + re.escape(name) + r"\[@\]\}\"\s+deploy\b"
    )


# ⛔ DELEGATED CREATION IS STILL CREATION. A repo whose only deployments come from
# `runner-pool.yml` spends real escrow and leaks it when the pool's own teardown does not
# run — which is the case this reaper is the backstop for. Measured: no repo in the fleet
# enters scope by this route ALONE today (blazing also matches the variable form,
# just-akash also matches the literal), so it widens the rule's reasoning without widening
# today's population.
_DELEGATES_CREATION = re.compile(r"uses:\s*\S+/runner-pool\.yml@")


def _creates(text: str) -> bool:
    """True if this workflow creates Akash deployments, however it spells it."""
    if CREATES.search(text) or _DELEGATES_CREATION.search(text):
        return True
    return any(_invokes(m.group("name")).search(text) for m in _HOLDS_CLI.finditer(text))


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


def _repo_text(workflows_dir: Path) -> str:
    """Tracked text of the repo the workflows dir belongs to, for the prefix-evidence check.

    ⚠ Bounded on purpose: only files git tracks, only text, and a size cap. An unbounded walk
    would read `.venv` and node_modules and turn a fast rule into a slow one, which is how a
    rule stops being run.
    """
    root = workflows_dir.resolve().parent.parent
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "ls-files"],
            capture_output=True, text=True, timeout=20, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if out.returncode != 0:
        return ""
    chunks: list[str] = []
    for rel in out.stdout.splitlines()[:4000]:
        f = root / rel
        try:
            if f.is_file() and f.stat().st_size < 512_000:
                chunks.append(f.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
    return "\n".join(chunks)


def audit(d: Path) -> tuple[list[str], bool]:
    """Return (findings, in_scope) for one `.github/workflows` directory."""
    files = sorted(d.glob("*.yml")) + sorted(d.glob("*.yaml"))
    if not files:
        # ⚠ An empty directory is NOT a clean repo. Judging nothing and returning 0 is the
        # shape that makes a rule look adopted everywhere it was never actually run.
        return ([f"no workflow files under {d} — cannot judge, refusing to pass"], True)

    texts = {p: _executable(p.read_text(encoding="utf-8", errors="replace")) for p in files}
    creators = [p.name for p, t in texts.items() if _creates(t)]
    if not creators:
        return ([], False)

    # ⛔ THE REPO THAT SHIPS THE MECHANISM RUNS IT FROM THE CHECKOUT, NOT VIA A PIN.
    # Requiring it to `uses:` the reusable would make it install ITSELF at a released SHA and
    # sweep with that instead of with HEAD — so a defect on HEAD would go unexercised by the
    # one repo whose CI could catch it before consumers pin it.
    #
    # ⚠ THIS IS A DIFFERENT OBLIGATION, NOT AN EXEMPTION. Without the invocation check,
    # "ships the mechanism" would be a free pass, and the repo most able to reap would be the
    # only one not required to.
    if (d.resolve().parent.parent / MECHANISM).is_file():
        invokers = [p.name for p, t in texts.items() if MECHANISM_INVOCATION.search(t)]
        if not invokers:
            return (
                [
                    "ships the escrow-reaper mechanism (just_akash/cleanup_stale.py) but no "
                    "workflow invokes it. The mechanism repo runs it from the checkout rather "
                    "than adopting the reusable — but it must still RUN it, or the "
                    "implementation the whole fleet pins is the one nothing exercises."
                ],
                True,
            )
        return ([], True)

    findings: list[str] = []
    adopters: list[str] = []
    for p, t in texts.items():
        for m in ADOPTION.finditer(t):
            adopters.append(p.name)
            # ⛔ ADOPTED IS NOT THE SAME AS AIMED. The mechanism's own default prefix is
            # correct for exactly one repo; a consumer that stamps something else and does
            # not say so gets a reaper matching NONE of its deployments — 0 closable
            # forever, while this very rule reads green. An inert reaper is WORSE than an
            # absent one, because it manufactures a signal over an unswept account.
            #
            # ⚠ The check is that the declared prefix appears SOMEWHERE ELSE in the repo,
            # which is evidence the repo actually stamps it. Deliberately not a stamp
            # parser: the stamp lives in workflow shell in one repo and in SDL files in
            # another, and a parser that understood only one would fail correct code in the
            # other — and a rule that fails correct code gets exempted, not fixed.
            declared = PREFIX_INPUT.search(t)
            if not declared:
                findings.append(
                    f"{p.name}: calls the canonical escrow reaper but declares no "
                    "`placement-prefix`. The reaper would sweep under the mechanism's own "
                    "default and match none of this repo's deployments."
                )
            else:
                pfx = declared.group(1)
                elsewhere = any(pfx in other for q, other in texts.items() if q != p)
                if not elsewhere and pfx not in _repo_text(d):
                    findings.append(
                        f"{p.name}: declares `placement-prefix: {pfx}`, but that prefix "
                        "appears nowhere else in this repo. Either it is not what this repo "
                        "stamps — in which case the reaper matches nothing and reports 0 "
                        "forever — or the stamp lives somewhere this check cannot see, and "
                        "the two need reconciling."
                    )
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
    if (d.resolve().parent.parent / MECHANISM).is_file():
        print(f"OK: {label} SHIPS the mechanism and invokes it directly — adoption via the reusable is not required.")
    else:
        print(f"OK: {label} adopts {CANONICAL} at a pinned SHA.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
