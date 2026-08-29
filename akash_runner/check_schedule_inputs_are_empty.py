#!/usr/bin/env python3
"""A schedule supplies no inputs, so `inputs.X || 'false'` means "destroy" on the cron.

⛔ THE DEFECT, MEASURED. Blazing-Back's `cleanup-stale-akash.yml` closes Akash
deployments. Its destructive-mode flag read:

    DRY_RUN: ${{ github.event.inputs.dry_run || 'false' }}

A `schedule` event carries NO inputs, so `github.event.inputs.dry_run` is the empty
string on every cron firing, `||` falls through, and the UNATTENDED path ran with
`DRY_RUN=false` — closing for real, six times a day, with nobody watching.

⚠ AND IT WAS INVISIBLE BECAUSE THE JOB WAS BROKEN. That workflow had closed nothing in
283 consecutive runs (it matched ownership against an SDL no API returns), so the
unattended-destroy setting cost nothing and nobody looked at it. The moment the matcher
was repaired the same expression became live. ⇒ **A dangerous default hides behind a
broken feature until the feature is fixed.** The repair is what arms it.

⭐ THE GENERAL SHAPE, which is why this is a rule and not a one-line fix: an expression
that is CORRECT for `workflow_dispatch` and MEANINGLESS for `schedule`, in a workflow
that has both triggers. `inputs.*` is not merely absent on the cron path — it is empty,
and an empty string is falsy, so every `||` default silently wins. The author writes one
expression and gets two behaviours, and only one of them was designed.

⇒ WHAT THIS RULE DEMANDS. A workflow that (a) has an `on: schedule` trigger and (b)
reads `github.event.inputs.*` must discriminate the path — typically
`github.event_name == 'schedule' && <safe> || <the input expression>` — or declare in
`SCHEDULE_INPUT_EXEMPT` why the empty value is safe there.

⚠ SCOPE IS DELIBERATELY NARROW: schedule-triggered workflows only. A workflow without a
cron cannot exhibit this, and demanding the guard everywhere would be noise. A workflow
whose inputs are all non-destructive (a label, a log level) is exempt with a reason —
the harm is specific to a flag that gates an irreversible action.

★ THE PROPERTY WORTH KEEPING: this is not "remember to check dry_run". It is that
`inputs.*` has a DIFFERENT MEANING under a trigger that supplies none, and the language
gives you no signal — no error, no warning, just the fallback. The only way to see it is
to ask what each trigger makes the expression evaluate to.
"""

from __future__ import annotations

import argparse

import _cli
import re
import sys
from pathlib import Path
from typing import Any

import yaml

# `github.event.inputs.X` and the modern `inputs.X`. Both are empty under `schedule`.
_INPUT_REF = re.compile(r"\$\{\{[^}]*?\b(?:github\.event\.inputs|inputs)\.([A-Za-z0-9_-]+)[^}]*\}\}")
# A discriminator: the expression asks WHICH event fired before trusting the input.
_EVENT_NAME_GUARD = re.compile(r"github\.event_name\s*==\s*'(?:schedule|workflow_dispatch)'")

# Exemptions must name the workflow AND why an empty input is harmless there. An
# exemption without a reason is a permanent silence; this file makes the reason readable.
SCHEDULE_INPUT_EXEMPT: dict[str, str] = {}


def _load(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text())
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def _triggers(wf: dict[str, Any]) -> set[str]:
    """The trigger names. ⚠ YAML parses a bare `on:` as the BOOLEAN True, not the string
    'on' — the single most common way a workflow-parsing rule reads zero triggers and
    passes vacuously on every file it was written for."""
    on = wf.get("on", wf.get(True))
    if isinstance(on, str):
        return {on}
    if isinstance(on, list):
        return {str(x) for x in on}
    if isinstance(on, dict):
        return {str(k) for k in on}
    return set()


def offending_expressions(text: str) -> list[str]:
    """Lines that read an input WITHOUT discriminating on the event name."""
    out = []
    for line in text.splitlines():
        if not _INPUT_REF.search(line):
            continue
        if _EVENT_NAME_GUARD.search(line):
            continue  # the author asked which event fired — that is the fix
        out.append(line.strip())
    return out


def check_workflow(path: Path) -> list[str]:
    wf = _load(path)
    if "schedule" not in _triggers(wf):
        return []  # cannot exhibit the defect
    if path.name in SCHEDULE_INPUT_EXEMPT:
        return []
    return offending_expressions(path.read_text())


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

    files = sorted(d.glob("*.yml")) + sorted(d.glob("*.yaml"))
    scheduled = [p for p in files if "schedule" in _triggers(_load(p))]
    print(f"Scanned {len(files)} workflow(s); {len(scheduled)} carry an `on: schedule` trigger.")

    bad = 0
    for p in files:
        for line in check_workflow(p):
            bad += 1
            print(
                f"::error file={p}::A schedule supplies NO inputs, so this expression "
                f"falls through to its default on every cron firing: {line}"
            )
    if bad:
        print(
            "::error::Discriminate the path — `github.event_name == 'schedule' && <safe> "
            "|| <input expr>` — or add the workflow to SCHEDULE_INPUT_EXEMPT with a reason."
        )
        return 1
    print("OK: no scheduled workflow trusts an input the schedule cannot supply.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
