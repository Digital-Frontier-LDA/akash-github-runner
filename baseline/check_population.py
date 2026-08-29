#!/usr/bin/env python3
"""POPULATION_SCOPED conformance — the third scope, and the one a fixture cannot provide.

⛔ WHY A THIRD SCOPE EXISTS. The rules in `check_conformance.py` are all
`rule(root: Path, traits) -> RuleResult`: they judge a FILE or a DIRECTORY. Every one of
them is excellent and every one of them was GREEN through 2026-08-28, while:

  * Blazing-Back's stale-runner-reaper selected `PREFIXES: df-core-` against an org
    listing that was 100% `akash-e2epool-*` / `akash-fast-pool-*`. It matched 0 of 10000,
    printed `owned_by_us=0`, and exited SUCCESS.
  * just-akash's cleanup-stale ran 4x/day with correct aim and no hands (a scheduled run
    inherits `execute=false`), while 25 leases aged to 33.5h and drove the shared Console
    grant under its funding floor, blocking a sibling repo's CI twice.

Neither is a defect in a file. Both are a correct implementation aimed at the wrong
POPULATION, or aimed correctly with no authority to act. **A fixture cannot detect a
population mismatch, because the fixture IS the assumption under test.** That is the
whole argument for this module: it reads the live shared resource instead of a checked-in
sample of it.

⚠ OWNERSHIP FOLLOWS THE SHARED RESOURCE, NOT THE CODE. Three repos share exactly two
things — the org runner-registration cap, and the Console escrow grant. Every failure
above is a failure to reap one of those two. Relocating the code into one repo would not
have caught any of them, because the implementations were never the thing in common.

⚠ READ-ONLY, AND DELIBERATELY SO. This module observes and reports. It deletes nothing and
closes nothing. just-akash is the proof of why: adding a schedule LOOKED like a fix while
the aim was wrong, and its own comment records that "fixing only the schedule would have
looked like a fix". Eyes first; hands only after a non-zero owned set has been reconciled
by hand at least once.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field

SCHEMA_VERSION = 1
_SEVERITY_ORDER = {"required": 0, "advisory": 1}


@dataclass
class Finding:
    rule: str
    severity: str
    message: str
    path: str | None = None
    line: int | None = None

    def as_dict(self) -> dict:
        return {
            "rule": self.rule,
            "severity": self.severity,
            "message": self.message,
            "path": self.path,
            "line": self.line,
        }


@dataclass
class RuleResult:
    rule: str
    status: str  # pass | fail | warn | n-a
    findings: list[Finding] = field(default_factory=list)
    note: str = ""

    def as_dict(self) -> dict:
        return {
            "rule": self.rule,
            "status": self.status,
            "note": self.note,
            "findings": [f.as_dict() for f in self.findings],
        }


class Unreadable(Exception):
    """The resource could not be observed. NOT the same as observing an empty one."""


def _gh(args: list[str]) -> str:
    """`gh api` returning stdout, raising Unreadable on any non-zero exit.

    ⛔ THE EXIT STATUS IS THE ORACLE, NEVER THE PRESENCE OF OUTPUT. `gh api` writes the
    error BODY to stdout on 404/403, so `if out:` reads a failure as data. That exact
    mistake inverted an ownership verdict during this module's design — a detector
    reported "OWNED BY US" for two runs owned by a sibling repo, because it tested
    `-n "$out"` instead of the return code.
    """
    p = subprocess.run(["gh", "api", *args], capture_output=True, text=True, timeout=60)
    if p.returncode != 0:
        raise Unreadable(
            f"gh api {' '.join(args)} -> rc={p.returncode}: {p.stderr[:200]}"
        )
    return p.stdout


# ---------------------------------------------------------------- rule 1: total miss
def rule_reaper_matches_its_population(org: str, prefixes: list[str]) -> RuleResult:
    """A reaper that matches ZERO of a non-empty population is not clean — it is blind.

    ⚠ THIS CATCHES A TOTAL MISS, NOT A PARTIAL MISAIM. Matching the wrong 5 of 900 still
    passes here. It is worth having anyway because both 2026-08-28 failures matched
    EXACTLY ZERO, and because `matched==0` is the shape every one of our reapers prints
    on its way to exiting green.

    ⚠ AND ZERO CAN BE CORRECT. Blazing-Back genuinely owns no runners in this org listing
    — its registrations resolve to a sibling repo. So a bare `matched==0 -> FAIL` would
    pin a FALSE invariant and push the next engineer into widening a prefix into another
    repo's live runners. The finding therefore reports WHOSE the population is, and is
    advisory-by-default unless the caller declares it owns some.
    """
    rule = "reaper-matches-its-population"
    try:
        # ⛔ `--paginate` OR THIS READS 1.6% OF THE POPULATION. `per_page=100` alone
        # returns the FIRST page only. Measured 2026-08-29: Borduas-Holdings held 6,276
        # registrations = 63 pages, so a declared prefix living on any later page yields
        # `matched=0` — the exact false-clean this module exists to catch, manufactured by
        # the module itself. REST `--paginate` advances on Link headers, so a `--jq`
        # projection cannot break it (unlike the GraphQL loop bug).
        raw = _gh(
            [
                "--paginate",
                f"orgs/{org}/actions/runners?per_page=100",
                "--jq",
                ".runners[].name",
            ]
        )
    except Unreadable as exc:
        # ⛔ UNREADABLE IS NOT ZERO. Reporting "0 matched" here would manufacture the very
        # false-clean this module exists to catch.
        return RuleResult(rule, "n-a", note=f"population unreadable: {exc}")

    names = [n for n in raw.splitlines() if n.strip()]
    if not names:
        return RuleResult(rule, "n-a", note="population is empty; nothing to judge")

    matched = [n for n in names if any(n.startswith(p) for p in prefixes)]
    census: dict[str, int] = {}
    for n in names:
        head = n.rsplit("-", 2)[0] if n.count("-") >= 2 else n
        census[head] = census.get(head, 0) + 1
    top = sorted(census.items(), key=lambda kv: -kv[1])[:3]

    if matched:
        return RuleResult(
            rule,
            "pass",
            note=f"{len(matched)}/{len(names)} sampled names matched {prefixes}",
        )

    return RuleResult(
        rule,
        "warn",
        [
            Finding(
                rule,
                "advisory",
                f"prefixes {prefixes} matched 0 of {len(names)} sampled registrations. "
                f"Dominant prefixes: {', '.join(f'{k}={v}' for k, v in top)}. "
                "Either this reaper is aimed at a population that no longer exists, or the "
                "population belongs to another repo — resolve an embedded run id before "
                "widening anything.",
            )
        ],
        note="matched=0 over a non-empty population",
    )


# ------------------------------------------------------- rule 2: the claim must shrink
def rule_claimed_population_shrinks(
    previous: dict | None, current: int, label: str
) -> RuleResult:
    """The only rule here that catches PARTIAL misaim, because it judges the OUTCOME.

    A reaper can run, match, delete, and still not reduce the thing it exists to reduce.
    Comparing successive observations is the only check that notices.

    ⚠ AT A CAP, THIS READING IS CENSORED AND THE RULE MUST SAY SO. `total_count` saturates
    at the GitHub org limit of 10000: deletions do not move the number until the true
    figure drops below the ceiling, so "did not shrink" is UNFALSIFIABLE there rather than
    false. Reporting a failure at the cap would be a confident answer from a blind probe.
    """
    rule = "claimed-population-shrinks"
    CAP = 10000
    if previous is None:
        return RuleResult(
            rule, "n-a", note=f"no prior observation of {label}; baseline recorded"
        )
    was = previous.get("count")
    if not isinstance(was, int):
        return RuleResult(rule, "n-a", note="prior observation malformed")
    if current >= CAP and was >= CAP:
        return RuleResult(
            rule,
            "n-a",
            note=(
                f"{label} is AT THE {CAP} CAP in both observations ({was} -> {current}); the "
                "true figure is >= the cap, so shrinkage is not observable from this number. "
                "This is censored, not stable."
            ),
        )
    if current > was:
        return RuleResult(
            rule,
            "fail",
            [
                Finding(
                    rule,
                    "required",
                    f"{label} GREW {was} -> {current}; the reaper is not keeping up",
                )
            ],
        )
    return RuleResult(rule, "pass", note=f"{label} {was} -> {current}")
