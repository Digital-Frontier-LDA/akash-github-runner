#!/usr/bin/env python3
"""A backstop reaper must declare a schedule, or declare why it does not.

⛔ THE DEFECT. just-akash shipped THREE cleanup mechanisms and, until 2026-08-23,
ZERO of them ran automatically. `cleanup-stale.yml` and `close-orphans.yml` were both
dispatch-only, so the backstop layer that was supposed to catch leaked leases existed
only as workflows nobody triggered. The docstrings described a safety net; nothing ran it.

⚠ SCOPE — A PER-RUN TEARDOWN IS NOT A BACKSTOP REAPER, and conflating them is a category
error that would demand a cron on a workflow invoked once per run:

    runner-teardown.yml   on: workflow_call            per-run closer   OUT OF SCOPE
    cleanup-stale.yml     on: schedule + dispatch      backstop reaper  IN SCOPE, passes
    close-orphans.yml     on: workflow_dispatch        backstop reaper  IN SCOPE, exempt

A workflow reachable by `workflow_call` runs when its caller runs; demanding a cron of it
is meaningless. Scope is reaper-shaped AND not `workflow_call`-invocable.

⛔⛔ AND SOME REAPERS MUST NOT BE SCHEDULED. `close-orphans.yml` takes a REQUIRED `dseqs`
input with NO default, deliberately: a cron cannot supply a safe list, and scheduling it
invites the wildcard sweep that once destroyed 14 third-party deployments. A blanket
"every reaper is scheduled" rule would demand a change that REINTRODUCES a destructive
sweep — the rule would be actively harmful.

⇒ SO THE EXEMPTION IS FALSIFIABLE, NOT PROSE. Each entry names the input whose
required-and-defaultless shape IS the justification, and this checker RE-VERIFIES that
shape on every run. If someone later gives `dseqs` a safe default, a cron becomes
possible, the stated reason stops being true, and the exemption EXPIRES BY ITSELF — the
workflow starts failing until it is scheduled or re-justified.

★ That is the property a `restore_when:` comment can never have. An exemption nobody
re-examines is permanent by default; this one re-examines itself.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

import yaml

# Reaper-shaped by name. Deliberately narrow: this rule demands a CRON, and a false
# positive here is a demand to schedule something that should not be scheduled.
# ⚠ `s?` IS LOAD-BEARING. Without it "close-orphans.yml" does not match — "orphan" is
# followed by "s", which is not a boundary — so the one workflow this rule's exemption
# exists for was silently OUT OF SCOPE, and the exemption test passed vacuously.
# `test_the_selector_matches_the_real_filenames` is the control that catches it.
REAPER_NAME = re.compile(
    r"(?:^|[-_])(?:cleanup|reap|sweep|orphan|stale|prune)s?(?:$|[-_.])", re.I
)


class Exemption:
    """An unscheduled reaper, and the machine-checkable reason it stays that way.

    ``required_input_without_default`` names an input which, being required and having no
    default, makes a scheduled run impossible to supply safely. The checker asserts that
    is STILL true — the exemption cannot outlive its own justification.
    """

    def __init__(self, reason: str, required_input_without_default: str) -> None:
        self.reason = reason
        self.required_input_without_default = required_input_without_default


EXEMPT: dict[str, Exemption] = {
    "close-orphans.yml": Exemption(
        reason=(
            "dseqs is required with no default and a cron cannot supply a safe list; "
            "scheduling it invites the wildcard sweep that once destroyed 14 third-party "
            "deployments. Approved by TEAMLEAD 2026-08-23."
        ),
        required_input_without_default="dseqs",
    ),
}


def _on(document: dict[str, Any]) -> dict[str, Any]:
    # ⚠ YAML 1.1: a bare `on:` key parses as the BOOLEAN True, not the string "on".
    # Reading document["on"] alone silently finds nothing and every workflow looks
    # trigger-less — which would make this rule fire on everything, or nothing.
    for key in ("on", True):
        value = document.get(key)
        if isinstance(value, dict):
            return value
        if isinstance(value, list):
            return dict.fromkeys(value, None)
        if isinstance(value, str):
            return {value: None}
    return {}


def _inputs(triggers: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for trigger in ("workflow_dispatch", "workflow_call"):
        section = triggers.get(trigger)
        if isinstance(section, dict):
            found = section.get("inputs")
            if isinstance(found, dict):
                merged.update(found)
    return merged


def check_workflow(path: Path, document: dict[str, Any]) -> list[str]:
    name = path.name
    if not REAPER_NAME.search(name):
        return []
    triggers = _on(document)
    if "workflow_call" in triggers:
        # Runs when its caller runs. A cron would be meaningless.
        return []
    if "schedule" in triggers:
        return []

    exemption = EXEMPT.get(name)
    if exemption is None:
        return [
            f"{name}: backstop reaper declares no schedule and no exemption — it runs only "
            f"when a human remembers, which is how three cleanup mechanisms ran zero times"
        ]

    field = exemption.required_input_without_default
    spec = _inputs(triggers).get(field)
    if not isinstance(spec, dict):
        return [
            f"{name}: exemption cites input {field!r}, which no longer exists — the stated "
            f"reason is no longer true, so schedule it or re-justify the exemption"
        ]
    if not spec.get("required") or "default" in spec:
        return [
            f"{name}: exemption rests on {field!r} being required with no default, but it is "
            f"now required={spec.get('required')!r} default={spec.get('default')!r} — a "
            f"scheduled run is supplyable, so the exemption has expired"
        ]
    return []


def check_directory(workflows: Path) -> list[str]:
    findings: list[str] = []
    for path in sorted(workflows.glob("*.yml")) + sorted(workflows.glob("*.yaml")):
        try:
            document = yaml.safe_load(path.read_text()) or {}
        except (OSError, yaml.YAMLError) as exc:
            # ⚠ Unreadable is NOT clean. A parse failure that returned no findings would
            # make a broken workflow indistinguishable from a compliant one.
            findings.append(
                f"{path.name}: could not be read, so it was NOT checked: {exc}"
            )
            continue
        if isinstance(document, dict):
            findings.extend(check_workflow(path, document))
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
        print(f"Reaper schedule: not a directory: {args.workflows}", file=sys.stderr)
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
            f"Reaper schedule: FAIL — found 0 WORKFLOW documents under {args.workflows} "
            f"({matched} yaml file(s) matched, none declaring `on:` or `jobs:`). "
            "A pass over an empty population is not compliance; check the path.",
            file=sys.stderr,
        )
        return 1
    findings = check_directory(args.workflows)
    for finding in findings:
        print(f"::error title=Reaper schedule::{finding}")
    if findings:
        print(f"Reaper schedule: FAIL ({len(findings)} finding(s))")
        return 1
    print(f"Reaper schedule: PASS — {examined} workflow file(s) examined")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
