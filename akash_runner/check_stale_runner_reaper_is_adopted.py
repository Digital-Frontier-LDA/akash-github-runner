#!/usr/bin/env python3
"""A repo that registers org runners should ADOPT the canonical stale-runner reaper.

⛔ READ THIS BEFORE ADDING ANYTHING TO IT. Three rules already own the de-registration
question, and the reason this one is separate is narrow:

    rule                              asks
    check_dereg_backstop              does a scheduled, SAFE (offline|!busy) dereg EXIST?
    check_backstop_covers_producers   does that dereg's prefix filter COVER what the repo emits?
    check_sibling_prefix_collisions   do two repos' prefixes overlap onto each other's runners?
    ── this rule ──                   is it the SHARED implementation, or an Nth private one?

Those three are satisfied by a CORRECT LOCAL reaper. That is deliberate and correct — a
repo with a working, well-aimed backstop is not leaking, and failing it would be a rule
that fails correct code. This rule asks the one question they cannot: whether the fleet is
CONVERGING on one implementation or maintaining N.

⛔ WHY CONVERGENCE IS ITS OWN PROPERTY, MEASURED NOT ASSUMED. `check_backstop_covers_producers`
recorded, on 2026-08-24 mains, that **3 of 6 producers across 3 repos were UNCOVERED** — each
repo having written its own reaper, each individually plausible, each with a different hole.
The escrow side ran the identical experiment to its conclusion: two repos, two independently
written reapers, both scheduled on a 6h cron, and NEITHER closed anything for 14-21h.
Correctness of each local copy is not the same property as there being one copy to correct.

⚠ AND THE AIM DEFECT IS NOT HYPOTHETICAL HERE. Measured 2026-08-31 in Blazing-Back: a
sweeper aimed at `dfci-infra-` while `akash-runner.yml` registers runners named `df-core-`.
It reported "stale (closable): 0" — a false negative that reads exactly like a clean account.
A shared implementation does not by itself prevent a misaimed prefix, but it collapses N
places that can be misaimed into one, and puts that one under the fleet's whole test suite.

⛔ ADVISORY ON PURPOSE, AND THE REASON IS A DATE, NOT A DOUBT. Blazing-Back's adoption is
open as BB#1745. Promoting this to ENFORCING while the fix it demands is an unmerged PR
would fail a repo for not having merged something — which teaches the fleet to exempt the
rule rather than to adopt the reaper. Promote it once BB#1745 lands.

MEASURED 2026-08-31, executable `uses:` only (comments stripped):

    repo              canonical stale-runner reaper
    just-akash        ADOPTED — agr path, sha-pinned @5d82c5973e01…
    Blazing-Back      none. Its ONLY mention is a COMMENT naming df-cicd's copy, which was
                      DELETED in df-cicd#191.
    blazing           none
    df-cicd           none

⚠ That Blazing-Back row is why comment-stripping is not optional hygiene here. A raw grep
scores it as an adopter of a workflow file that does not exist — the rule would read green
on the single most divergent repo in the fleet, and would be pointing at a deleted target
while doing it.
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

import _cli

# ⛔ IMPORTED, NEVER RE-TYPED. If this rule's idea of "registers runners" drifts from
# `check_dereg_backstop`'s, the two disagree about who is in scope, and a repo can be
# obliged to have a backstop while being exempt from converging on the shared one —
# silently, with both rules green. A copied constant drifting from its producer is the
# exact defect shape fixed in Blazing-Back#1753 the same day this was written.
from check_dereg_backstop import CREATES_REGISTRATIONS, IMMUTABLE_REF

# ⚠ The comment-stripper is imported from the ESCROW rule rather than re-typed, and
# deliberately not taken from `check_dereg_backstop` — that rule reads PARSED YAML, where
# comments vanish for free. This rule reads raw lines on purpose, for the reason the escrow
# rule records: a YAML parse discards the `uses:` lines the rule depends on when a workflow
# fails to parse, turning an unparseable file into a silent pass.
from check_escrow_reaper_is_adopted import _executable

CANONICAL = (
    "Digital-Frontier-LDA/akash-github-runner"
    "/.github/workflows/reusable-stale-runner-reaper.yml"
)


def _adoptions(text: str) -> list[str]:
    """Refs at which `text` calls the canonical reaper. Empty list = no adoption.

    ⚠ Substring-anchored on the full canonical path rather than the basename. df-cicd
    published a file with the SAME basename and it was deleted (df-cicd#191); a basename
    match would credit a consumer pointing at it — which is precisely the state Blazing-Back
    is in today, in a comment.
    """
    refs: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("uses:"):
            continue
        target = stripped[len("uses:") :].strip().strip("\"'")
        path, _, ref = target.partition("@")
        if path == CANONICAL:
            refs.append(ref)
    return refs


def _is_the_publisher(d: Path) -> bool:
    """True only for the repo that OWNS the canonical reaper.

    ⛔ NOT A BASENAME CHECK, AND THE FIRST DRAFT OF THIS RULE WAS. Testing
    `(d / "reusable-stale-runner-reaper.yml").is_file()` handed the publisher exemption to
    df-cicd on 2026-08-31 — a repo whose copy was DELETED in df-cicd#191 and survived only
    as an untracked leftover in one working tree. A same-named file is exactly what a
    RETIRED FORK looks like, and the exemption would have been granted to the second
    implementation this rule exists to eliminate.

    ⚠ Identity comes from the remote, never the directory name: this fleet has two
    checkouts whose directory names do not match their repos. Fails CLOSED — a repo that
    cannot prove it is the publisher is simply a consumer, which is the safe verdict.
    """
    root = d.resolve().parent.parent
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    if out.returncode != 0:
        return False
    owner_repo = CANONICAL.split("/.github/", 1)[0]
    return owner_repo.lower() in out.stdout.strip().lower().removesuffix(".git")


def audit(d: Path) -> tuple[list[str], bool]:
    """Return (findings, in_scope) for one `.github/workflows` directory."""
    files = sorted(d.glob("*.yml")) + sorted(d.glob("*.yaml"))
    if not files:
        # ⚠ An empty directory is NOT a clean repo. Returning 0 findings over 0 files is how
        # a rule reports adopted everywhere it never actually ran.
        return ([f"no workflow files under {d} — cannot judge, refusing to pass"], True)

    texts = {
        p: _executable(p.read_text(encoding="utf-8", errors="replace")) for p in files
    }
    registrars = [p.name for p, t in texts.items() if CREATES_REGISTRATIONS.search(t)]
    if not registrars:
        return ([], False)

    # The repo that PUBLISHES the reusable is not required to call it. Requiring that would
    # make it install ITSELF at a released SHA and sweep with that rather than with HEAD —
    # so a defect on HEAD would go unexercised by the one repo whose CI could catch it
    # before every consumer pins it. Same reasoning as the escrow rule's mechanism branch.
    if _is_the_publisher(d):
        return ([], True)

    findings: list[str] = []
    adopted = False
    for p, t in texts.items():
        for ref in _adoptions(t):
            adopted = True
            if not IMMUTABLE_REF.match(ref):
                findings.append(
                    f"{p.name}: adopts the canonical stale-runner reaper but pins "
                    f"`@{ref or '<nothing>'}`, not a 40-hex commit. A branch or tag resolves "
                    "at run time, so the reaping behaviour can change under a consumer that "
                    "changed nothing."
                )
    if not adopted:
        findings.append(
            "registers org runners ("
            + ", ".join(sorted(registrars))
            + f") but no workflow calls `{CANONICAL}`. A correct repo-local reaper satisfies "
            "check_dereg_backstop and check_backstop_covers_producers and is NOT a defect — "
            "this is the separate question of whether the fleet maintains one reaper or N. "
            "Measured: 3 of 6 producers across 3 repos were uncovered while each repo held "
            "its own."
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
        # indistinguishable from one that passed — this repo has already shipped a checker
        # that reported NOT APPLICABLE on the very repo it was written for.
        print(f"NOT APPLICABLE: {label} registers no org runners — nothing to reap.")
        return 0
    if findings:
        for f in findings:
            print(f"::error::{label}: {f}")
        return 1
    if _is_the_publisher(d):
        print(
            f"OK: {label} PUBLISHES the canonical stale-runner reaper — it runs HEAD, not a pin."
        )
    else:
        print(f"OK: {label} adopts {CANONICAL} at a pinned SHA.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
