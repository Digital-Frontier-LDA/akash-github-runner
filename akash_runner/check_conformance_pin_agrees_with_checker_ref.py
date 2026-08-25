#!/usr/bin/env python3
"""A consumer's `uses:@sha` and its `checker-ref` must be the SAME commit.

⛔ THE INVARIANT EXISTED ONLY AS A COMMENT, AND BOTH CONSUMERS DRIFTED.
`reusable-akash-runner-conformance.yml` takes `checker-ref` — the revision of the
CHECKER to run — while the caller separately pins the WORKFLOW with `uses:@sha`.
just-akash's own file says why they must match:

    # Pinned to the SAME sha as the @pin above so checker and contract cannot drift.

That sentence is the whole enforcement. Nothing reads it.

⚠ WHY DRIFT HERE IS SILENT RATHER THAN LOUD. Both halves resolve. A `uses:@sha` at
commit A and a `checker-ref` at commit B are each individually valid: the SHAs exist,
the files exist, the job runs, the conformance check goes GREEN. What actually happens
is that the CONTRACT from commit A is enforced by the CHECKER from commit B — a rule
added in between is invisible to one half or the other, and no signal distinguishes
that from a clean run.

⚠ AND THE FAILURE IS ASYMMETRIC, WHICH IS WHY A HALF-BUMP IS THE LIKELY SHAPE. Bumping
`uses:` alone runs a NEW contract against an OLD checker; bumping `checker-ref` alone
runs an OLD contract against a NEW checker. Both are one-line edits, both look
complete in review, and the reviewer sees a 40-character hex string change either way.

MEASURED, 2026-08-25 — the class this rule generalises:

    df-cicd      pinned 297ea3cc (ancestor)  ->  3 rules ABSENT at the pin   (df-cicd#186)
    just-akash   pinned 47f2835d (ancestor)  ->  3 rules ABSENT at the pin   (just-akash#209)

Both were STALE rather than mismatched, so this rule would not have caught those two —
staleness needs the upstream default branch, which a local rule cannot see without a
network call. ⚠ Stated plainly so nobody reads this as covering currency: THIS RULE
CHECKS AGREEMENT, NOT CURRENCY. What it catches is the repair going half-done, which
is the most likely next instance now that two repos have been bumped by hand.

⭐ `check_context_properties_exist` is why this rule is STATIC. The obvious design —
have the reusable workflow compare its own resolved SHA to the input — needs
`github.job_workflow_sha`, which is NOT in that rule's known-good leaf set. It may
well be real, but this repo already carries two incidents (`github.organization`,
`job.workflow_sha`) where a confident, nonexistent property resolved to "" and was
green over. Both values here are LITERALS in the caller's YAML, so no context property
is needed at all.

Exit codes match the other rules:
    0  every caller's two pins agree (or no caller is present — see NOT-JUDGEABLE)
    1  at least one caller's pins disagree
    2  the scan itself is broken (no files, unparseable YAML)
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

import yaml

# The reusable this rule is about. Matched on the FILENAME so a fork or a rename of the
# owning org still resolves — the contract is the workflow, not the repository path.
_REUSABLE = "reusable-akash-runner-conformance.yml"

# `uses: <owner>/<repo>/.github/workflows/<file>@<ref>` — the ref is everything after
# the LAST '@', because a path cannot contain '@' but a ref theoretically can.
_USES = re.compile(rf"(?P<path>\S*{re.escape(_REUSABLE)})@(?P<ref>\S+)")

_SHA = re.compile(r"^[0-9a-f]{40}$")


def _jobs(doc: Any) -> dict[str, Any]:
    jobs = (doc or {}).get("jobs")
    return jobs if isinstance(jobs, dict) else {}


def audit(path: Path) -> tuple[list[str], int]:
    """Return (problems, callers_seen). `callers_seen` separates OK from NOT-JUDGEABLE."""
    doc = yaml.safe_load(path.read_text())
    problems: list[str] = []
    seen = 0
    for job_id, job in _jobs(doc).items():
        if not isinstance(job, dict):
            continue
        uses = job.get("uses")
        if not isinstance(uses, str):
            continue
        m = _USES.search(uses)
        if not m:
            continue
        seen += 1
        pinned = m.group("ref")
        with_block = job.get("with")
        checker = (
            (with_block or {}).get("checker-ref")
            if isinstance(with_block, dict)
            else None
        )

        if checker is None:
            problems.append(
                f"{path.name}: job '{job_id}' calls {_REUSABLE}@{pinned[:9]} but supplies no "
                f"`checker-ref`. The input is REQUIRED and has no default precisely so the "
                f"checker cannot silently differ from the contract."
            )
            continue

        checker = str(checker).strip()
        if not _SHA.match(str(pinned)):
            problems.append(
                f"{path.name}: job '{job_id}' pins `uses:@{pinned}` — not a 40-char commit "
                f"SHA. A branch or tag is mutable, so the contract this job enforces can "
                f"change without any edit here."
            )
        if not _SHA.match(checker):
            problems.append(
                f"{path.name}: job '{job_id}' sets `checker-ref: {checker}` — not a 40-char "
                f"commit SHA. The checker revision must be immutable for the same reason."
            )
        if _SHA.match(str(pinned)) and _SHA.match(checker) and pinned != checker:
            problems.append(
                f"{path.name}: job '{job_id}' runs the CONTRACT from {pinned[:9]} against the "
                f"CHECKER from {checker[:9]}. Both resolve and the job goes green, so nothing "
                f"else will report this. Bump both or neither."
            )
    return problems, seen


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "targets", nargs="+", help="workflow file(s) or a workflows directory"
    )
    args = ap.parse_args(argv)

    files: list[Path] = []
    for t in args.targets:
        p = Path(t)
        if p.is_dir():
            files.extend(sorted(q for q in p.glob("*.y*ml")))
        elif p.exists():
            files.append(p)
    if not files:
        print(
            "no workflow files found — the scan is broken, not the repo",
            file=sys.stderr,
        )
        return 2

    problems: list[str] = []
    callers = 0
    for f in files:
        try:
            found, seen = audit(f)
        except yaml.YAMLError as e:
            print(f"{f.name}: unparseable YAML ({e}) — NOT a pass", file=sys.stderr)
            return 2
        problems.extend(found)
        callers += seen

    if problems:
        print("Conformance pins disagree with their checker-ref:")
        for p in problems:
            print(f"  - {p}")
        print(
            "\n⇒ `uses:@sha` selects the CONTRACT; `checker-ref` selects the CHECKER. "
            "They are two declarations of one decision, and a half-bump enforces an old "
            "contract with a new checker (or the reverse) while reporting green."
        )
        return 1

    if callers == 0:
        # ⛔ NOT A PASS. A repo that never calls the reusable has not been judged on this
        #    axis, and printing OK would let a caller be REMOVED without any signal.
        print(
            f"⚠ NOT-JUDGEABLE: no caller of {_REUSABLE} in {len(files)} workflow(s). "
            "This axis does not apply here; it is not a pass."
        )
        return 0

    print(
        f"conformance-pin: OK — {callers} caller(s) across {len(files)} workflow(s), pins agree"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
