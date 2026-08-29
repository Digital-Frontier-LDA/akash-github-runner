"""The third exit state: a rule that observed NOTHING is not a rule that found nothing.

⛔ THE AMBIGUITY THIS REMOVES. Measured across seven repos, `check_listing_failure_is_loud.py`
reported FAIL for both of these, with the same exit code:

    df-wiki           FAIL — 0 workflow(s) read the org listing   <- rule does not apply here
    blazing           FAIL (4 findings)                           <- four real defects

The non-vacuity floor is CORRECT — a PASS over an empty population reads as coverage, which is
the lie this suite exists to prevent. But it replaced one ambiguity with another: a fleet sweep
cannot separate NOT-JUDGEABLE from DEFECTIVE without reading prose.

★ THE PRECEDENT is df-wiki's `scripts/verify-register-tally.mjs`, already in production: it sets
`failed = 2` for its established-nothing branch, distinct from `failed = failed || 1` for real
findings, and says "the table shape moved; this is not a pass."

⛔⛔ WHY 3 AND NOT 2. Exit 2 is DOUBLY TAKEN in this suite:
  * `argparse` exits 2 on an unrecognised flag — and that is not hypothetical here: a rule
    authored with `--workflows` while the action passes `--workflows-dir` exits 2, the advisory
    wrapper swallows it, and the job goes green having judged nothing.
  * rules already return 2 for "not a directory" — a usage/environment error.
So 2 cannot distinguish "I could not judge" from "you called me wrong", which is precisely the
distinction being introduced. 3 is unused.

⚠⚠ BACKWARD COMPATIBILITY, AND IT IS THE PART MOST LIKELY TO BITE SOMEONE ELSE'S CI. This repo is
PUBLIC and its rules are consumed cross-org by repos we do not own, pinned at SHAs that have never
heard of this code. The change is safe because it moves a floor from **1 to 3 — both non-zero**:

    old caller:  `if ! python3 rule.py; then fail; fi`   1 -> fail   3 -> fail   IDENTICAL
    new caller:  branches on the code                    1 -> defect 3 -> not-judgeable

⇒ The new state adds INFORMATION, not PERMISSIVENESS. No previously-failing build starts passing,
which is the direction that would break an external consumer silently. A caller that opts into
treating 3 as non-fatal does so deliberately, in its own action version.

⚠ AND A MARKER IS PRINTED AS WELL AS THE CODE. A wrapper that collapses exit codes (`|| true`,
`&&`, a shell that loses `$?`) would erase the distinction the code carries; the stdout marker
survives that. Belt and braces, because the failure mode being removed was itself a swallowed
exit code.
"""

from __future__ import annotations

import sys

#: A rule ran, was called correctly, and its population was empty — it judged nothing.
NOT_JUDGEABLE = 3

#: Printed on stdout so a caller can match on text when the exit code cannot be trusted.
MARKER = "CONFORMANCE-RESULT: NOT-JUDGEABLE"


def not_judgeable(rule: str, reason: str) -> int:
    """Report that `rule` observed nothing, and return the third-state exit code.

    ⚠ Deliberately NOT an `::error` annotation. Whether an unjudgeable rule is acceptable is
    the CALLER's policy — fine for a repo that provisions no runners, an error for one that
    does — and a rule cannot know which it is in. The action decides; this only reports.
    """
    print(f"{MARKER} {rule}: {reason}", flush=True)
    print(
        f"::notice title=NOT-JUDGEABLE — {rule}::{reason} "
        "This is not a pass and not a finding: the rule observed nothing. "
        "The caller decides whether that is acceptable here.",
        file=sys.stderr,
        flush=True,
    )
    return NOT_JUDGEABLE
