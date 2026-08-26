#!/usr/bin/env python3
"""A repo that registers org runners must run a SCHEDULED de-registration backstop.

⛔ THE LOOP THIS BREAKS, measured 2026-08-23 on Borduas-Holdings:

    3,025 org runner registrations   (2,900 offline+idle, 53 online, 0 busy)
    vs Digital-Frontier's 1

`runner-pool.yml` polls `orgs/{org}/actions/runners?per_page=100 --paginate`, and its own
comment predicted the consequence: "each poll costs ceil(org_runners/100) requests because
GitHub cannot filter runners by label." At 3,025 that is 31 API calls PER POLL.

    stale registrations -> 31x poll cost -> core budget exhausted -> provisioner blind
      -> runners orphaned -> MORE stale registrations

⇒ It is a positive feedback loop, and every term is measured. What is missing is a DRAIN.

⚠ DE-REGISTRATION EXISTS ALREADY AND IS NOT THE PROBLEM. `runner-teardown.yml` removes this
run's offline registrations, correctly. But it is PER-RUN: when a run is throttled, killed,
or never reaches teardown, the registration survives — and each survivor makes the next
run's poll more expensive. A per-run cleaner cannot drain a backlog it did not create.
MEASURED: of just-akash's workflows, exactly two perform de-registration and NEITHER
declares a schedule.

⇒ SO THE RULE IS EXISTENCE PLUS CADENCE, not correctness of the per-run path.

⚠ AND THE OBLIGATION BELONGS TO WHOEVER CREATES THE REGISTRATIONS. A repo that only READS
the org listing pays the pagination cost but leaks nothing — it has no backlog of its own to
drain, and demanding a reaper of it is demanding that it clean up after someone else. That
is deliberately OUT OF SCOPE here rather than silently unconsidered: poll cost is a real
term of the same loop, and if it needs enforcing it needs its own rule with its own remedy.

⛔⛔ AND ADOPTION COUNTS, BECAUSE A RULE THAT PUNISHES ADOPTION IS WORSE THAN NO RULE.
Until #145 there was nothing to adopt, so this rule looked only for a LOCAL `-X DELETE`.
Once the reusable reaper shipped, the DELETE lived in df-cicd — and a consumer that wired
it correctly still FAILED this check. Measured on just-akash: FAIL before the wiring, and
still FAIL with a correct, sha-pinned `uses:` in place.

That is not a cosmetic false negative. It teaches every consumer that the compliant path is
the one that goes red, and the rational response is to write ANOTHER repo-local reaper —
which is the divergence the standard exists to prevent. The rule would have manufactured
the defect it was written to stop.

⛔⛔ AND A LIBRARY REPO DISCHARGES THE OBLIGATION BY EXPORTING IT.

just-akash registers org runners on behalf of its CALLERS. It holds no runner PAT — its own
`check_repo_invariants.py` says so: "a caller brings its own Akash account and its own runner
PAT, and this repo must never hold either" — and it cannot know the org, because
`runner-pool.yml` takes `github-org` as a required input with no default. A cron there would
authenticate with an empty secret against a guessed org: a backstop that reaps nothing and
reports success.

Demanding a schedule of such a repo marks correct architecture non-compliant forever, and
the only way to comply would be to hold a credential the repo is designed never to hold.
That is the same defect as the adoption blindness above, one level up: the rule encoding ONE
deployment topology as the only legitimate one.

⚠ SO THE EXEMPTION IS VERIFIED, NOT CLAIMED — otherwise "library repo" is an opt-out anybody
can assert by deleting their cron. THREE things must all hold, and each is read off the
workflow rather than trusted:

  1. it EXPORTS — a `workflow_call` workflow whose job-level `uses:` is the canonical reaper,
     sha-pinned. A stub that exports nothing satisfies nothing.
  2. it does not HOLD the credential — the secret handed to the reaper is one this workflow
     DECLARES under `on.workflow_call.secrets`, i.e. supplied by the caller. A repo reading
     the PAT from its own repo secrets could have scheduled it, so it must.
  3. it does not KNOW the org — `org:` comes from an input, not a literal. A hard-coded org
     means the repo could have scheduled itself; an exporter that hard-codes one is just an
     unscheduled reaper wearing the exemption.

A repo that converts its scheduled reaper to `workflow_call` to dodge the cron requirement
fails (2) or (3), because it still holds the credential or still names the org.

⚠ BUT ADOPTION IS ONLY ADOPTION WHEN IT IS PINNED. A `uses:` of the canonical reaper at a
TAG or BRANCH satisfies nothing: a tag moves, so the de-registration behaviour this rule
depends on could change with no commit in the consumer. Accepting an unpinned `uses:` would
silently retire the supply-chain property #1128/#184 established, and would degrade this
rule to "mention the reaper somewhere". So an unpinned canonical `uses:` fails BOTH ways —
reported as a finding, and not counted toward the requirement — the same shape as an unsafe
reaper below.

⛔⛔ AND IT ENFORCES BUSY-SAFETY RATHER THAN TRUSTING IT. A rule that demanded "a scheduled
dereg" and nothing more is satisfiable by a workflow that de-registers EVERY runner —
including one mid-job. That would make this rule the cause of a worse outage than the one
it prevents, which is the shape of the `close-orphans` trap: a naive requirement demanding
a destructive regression. So a dereg operation only counts toward the requirement if it is
filtered to one of the two safe predicates (`status==offline` OR `busy==false`). An unsafe
reaper does not satisfy this rule; it fails it.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys
from pathlib import Path
from typing import Any

import yaml

# ⛔ TOUCHING THE ORG RUNNER API IS NOT REGISTERING RUNNERS, and conflating them made this
# rule fail df-cicd ITSELF. The old predicate was `orgs/.../actions/runners` — which the
# reaper this repo PUBLISHES matches on all four of its own lines: three listing GETs and
# its own DELETE. Every one is a REAPING act. The rule concluded that the repo shipping the
# backstop needed a backstop.
#
# ⚠ A PATTERN TWEAK CANNOT FIX THAT. The DELETE is genuinely present in both a registrar
# and a reaper; only the surrounding ROLE differs. So the discriminator has to ask a
# different question: does this repo CREATE registrations?
#
# MEASURED 2026-08-24 across the three repos, on the run-text this checker already reads:
#
#                          RUNNER_SCOPE / ACCESS_TOKEN= /   DELETE on
#                          RUNNER_NAME_PREFIX / image      a runner id
#     df-cicd  (ships it)          0                            1
#     just-akash                   1                            1
#     Blazing-Back                 3                            2
#
# The DELETE separates nothing. Every creation signal is 0 for the publisher and non-zero
# for both registrars.
#
# ⚠ `registration-token` is NOT the discriminator, though it looks like the obvious one:
# it is 0 in all three, because the runner IMAGE mints the token, not the workflow. A rule
# built on it would have scoped nobody and passed everyone. Measured before it was written.
CREATES_REGISTRATIONS = re.compile(
    r"RUNNER_SCOPE"  # the runner image's org-vs-repo switch
    r"|ACCESS_TOKEN\s*="  # a credential handed to a runner process
    r"|RUNNER_NAME_PREFIX"  # only something that CREATES them names them
    r"|github-runner"  # a runner image reference
    r"|actions/runners/registration-token"  # minting a registration token directly
    r"|config\.sh\b[^\n]*--token"  # actions/runner configured in place
)

# A DELETE against a specific registration id.
DEREG_OP = re.compile(r"-X\s+DELETE\s+[\"']?\S*orgs/[^\s\"']*/actions/runners/")

# The reusable reaper a consumer is meant to ADOPT rather than reimplement. Anything else
# is a repo-local reaper and is judged on its own `run:` text, as before.
CANONICAL_REAPER = (
    "Digital-Frontier-LDA/df-cicd/.github/workflows/reusable-stale-runner-reaper.yml"
)
CANONICAL_USES = re.compile(re.escape(CANONICAL_REAPER) + r"@(?P<ref>\S+)")

# A 40-hex commit. NOT a tag and NOT a branch: both move, and a backstop whose behaviour
# can change without a commit in the consumer is not a backstop.
IMMUTABLE_REF = re.compile(r"\A[0-9a-f]{40}\Z")

# The two safe selectors. A reaper must filter to either:
#   1. status == "offline", OR
#   2. .busy == false
#
# Both are safe because a runner mid-job is online+busy, so neither can select a busy
# runner. THE ORIGINAL RULE demanded ONLY the offline spelling — a true premise with a
# false "only". Offline filters out 100% of the live leak's busy half AND 100% of the live
# leak's online-and-busy half, but the live leak is overwhelmingly the OTHER half:
# `online AND busy=false`, a starved runner printing "Listening for Jobs". Measured
# 2026-08-25 by reference_the_leak_metric_is_online_and_idle_not_offline: of 144 live
# leaks, 119 (83%) are online+idle — invisible to every offline-only reaper.
#
# `busy == false` is the STRICTLY BETTER conjunct: it misses 0% of the live leak (the
# starved runners are exactly `online AND busy=false`) AND never selects a busy runner.
# The offline spelling is kept on the allowlist so a pre-existing offline-filtered reaper
# does not need to be rewritten; the rule no longer REQUIRES it.
#
# ⚠ THE QUOTE MAY BE BACKSLASH-ESCAPED. A jq program embedded in a DOUBLE-quoted shell
# string is written `select(.status == \"offline\")`, which is the normal spelling and was
# live in Blazing-Back/akash-close.yml:167. The original pattern demanded a bare `"`, so it
# MISSED that filter and reported a compliant, offline-filtered workflow as a busy-safety
# hazard — and, through the same code path, refused to count it toward the requirement. One
# missing `\\?` produced two false findings against a repo doing it right.
#
# ⇒ That is the defect this whole rule is about, committed by the rule: an instrument that
# reports on the SPELLING it expected rather than the PROPERTY it claims to check.
#
# ⚠ KNOWN LIMIT, stated rather than papered over: `select(.status != "online")` and
# `select(.busy != true)` are equally safe filters and are NOT matched. No workflow in the
# fleet uses them today (checked), and widening to `!=` would also admit genuinely wrong
# predicates, so this stays an allowlist of proven-safe spellings. A repo using another one
# gets a false positive, and the fix is to add the spelling here with its evidence — not
# to loosen the pattern.
SAFE_FILTER = re.compile(
    r"status\s*==\s*\\?[\x27\"]offline\\?[\x27\"]"  # the OFFLINE spelling, kept for parity
    r"|\.?\s*busy\s*==\s*false"  # .busy == false — bare boolean literal, optionally prefixed with `.`
)


def _on(document: dict[str, Any]) -> dict[str, Any]:
    # YAML 1.1 parses a bare `on:` as the BOOLEAN True, not the string "on".
    for key in ("on", True):
        value = document.get(key)
        if isinstance(value, dict):
            return value
    return {}


def _run_text(document: dict[str, Any]) -> str:
    parts: list[str] = []
    for job in (document.get("jobs") or {}).values():
        if not isinstance(job, dict):
            continue
        for step in job.get("steps") or []:
            if isinstance(step, dict):
                parts.append(str(step.get("run") or ""))
    return "\n".join(parts)


# ⛔ A REAPER THAT DELEGATES TO A SCRIPT IS STILL A REAPER. Measured 2026-08-24 on
# blazing: `akash-runner-registration-reaper.yml` is scheduled and its only step is
# `bash scripts/akash-runner-reaper.sh`. The listing read, the `status=="offline"` filter
# and the DELETE all live in that script — so a checker reading only `run:` text sees a
# scheduled workflow that de-registers nothing, and reports a repo with a working backstop
# as having none.
#
# ⚠ THIS IS THE SAME DELEGATION BLINDNESS #146 FIXED FOR `uses:`, IN A SECOND FORM. That
# fix taught the rule to see a reusable-workflow call; it did not teach it to see a shell
# script. One delegation mechanism was handled and the other was not, which is why the
# false positive survived a fix aimed squarely at it.
DELEGATES_TO_SCRIPT = re.compile(
    r"(?:^|\||&|;)\s*(?:bash|sh|source|\.)\s+(?P<path>[A-Za-z0-9_./-]+\.sh)\b"
    r"|(?:^|\||&|;)\s*(?P<rel>\./[A-Za-z0-9_./-]+\.sh)\b",
    re.M,
)


def _delegated_text(body: str, workflows: Path) -> tuple[str, list[str]]:
    """Text of the shell scripts a run-block delegates to, plus any it could not read.

    Scripts are resolved against the REPO ROOT — `<repo>/.github/workflows` means the root
    is two levels up — because a workflow's `bash scripts/x.sh` runs from the checkout root.

    ⚠ An unreadable script is RETURNED AS A PROBLEM, never skipped. Treating "I could not
    open it" as "it contains no de-registration" is how a repo with a working backstop gets
    reported as having none, which is the exact defect this function exists to remove.
    """
    root = workflows.parent.parent
    collected: list[str] = []
    unreadable: list[str] = []
    for match in DELEGATES_TO_SCRIPT.finditer(body):
        rel = match.group("path") or match.group("rel") or ""
        # ⚠ NOT `lstrip("./")`. lstrip strips ANY leading `.` or `/` CHARACTER, so
        # `.github/scripts/x.sh` becomes `github/scripts/x.sh` and never resolves.
        # Caught by its own false findings against four real repos.
        if rel.startswith("./"):
            rel = rel[2:]
        # ⚠ ONLY REPO-RELATIVE SCRIPTS. An ABSOLUTE path is a file on the RUNNER HOST, not
        # in this repo — Blazing-Back's sentinel-pentest.yml runs
        # `/home/pentest/.guardian/run-engagement.sh`, which cannot exist at check time and
        # is not a backstop. Reporting it as an unreadable delegation turns a host-path
        # invocation into a de-registration finding. `..` is excluded for the same reason:
        # it names something outside the tree being judged.
        if not rel or rel.startswith("/") or ".." in pathlib.PurePosixPath(rel).parts:
            continue
        candidate = root / rel
        try:
            collected.append(candidate.read_text())
        except OSError:
            unreadable.append(rel)
    return "\n".join(collected), unreadable


def _uses_refs(document: dict[str, Any]) -> list[tuple[str, str]]:
    """(job name, `uses:` value) for every job that CALLS a reusable workflow.

    Job-level `uses:` only. A step-level `uses:` is an action, not a reusable workflow, and
    cannot perform the de-registration this rule is about.
    """
    out: list[tuple[str, str]] = []
    for job_name, job in (document.get("jobs") or {}).items():
        if isinstance(job, dict) and isinstance(job.get("uses"), str):
            out.append((str(job_name), job["uses"]))
    return out


def _declared_call_secrets(document: dict[str, Any]) -> set[str]:
    """Secret names this workflow declares under `on.workflow_call.secrets`.

    These are a typed parameter list supplied by the CALLER, not a credential this repo
    stores — which is exactly the distinction the export exemption turns on.
    """
    call = _on(document).get("workflow_call") or {}
    if not isinstance(call, dict):
        return set()
    declared = call.get("secrets") or {}
    return set(declared) if isinstance(declared, dict) else set()


def _exports_the_obligation(
    document: dict[str, Any], job: dict[str, Any]
) -> str | None:
    """Why this adopting job does NOT qualify as an export, or None if it does."""
    if "workflow_call" not in _on(document):
        return "it is neither scheduled nor callable, so nothing will ever run it"

    org = str((job.get("with") or {}).get("org", ""))
    if "inputs." not in org:
        return (
            f"it hard-codes org {org!r} instead of taking it from an input — a repo that "
            f"knows its org could have scheduled the reaper itself"
        )

    declared = _declared_call_secrets(document)
    passed = job.get("secrets") or {}
    if not isinstance(passed, dict) or not passed:
        return "it passes no secret to the reaper, so the reaper cannot authenticate"
    undeclared = [
        name
        for name, value in passed.items()
        for ref in re.findall(r"secrets\.([A-Za-z0-9_]+)", str(value))
        if ref not in declared
    ]
    if undeclared:
        return (
            f"it hands the reaper this repo's OWN secret(s) {sorted(set(undeclared))} rather "
            f"than one declared under `on.workflow_call.secrets` — a repo that holds the "
            f"credential could have scheduled the reaper itself"
        )
    return None


def check_directory(workflows: Path) -> list[str]:
    findings: list[str] = []
    registers_runners: list[str] = []
    scheduled_safe_dereg: list[str] = []
    unsafe_dereg: list[str] = []
    unpinned_adoption: list[tuple[str, str, str]] = []
    exported_backstop: list[str] = []
    near_miss_export: list[tuple[str, str]] = []
    adopting_job: dict[str, Any] = {}

    for path in sorted(workflows.glob("*.yml")) + sorted(workflows.glob("*.yaml")):
        try:
            document = yaml.safe_load(path.read_text()) or {}
        except (OSError, yaml.YAMLError) as exc:
            # ⚠ Unreadable is not clean: a parse failure that contributed nothing would let
            # a repo look compliant because its only backstop failed to parse.
            findings.append(
                f"{path.name}: could not be read, so it was NOT checked: {exc}"
            )
            continue
        if not isinstance(document, dict):
            continue
        body = _run_text(document)
        delegated, unreadable_scripts = _delegated_text(body, workflows)
        # ⚠ ONLY A SCHEDULED WORKFLOW CAN BE THE BACKSTOP, so only there does an unreadable
        # script change the answer. Reporting every workflow that runs a script it cannot
        # open turns telemetry and install helpers into de-registration findings — measured:
        # 3 such findings on just-akash and 1 on df-cicd, none of them about reaping.
        if unreadable_scripts and "schedule" in _on(document):
            findings.append(
                f"{path.name}: is scheduled and delegates to "
                f"{', '.join(repr(r) for r in unreadable_scripts)}, which could not be read "
                f"— so it was judged on its `run:` text alone and may hold a backstop this "
                f"check cannot see. Unreadable is not empty."
            )
        # The scripts a step runs are part of what that step DOES. Only the dereg question
        # consults them; whether a repo REGISTERS runners is answered by the workflow.
        body_with_delegates = body + "\n" + delegated
        if CREATES_REGISTRATIONS.search(body):
            registers_runners.append(path.name)

        # ADOPTION. Checked BEFORE the local-DELETE gate below, because an adopting
        # workflow has no `run:` text at all — its whole body is the `uses:`.
        adopted = False
        for job_name, uses in _uses_refs(document):
            match = CANONICAL_USES.search(uses)
            if match is None:
                continue
            ref = match.group("ref")
            if IMMUTABLE_REF.match(ref):
                adopted = True
                adopting_job = (document.get("jobs") or {}).get(job_name) or {}
            else:
                unpinned_adoption.append((path.name, job_name, ref))
        if adopted:
            if "schedule" in _on(document):
                scheduled_safe_dereg.append(path.name)
            else:
                why_not = _exports_the_obligation(document, adopting_job)
                if why_not is None:
                    exported_backstop.append(path.name)
                else:
                    near_miss_export.append((path.name, why_not))

        if not DEREG_OP.search(body_with_delegates):
            continue
        if not SAFE_FILTER.search(body_with_delegates):
            unsafe_dereg.append(path.name)
            continue
        if "schedule" in _on(document):
            scheduled_safe_dereg.append(path.name)

    for name, job_name, ref in unpinned_adoption:
        findings.append(
            f"{name}: job '{job_name}' calls the canonical reaper at '{ref}', which is not a "
            f"40-hex commit. A tag or branch moves, so the de-registration behaviour this "
            f"repo relies on can change with no commit here. It does NOT satisfy the backstop "
            f"requirement; pin it to a commit."
        )

    for name in unsafe_dereg:
        findings.append(
            f"{name}: de-registers org runners without filtering to one of the two safe "
            f"predicates (status==offline or busy==false) — a runner mid-job is online+busy, "
            f"so this can remove a runner that is executing. It does not satisfy the backstop "
            f"requirement; it is a hazard."
        )

    for name, why_not in near_miss_export:
        findings.append(
            f"{name}: calls the canonical reaper but neither schedules it nor exports it — "
            f"{why_not}. A reaper nothing runs drains nothing."
        )

    if registers_runners and not scheduled_safe_dereg and not exported_backstop:
        findings.append(
            "this repo registers org runners ("
            + ", ".join(registers_runners)
            + ") but no workflow performs a SCHEDULED de-registration filtered to one of "
            "the two safe predicates (status==offline or busy==false). Per-run cleanup cannot "
            "drain registrations left by runs that were throttled or killed, and every survivor "
            "makes the next pool's poll cost ceil(org_runners/100) requests — the loop that "
            "exhausted the core API budget."
        )
    return findings


def _workflow_documents(workflows: Path) -> list[Path]:
    """Files under `workflows` that are actually WORKFLOWS, not merely `*.yml`.

    ⛔ COUNTING GLOB HITS IS NOT COUNTING WORKFLOWS. Pointed at a repo ROOT this checker
    matched `.pre-commit-config.yaml`, `.sops.yaml` and `.coderabbit.yaml` and printed
    "PASS — 3 workflow file(s) examined" — a MORE convincing green than the bare PASS it
    replaced, because it asserts a number and reads as evidence of work done. Measured
    2026-08-23 on just-akash, in the same wrong-path incident this floor exists for: the
    first version of the floor made the silent green louder instead of catching it.

    ⚠ An UNREADABLE file counts as a candidate. It is not a workflow we could confirm,
    but dropping it here would delete it from the population and silence the
    "could not be read, so it was NOT checked" finding below — trading one vacuity for
    another.
    """
    found: list[Path] = []
    for path in sorted(workflows.glob("*.yml")) + sorted(workflows.glob("*.yaml")):
        try:
            document = yaml.safe_load(path.read_text())
        except (OSError, yaml.YAMLError):
            found.append(path)
            continue
        # YAML 1.1 parses a bare `on:` as the boolean True, not the string "on".
        if isinstance(document, dict) and ({"on", True, "jobs"} & set(document)):
            found.append(path)
    return found


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("workflows", type=Path, help="a .github/workflows directory")
    args = parser.parse_args()
    if not args.workflows.is_dir():
        print(f"Dereg backstop: not a directory: {args.workflows}", file=sys.stderr)
        return 2
    matched = len(list(args.workflows.glob("*.yml"))) + len(
        list(args.workflows.glob("*.yaml"))
    )
    examined = len(_workflow_documents(args.workflows))
    if examined == 0:
        # ⛔ NON-VACUITY FLOOR. "I found nothing to check" is not "you comply". A wrong
        # path, a repo layout change, or a checkout that omitted .github all produce an
        # empty population — and every rule below would then report PASS forever while
        # observing nothing. A guard that cannot fire is worse than no guard: it reads as
        # coverage. Measured 2026-08-23: this checker returned PASS on an empty directory.
        print(
            f"Dereg backstop: FAIL — found 0 WORKFLOW documents under {args.workflows} "
            f"({matched} yaml file(s) matched, none declaring `on:` or `jobs:`). "
            "A pass over an empty population is not compliance; check the path.",
            file=sys.stderr,
        )
        return 1
    findings = check_directory(args.workflows)
    for finding in findings:
        print(f"::error title=Dereg backstop::{finding}")
    if findings:
        print(f"Dereg backstop: FAIL ({len(findings)} finding(s))")
        return 1
    print(f"Dereg backstop: PASS — {examined} workflow file(s) examined")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
