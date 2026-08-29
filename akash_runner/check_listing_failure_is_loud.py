#!/usr/bin/env python3
"""A reaper that cannot READ the org listing must not report a clean sweep.

⛔ MEASURED 2026-08-29 on Borduas-Holdings. `reusable-stale-runner-reaper.yml` did:

    gh api --paginate "orgs/${ORG}/actions/runners?per_page=100" --jq '…' \\
      > /tmp/offline.tsv || true
    OFFLINE="$(wc -l < /tmp/offline.tsv | tr -d ' ')"

On a 403 the file is empty, `|| true` swallows the status, `OFFLINE` becomes 0, and the run
reports **0 offline runners** — a clean sweep. That is indistinguishable from an org with
genuinely nothing to reap, and it is the reading that let a blocked reaper look healthy.

⚠ THE 403 THAT ACTUALLY OCCURS IS INVISIBLE TO THE BUDGET FLOOR ABOVE IT. The floor reads
`rate_limit.resources.core`, but the refusals come from GitHub's SECONDARY rate limit,
which that endpoint does not report — measured with core at 4900/5000 while writes 403'd.
So the floor passes, the listing still fails, and nothing else was looking.

⭐ THE CONTROL WAS ALREADY THERE AND WAS NEVER CONSULTED. The very next line fetched
`TOTAL` from `?per_page=1`. An org total is a value whose zero is impossible while runners
demonstrably exist — exactly the paired control that separates "read succeeded, found
nothing" from "read failed". It was computed for display and never used as evidence.

⇒ SO THE RULE IS: a listing whose failure is swallowed is a defect, and the fix is not a
retry — it is making UNREADABLE a distinct, loud outcome from EMPTY.

⚠ SCOPE, STATED SO IT IS NOT MISTAKEN FOR MORE. This checks the LISTING path only. The
DELETE path in the same file also swallows its status (`-X DELETE … >/dev/null 2>&1 &&
D=$((D+1))`), which leaves an orphan uncounted and unreported. That is a real defect of the
same family and it needs its own rule with its own remedy; fixing one instance leaves the
class, and pretending this rule covers both would be the more dangerous outcome.

⚠ AND `--paginate` HERE IS NOT THE GRAPHQL LOOP BUG. A sibling investigation found that
`gh api graphql --paginate` with a `--jq` projecting only the node array strips `pageInfo`,
so gh never sees `endCursor` and re-fetches page 1 forever. REST `--paginate` advances on
HTTP **Link headers**, not a body cursor, so a `--jq` filter cannot break it. Recorded
because the two look identical and "fixing" this one would be a regression.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# A listing whose failure is discarded. `|| true` and `2>/dev/null` on the same command
# that produces the population are the two spellings seen in this fleet.
_LIST_CMD = re.compile(r"gh api[^\n]*actions/runners[^\n]*", re.IGNORECASE)
_SWALLOW = re.compile(r"\|\|\s*true\s*$|\|\|\s*echo\s|2>\s*/dev/null")


def _documents(workflows: Path) -> list[Path]:
    return sorted(p for p in workflows.iterdir() if p.suffix in {".yml", ".yaml"} and p.is_file())


def check_file(path: Path) -> list[str]:
    """Findings for one workflow. A listing must not swallow its own failure."""
    text = path.read_text()
    findings: list[str] = []
    for block in re.finditer(r"gh api(?:[^\n]*\\\n)*[^\n]*", text):
        cmd = block.group(0)
        if "actions/runners" not in cmd:
            continue
        # A single-record probe is a control read, not the population read.
        if "per_page=1\"" in cmd or "per_page=1'" in cmd:
            continue
        tail = text[block.end() : block.end() + 200]
        window = cmd + tail.split("\n\n")[0]
        if _SWALLOW.search(window) and "LIST_RC" not in window:
            findings.append(
                f"{path.name}: a runner LISTING swallows its own failure "
                f"(`|| true` / `2>/dev/null`) without capturing the exit status. "
                f"A 403 then yields an empty population and the run reports a clean "
                f"sweep. Capture the status and fail loudly, and corroborate with the "
                f"org total whose zero is impossible."
            )
    return findings


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    # `--workflows-dir` is the fleet convention every other rule in
    # .github/actions/akash-runner-conformance/action.yml is invoked with. `--workflows`
    # is kept as an alias so an existing caller does not break, but the conforming spelling
    # is the one the action passes — a rule whose flag disagrees with its call site exits 2
    # on argparse and never judges anything.
    ap.add_argument(
        "--workflows-dir", "--workflows", dest="workflows", type=Path,
        default=Path(".github/workflows"),
    )
    args = ap.parse_args(argv)

    if not args.workflows.is_dir():
        print(f"Listing-failure: not a directory: {args.workflows}", file=sys.stderr)
        return 2

    docs = _documents(args.workflows)
    reapers = [p for p in docs if "actions/runners" in p.read_text()]
    if not reapers:
        # ⛔ NON-VACUITY FLOOR, for the reason check_dereg_backstop.py documents: a pass
        #    over an empty population reads as coverage. If no workflow touches the runner
        #    listing at all, this rule observed nothing and must say so.
        print(
            f"Listing-failure: FAIL — 0 workflow(s) under {args.workflows} read the org "
            f"runner listing ({len(docs)} file(s) examined). This rule observed nothing; "
            "a pass over an empty population is not compliance. Check the path.",
            file=sys.stderr,
        )
        return 1

    findings = [f for p in reapers for f in check_file(p)]
    for f in findings:
        print(f"::error title=Listing-failure::{f}")
    if findings:
        print(f"Listing-failure: FAIL ({len(findings)} finding(s))")
        return 1
    print(f"Listing-failure: PASS — {len(reapers)} workflow(s) reading the runner listing")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
