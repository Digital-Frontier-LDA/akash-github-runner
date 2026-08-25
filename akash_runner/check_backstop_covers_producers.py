#!/usr/bin/env python3
"""A backstop must reap what the repo actually creates.

`check_dereg_backstop.py` asks whether a scheduled, offline-filtered de-registration
EXISTS. It does not ask whether that backstop covers the runners the repo CREATES. It was
promoted to ENFORCING on a clean five-consumer sweep, and two of those five were leaking
while green.

⛔ MEASURED 2026-08-24 on current mains:

    repo          producer -> emitted prefix              backstop filter        covered
    blazing       akash-integration-new.yml -> akash-integration-   startswith(same)  yes
                  akash-ci.yml              -> akash-ci-            --                NO
                  akash-runner.yml          -> akash-               --                NO
    Blazing-Back  akash-runner.yml          -> df-core-             PREFIXES: df-core- yes
                  runner-time-to-ready.yml  -> akash-               --                NO
    just-akash    runner-pool.yml           -> just-akash-          name-prefixes:     yes

⇒ PROMOTING A RULE TO ENFORCING DOES NOT MAKE A REPO SAFE; IT MAKES IT GREEN. Existence is
not coverage, and the ladder in #154 has one more rung than it looked:
merged != tested != invoked != enforced != SUFFICIENT.

★ The mechanism is generalised from just-akash#186's `test_runner_name_prefix_invariants.py`,
which solved exactly this for ONE prefix as a repo-local test: assert the backstop's
CONFIGURED prefix against what the SDLs actually EMIT. This asks it of the whole producer
set, for every consumer.

⚠ THE FILTER EXTRACTION IS ANCHORED ON `.name`, NOT ON `startswith`. A bare `startswith`
scan over these repos returns `http`, `#`, `v0.2`, `attributes.`, `akash1` and a dozen more
— none of them runner-name filters. A rule built on the loose pattern computes coverage
from noise and reports whatever that noise happens to cover.

⚠ AND IT FOLLOWS DELEGATION IN BOTH FORMS — a job-level `uses:` and a shell script —
because blazing's filter lives in `scripts/akash-runner-reaper.sh`. #156 recorded why:
handling one delegation mechanism looks identical to handling the problem, and makes the
remaining one harder to find rather than easier.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys
from pathlib import Path
from typing import Any

import yaml

# A producer names its registrations. The literal prefix is everything before the first
# shell/Actions interpolation: `RUNNER_NAME_PREFIX=df-core-${RUNNER_LABEL}` -> `df-core-`.
EMITS_PREFIX = re.compile(r"RUNNER_NAME_PREFIX=([A-Za-z0-9._-]*)")

# ⚠ ANCHORED ON `.name`. `startswith(...)` alone matches any jq string test in the repo.
NAME_FILTER_JQ = re.compile(r"\.name\s*\|\s*startswith\(\s*[\"']([^\"']*)[\"']\s*\)")
# The canonical reusable reaper's input, and the local spelling Blazing-Back uses.
NAME_FILTER_INPUT = re.compile(
    r"(?:name-prefixes|PREFIXES)\s*[:=]\s*[\"']?([A-Za-z0-9._,-]+)"
)

DEREG_OP = re.compile(r"-X\s+DELETE\s+[\"']?\S*orgs/[^\s\"']*/actions/runners/")
DELEGATES_TO_SCRIPT = re.compile(
    r"(?:^|\||&|;)\s*(?:bash|sh|source|\.)\s+(?P<path>[A-Za-z0-9_./-]+\.sh)\b"
    r"|(?:^|\||&|;)\s*(?P<rel>\./[A-Za-z0-9_./-]+\.sh)\b",
    re.M,
)


def _on(document: dict[str, Any]) -> dict[str, Any]:
    for key in ("on", True):  # YAML 1.1 parses a bare `on:` as the boolean True.
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


def _delegated_text(body: str, workflows: Path) -> str:
    """Text of repo-relative shell scripts the run-block delegates to.

    ⚠ Repo-relative only. An ABSOLUTE path is a file on the runner host, not in the tree
    being judged, and `..` names something outside it.
    """
    root = workflows.parent.parent
    out: list[str] = []
    for match in DELEGATES_TO_SCRIPT.finditer(body):
        rel = match.group("path") or match.group("rel") or ""
        if rel.startswith("./"):
            rel = rel[2:]
        if not rel or rel.startswith("/") or ".." in pathlib.PurePosixPath(rel).parts:
            continue
        try:
            out.append((root / rel).read_text())
        except OSError:
            continue
    return "\n".join(out)


def check_directory(workflows: Path) -> list[str]:
    emitted: dict[str, set[str]] = {}  # prefix -> the producer files that emit it
    filters: set[str] = set()
    unfiltered_backstop = False

    for path in sorted(workflows.glob("*.yml")) + sorted(workflows.glob("*.yaml")):
        try:
            document = yaml.safe_load(path.read_text()) or {}
        except (OSError, yaml.YAMLError):
            continue
        if not isinstance(document, dict):
            continue
        body = _run_text(document)
        full = body + "\n" + _delegated_text(body, workflows)

        for prefix in EMITS_PREFIX.findall(body):
            if prefix:
                emitted.setdefault(prefix, set()).add(path.name)

        # ⛔ A BACKSTOP DECLARES ITS COVERAGE WHETHER IT IS SCHEDULED OR EXPORTED. A
        # library repo cannot schedule (no PAT, no org — see check_dereg_backstop), so it
        # ships a `workflow_call` wrapper that pins `name-prefixes`. That wrapper is where
        # its coverage is stated.
        #
        # ⚠ THIS IS THE THIRD TIME THIS SHAPE HAS BITTEN, and it bit inside the rule
        # written about it. #146 handled `uses:` delegation and not scripts; #156 handled
        # scripts; this handled SCHEDULED backstops and not EXPORTED ones — and reported
        # just-akash, whose coverage is correct and complete, as leaking. Handling one form
        # of a thing looks exactly like handling the thing.
        triggers = _on(document)
        if "schedule" not in triggers and "workflow_call" not in triggers:
            continue
        job_uses = " ".join(
            str(job.get("uses") or "")
            for job in (document.get("jobs") or {}).values()
            if isinstance(job, dict)
        )
        if not (DEREG_OP.search(full) or "reusable-stale-runner-reaper" in job_uses):
            continue
        found = set(NAME_FILTER_JQ.findall(full))
        for raw in NAME_FILTER_INPUT.findall(yaml.dump(document) + "\n" + full):
            found |= {p for p in raw.split(",") if p}
        if found:
            filters |= found
        elif "schedule" in triggers and "startswith(" not in full:
            # A SCHEDULED reaper that filters NOTHING by prefix reaps every offline runner
            # in the org, so it does cover everything this repo emits. Whether reaping other
            # repos' runners is SAFE is check_dereg_backstop's question, not this one.
            #
            # ⚠ `"startswith(" not in full` is load-bearing. A reaper that filters on a
            # field this rule cannot parse — `select(.url|startswith(...))` — is NOT
            # unfiltered; it filters, just not by a name this rule can read. Treating "I
            # found no NAME filter" as "it filters nothing" would claim blanket coverage
            # from an inability to parse, which is the strongest possible form of a green
            # that means nothing. If it filters and we cannot read it, we do not know.
            unfiltered_backstop = True
        # ⛔ A `workflow_call` dereg with no name filter is NOT blanket coverage — it is a
        # PER-RUN TEARDOWN, and a teardown only ever cleans up after the run that invoked
        # it. Treating it as covering everything made Blazing-Back PASS on the strength of
        # akash-close.yml while runner-time-to-ready.yml emitted `akash-` that nothing
        # reaps. An exported backstop contributes the prefixes it DECLARES, and nothing
        # more.

    if not emitted or unfiltered_backstop:
        return []

    findings: list[str] = []
    for prefix, producers in sorted(emitted.items()):
        if any(prefix.startswith(f) for f in filters):
            continue
        findings.append(
            f"{', '.join(sorted(producers))}: emits runner names beginning {prefix!r}, and no "
            f"scheduled backstop filters for it (backstop prefixes: "
            f"{sorted(filters) if filters else 'none found'}). Those registrations are "
            f"created and never reaped — the leak a backstop exists to drain."
        )
    return findings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("workflows", type=Path, help="a .github/workflows directory")
    args = parser.parse_args()
    if not args.workflows.is_dir():
        print(f"Backstop coverage: not a directory: {args.workflows}", file=sys.stderr)
        return 2
    documents = [
        p
        for p in sorted(args.workflows.glob("*.yml"))
        + sorted(args.workflows.glob("*.yaml"))
        if _is_workflow(p)
    ]
    if not documents:
        print(
            f"Backstop coverage: FAIL — found 0 WORKFLOW documents under {args.workflows}. "
            "A pass over an empty population is not compliance; check the path.",
            file=sys.stderr,
        )
        return 1
    findings = check_directory(args.workflows)
    for finding in findings:
        print(f"::error title=Backstop coverage::{finding}")
    if findings:
        print(f"Backstop coverage: FAIL ({len(findings)} finding(s))")
        return 1
    print(f"Backstop coverage: PASS — {len(documents)} workflow file(s) examined")
    return 0


def _is_workflow(path: Path) -> bool:
    try:
        document = yaml.safe_load(path.read_text())
    except (OSError, yaml.YAMLError):
        return True  # unreadable is not "not a workflow"
    return isinstance(document, dict) and bool({"on", True, "jobs"} & set(document))


if __name__ == "__main__":
    raise SystemExit(main())
