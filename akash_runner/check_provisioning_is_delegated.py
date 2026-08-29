#!/usr/bin/env python3
"""§1: runner provisioning lives ONLY in just-akash, consumed via `uses:` at a pinned tag.

★ THE GAP THIS CLOSES. The standard's FIRST mandate had no rule enforcing it. Measured:
`content/platform/akash-github-runners.md` §1 says "Runner provisioning workflows live **only**
in just-akash, consumed via `uses:` at a pinned tag" and "a repo-local `akash-runner.yml` is a
defect, not a customisation" — and its opening line is "Two repos independently grew an
`akash-runner.yml`." Both still have one.

⛔ AND THE OBVIOUS EXPLANATION IS REFUTED: it is not that consumers cannot adopt. Blazing-Back
runs this suite today, cross-org, pinned at a SHA level with main — so a repo can pass every
rule the suite has and still violate the standard's first mandate. THE GAP WAS IN THE RULE SET,
not in uptake.

⚠ THE SELECTOR IS NOT THE FILENAME, and that is deliberate. `akash-runner.yml` is trivially
defeated by a rename, and a finder keyed to the string under change is a known failure here. The
subject is BEHAVIOUR: a workflow that PROVISIONS a runner without DELEGATING to just-akash.

    PROVISIONS  a step's `run:` invokes `just-akash deploy`, or renders a runner SDL
                (`RUNNER_NAME_PREFIX=`) — the two things a repo cannot do while delegating,
                because just-akash does them internally.
    DELEGATES   a step `uses: <owner>/just-akash/.github/workflows/runner-pool.yml@<ref>`,
                which is the mandate's prescribed mechanism, named exactly.

⚠ MEASURED POPULATION, and it depends on the selector — so here is mine, stated. A
`config.sh`-keyed selector finds four workflows in blazing; a deploy-verb-keyed one finds a
DIFFERENT four; their union is five. This rule uses neither raw form: it parses YAML and reads
`run:` blocks, so a COMMENTED-OUT provisioning line is not a call site. That distinction is not
academic — df-cicd and akash-github-runner each carry `df-akash-gate.yml` whose only match is
`# DSEQ=$(just-akash deploy ...)`, commented out. A grep-keyed rule reports both as violations;
this one does not.

Measured 2026-08-29, comment-filtered:

    Blazing-Back   2 violations  akash-runner.yml, runner-time-to-ready.yml
    df-cicd        0             (its only match is a comment)      -> NOT-JUDGEABLE
    agr            0             (its only match is a comment)      -> NOT-JUDGEABLE
    df-wiki        0             no provisioning workflow at all    -> NOT-JUDGEABLE

⭐ Note the second Blazing-Back finding: `runner-time-to-ready.yml` also provisions locally. The
standard's own opening line says "two repos grew an akash-runner.yml"; the rule finds a SECOND
provisioner inside one of them, which a filename-keyed check could never have surfaced.

⚠ WHAT THIS SELECTOR CANNOT SEE, named because a NOT-JUDGEABLE that silently covers one of
these is a pass-shaped answer (found by DEVOPS-core in review; neither is live today):

  * `env:` IS NEVER READ. `RUNNER_NAME_PREFIX` set at job or workflow level, rather than
    inside a `run:` block, evades the SDL signal entirely.
  * ONLY `run:` BLOCKS ARE READ. Provisioning reached through `run: bash scripts/provision.sh`
    (signal lives in the script) or `uses: ./.github/actions/provision-pool` (a local
    composite — not a run block, and DELEGATE will not match it either) is invisible, and the
    repo reads NOT-JUDGEABLE rather than flagged.
    ⚠ This fleet ALREADY writes workflows that way — blazing's reapers are
    `run: bash scripts/akash-runner-reaper.sh`. It is one refactor from live.

⚠ ADVISORY ON ARRIVAL. It fails a live consumer on day one, and promotion is gated on a
condition that is SATISFIABLE — see the PR: both the fix AND the consumer's pin must move,
because a consumer pinned at a SHA predating this rule cannot go green by fixing its workflows.
"Goes green on <repo>" alone is unreachable and has been written here before.
"""

from __future__ import annotations

import argparse

import _cli
import re
import sys
from pathlib import Path

from conformance_exit import not_judgeable

try:
    import yaml
except ImportError:  # pragma: no cover
    print("PyYAML is required", file=sys.stderr)
    raise

#: The two acts a repo cannot perform while delegating — just-akash does them internally.
PROVISION = re.compile(r"just-akash\s+deploy|RUNNER_NAME_PREFIX\s*=")

#: The mandate's prescribed mechanism, named exactly. `@<ref>` required: an unpinned `uses:`
#: is a different defect, but it is still delegation, so it is not this rule's finding.
DELEGATE = re.compile(
    r"[A-Za-z0-9_.-]+/just-akash/\.github/workflows/runner-pool\.yml@", re.I
)


def _strip_shell_comments(run: str) -> str:
    """A provisioning line inside a `#` comment is not a provisioning call site.

    ⚠ MEASURED: df-cicd and akash-github-runner both carry `# DSEQ=$(just-akash deploy ...)`.
    A rule that counted those would report two false violations on repos that provision nothing.
    """
    out = []
    for line in run.splitlines():
        i = line.find("#")
        out.append(line if i < 0 else line[:i])
    return "\n".join(out)


def _steps(doc: dict):
    for job in (doc.get("jobs") or {}).values():
        if not isinstance(job, dict):
            continue
        for st in job.get("steps") or []:
            if isinstance(st, dict):
                yield st


def inspect(path: Path) -> tuple[bool, bool]:
    """(provisions_locally, delegates_to_just_akash) for one workflow."""
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8", errors="replace"))
    except yaml.YAMLError:
        return (False, False)
    if not isinstance(doc, dict):
        return (False, False)
    provisions = delegates = False
    for st in _steps(doc):
        run = st.get("run")
        if isinstance(run, str) and PROVISION.search(_strip_shell_comments(run)):
            provisions = True
        uses = st.get("uses")
        if isinstance(uses, str) and DELEGATE.search(uses):
            delegates = True
    # a reusable consumed at job level, not step level
    for job in (doc.get("jobs") or {}).values():
        if isinstance(job, dict) and isinstance(job.get("uses"), str):
            if DELEGATE.search(job["uses"]):
                delegates = True
    return (provisions, delegates)


def is_the_provider(workflows: Path) -> bool:
    """True when THIS repo is just-akash itself — the repo §1 says provisioning belongs in.

    ⛔ WITHOUT THIS THE RULE FLAGS THE ONE REPO THAT IS CORRECT. just-akash provisions and does
    not delegate, because it IS the delegate; a naive "provisions and does not delegate"
    predicate reports the source of the standard as its worst violator.

    ⚠ Identified BEHAVIOURALLY, not by repo name. A name check is defeated by a fork, a rename,
    or a vendored copy, and this suite has a standing rule against finders keyed to the string
    under change. The provider is the repo that PUBLISHES the reusable the mandate names:
    `runner-pool.yml` offering `on: workflow_call`. Anything else that merely has a file by
    that name, without the trigger, is not offering it to anyone.
    """
    pool = workflows / "runner-pool.yml"
    if not pool.is_file():
        return False
    try:
        doc = yaml.safe_load(pool.read_text(encoding="utf-8", errors="replace"))
    except yaml.YAMLError:
        return False
    if not isinstance(doc, dict):
        return False
    # `on:` parses as the boolean True in YAML 1.1 — a well-known trap, handled explicitly.
    triggers = doc.get("on", doc.get(True))
    if isinstance(triggers, dict):
        offered = "workflow_call" in triggers
    elif isinstance(triggers, list):
        offered = "workflow_call" in triggers
    else:
        offered = triggers == "workflow_call"
    if not offered:
        return False

    # ⛔⛔ AND IT MUST ACTUALLY PROVISION. Without this the exemption is SELF-ASSERTABLE and
    # any repo escapes §1 permanently with a THREE-LINE FILE. Demonstrated by DEVOPS-core in
    # review, and reproduced here before fixing:
    #
    #     build.yml        RUNNER_NAME_PREFIX=evil-  +  just-akash deploy
    #     runner-pool.yml  name / on: workflow_call / jobs: {noop}
    #     -> PASS "this repo PUBLISHES runner-pool.yml ... provisioning here is the standard"
    #     delete only the decoy -> FAIL (1 local provisioner)
    #
    # The predicate tested whether a repo CLAIMS to be the provider, not whether it IS one.
    # A provider PROVISIONS — that is what makes it the provider — so require the signal the
    # rule already computes.
    # ⚠ VERIFIED IN BOTH DIRECTIONS against the real file, because the obvious version of
    # this fix would flag just-akash if its pool delegated the deploy to a script:
    #     just-akash/.github/workflows/runner-pool.yml -> 1 match
    #                                                     `- RUNNER_NAME_PREFIX=just-akash-${RUNNER_LABEL}`
    #     the three-line decoy                         -> 0 matches, correctly flagged
    provisions, _ = inspect(pool)
    return provisions


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    # Both spellings, via the shared helper from #41. Declaring ONLY the positional made
    # this rule exit 2 on `--workflows-dir` — the fleet-wide flag the conformance action
    # and every other dir-scoped rule use — so it would look invoked and judge nothing.
    # Caught by test_every_rule_is_invocable, which #41 added for exactly this: a
    # convergence that only fixes today's rules expires the moment a new rule lands.
    _cli.add_dir_target(ap)
    args = ap.parse_args(argv)
    _cli.resolve_target(ap, args, positional="workflows", flag="workflows_dir")

    if not args.workflows.is_dir():
        print(f"Provisioning-delegation: not a directory: {args.workflows}", file=sys.stderr)
        return 2

    if is_the_provider(args.workflows):
        print(
            "Provisioning-delegation: PASS — this repo PUBLISHES "
            "`runner-pool.yml` with `on: workflow_call`, so it is the provider §1 names. "
            "Provisioning here is the standard, not a violation of it."
        )
        return 0

    docs = sorted(p for p in args.workflows.glob("*.y*ml"))
    provisioners = []
    for p in docs:
        provisions, delegates = inspect(p)
        if provisions and not delegates:
            provisioners.append(p)

    # ⚠ DELEGATION IS A PROVISIONING PATH, and counting only LOCAL provisioning made a
    # perfectly compliant consumer read as NOT-JUDGEABLE. Caught by this rule's own test:
    # a repo whose only runner path is `uses: .../runner-pool.yml@<tag>` HAS been judged —
    # it is the compliant case — and reporting "nothing to judge" there understates
    # compliance and hides the very adoption the standard is asking for.
    seen = [inspect(p) for p in docs]
    any_provisioning = any(prov or deleg for prov, deleg in seen)
    if not any_provisioning:
        print(
            f"Provisioning-delegation: 0 workflow(s) under {args.workflows} provision a runner "
            f"({len(docs)} file(s) examined). This rule observed nothing — it cannot tell you "
            "whether provisioning is delegated in a repo that never provisions.",
            file=sys.stderr,
        )
        return not_judgeable(
            "check_provisioning_is_delegated.py",
            "no workflow provisions a runner here, so §1 has nothing to judge.",
        )

    for p in provisioners:
        print(
            f"::error title=Provisioning not delegated::{p.name} provisions a runner locally "
            f"(a `run:` step invoking `just-akash deploy` or rendering RUNNER_NAME_PREFIX) and "
            f"does not consume "
            f"`<owner>/just-akash/.github/workflows/runner-pool.yml@<ref>`. Standard §1: "
            f"provisioning lives ONLY in just-akash; push the difference into an input."
        )
    if provisioners:
        print(f"Provisioning-delegation: FAIL ({len(provisioners)} local provisioner(s))")
        return 1
    print(
        f"Provisioning-delegation: PASS — {len(docs)} workflow(s) examined, "
        "every provisioning path delegates to just-akash"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
