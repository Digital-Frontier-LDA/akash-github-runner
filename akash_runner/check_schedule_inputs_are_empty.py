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
`github.event_name == 'schedule' && <safe> || <the input expression>`.

⚠ THE EXEMPTION IS NOT YOURS TO ADD, AND THIS LINE USED TO IMPLY IT WAS. It said "or
declare in `SCHEDULE_INPUT_EXEMPT` why the empty value is safe there" — a dict that lives
in THIS file, in akash-github-runner, which a consumer repo cannot edit. The emitted error
message was corrected to say so; this docstring was not, so a reader arriving here still
got the unreachable advice. An exemption is a PR against this repo naming the workflow and
why its default is safe.

⇒ FORMS THAT ALSO DISCRIMINATE, and are accepted:
  `github.event_name != 'schedule' && <input expr>`   — short-circuits false on a cron
  `inputs.X == true`                                  — `null == true` is false, always

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
_INPUT_REF = re.compile(
    r"\$\{\{[^}]*?\b(?:github\.event\.inputs|inputs)\.([A-Za-z0-9_-]+)[^}]*\}\}"
)
# A discriminator: the expression asks WHICH event fired before trusting the input.
#
# ⛔ `!=` IS THE SAME QUESTION, AND ONLY `==` WAS ACCEPTED. `github.event_name !=
# 'schedule' && inputs.dry-run` short-circuits to `false` on a cron without consulting the
# input at all — identical safety to the accepted form, reported as a fall-through.
#
# ⚠ BUT ONLY `!= 'schedule'`, AND THE FIRST VERSION OF THIS LINE GOT IT WRONG. Widening to
# `(?:==|!=)\s*'(?:schedule|workflow_dispatch)'` also accepts `!= 'workflow_dispatch'`,
# which is TRUE on a scheduled run — so `github.event_name != 'workflow_dispatch' &&
# (inputs.X || 'false')` would be exempted while falling through on exactly the path this
# rule exists to catch. An exemption that fires on the cron path is worse than the finding
# it silences. Raised by Copilot on #65.
#
# ⇒ Safe forms, and why each is safe on a SCHEDULE firing:
#     == 'schedule'            selects the safe branch explicitly
#     == 'workflow_dispatch'   false on a cron → short-circuits before the input
#     != 'schedule'            false on a cron → short-circuits before the input
#     != 'workflow_dispatch'   TRUE on a cron → NOT a discriminator
# ⚠ AND `!= 'schedule'` ONLY WHERE IT SHORT-CIRCUITS. The safety comes entirely from `&&`:
# `!= 'schedule' && <expr>` never evaluates <expr> on a cron, but
# `!= 'schedule' || (inputs.X || 'false')` evaluates it every time. Accepting the mere
# PRESENCE of the comparison exempts the second. Third instance of the same mistake in this
# regex — widening the shape without constraining how it is used. Raised by Copilot on #65.
_EVENT_NAME_GUARD = re.compile(
    r"github\.event_name\s*==\s*'(?:schedule|workflow_dispatch)'"
    r"|github\.event_name\s*!=\s*'schedule'\s*\)*\s*&&"
)

# ⛔ AND THE RULE FLAGGED ITS OWN REFERENCE IMPLEMENTATION. Measured 2026-09-03 against
# Borduas-Holdings/Blazing-Back, the caller this repo's `reusable-akash-escrow-reaper.yml`
# ships as the example:
#
#     escrow-reaper.yml :: execute: ${{ inputs.execute == true }}
#
# There is no `||` in that expression. A schedule supplies nothing, so it evaluates
# `null == true` → FALSE, on every cron firing, forever. That is not a fall-through to a
# default — it is the safe value, reached by comparison. Flagging it taught the fleet's
# most-copied caller that the rule does not understand the shape it recommends by example.
#
# ⚠ ONLY AGAINST `true`, AND THE ASYMMETRY IS THE WHOLE POINT. `inputs.X == false` yields
# TRUE under a schedule, which is exactly the silent-destructive-default this rule exists
# to catch — so it stays a finding. An absent input can never equal `true`; it can very
# easily equal `false`.
_INPUT_EQUALS_TRUE = re.compile(
    r"\b(?:github\.event\.inputs|inputs)\.[A-Za-z0-9_-]+\s*==\s*(?:true|'true'|\"true\")"
)

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
        if _INPUT_EQUALS_TRUE.search(line) and "||" not in line:
            # Comparison, not fallback: `null == true` is false on every cron firing.
            # ⚠ The `||` exclusion matters — `(inputs.a == true) || inputs.b` puts a
            # fall-through back on the same line, and the comparison must not launder it.
            continue
        out.append(line.strip())
    return out


def _executable(text: str) -> str:
    """The workflow with WHOLE-LINE YAML COMMENTS REMOVED.

    ⛔ A COMMENT IS NOT EVIDENCE. This rule scans raw workflow text, so a comment that
    QUOTES the defective expression was reported as the defect (agr#54, reproduced while
    fixing blazing#786). The emitted finding even carried the leading `#` and a sentence
    fragment:

        ::error::... falls through to its default on every cron firing:
                 # `${{ inputs.dry-run || 'false' }}` selected the DESTRUCTIVE path by

    ⚠ THE INCENTIVE WAS BACKWARDS. Rewording the comment made it pass, so the verdict
    depended on how the fix was DESCRIBED, and the workaround was to not explain it — in a
    codebase whose comments carry the measured incidents. `check_escrow_reaper_is_adopted`
    grew the same helper for the same reason; this one had no equivalent.

    Only lines whose FIRST non-whitespace character is `#` are dropped. A trailing `#` can
    sit inside a quoted string, and guessing at that would blind the rule to a real
    expression on the same line.
    """
    return "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )


def check_workflow(path: Path) -> list[str]:
    wf = _load(path)
    if "schedule" not in _triggers(wf):
        return []  # cannot exhibit the defect
    if path.name in SCHEDULE_INPUT_EXEMPT:
        return []
    return offending_expressions(_executable(path.read_text()))


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
    print(
        f"Scanned {len(files)} workflow(s); {len(scheduled)} carry an `on: schedule` trigger."
    )

    bad = 0
    for p in files:
        for line in check_workflow(p):
            bad += 1
            print(
                f"::error file={p}::A schedule supplies NO inputs, so this expression "
                f"falls through to its default on every cron firing: {line}"
            )
    if bad:
        # ⛔ HALF THIS MESSAGE USED TO BE UNREACHABLE FROM WHERE IT IS READ. It said "add
        # the workflow to SCHEDULE_INPUT_EXEMPT with a reason" — but that dict lives HERE,
        # in this rule file, in akash-github-runner. A consumer repo cannot edit it. The
        # reader followed the advice, found no such symbol in their own tree, and was left
        # with a remedy that does not exist on their side of the boundary.
        #
        # ⚠ And the expression half was wrong in the direction that matters. For a
        # `type: boolean` input an unchecked box is the value `false`, so
        # `(inputs.dry-run || 'true')` evaluates `false || 'true'` -> 'true': an operator's
        # explicit "no, go live" silently becomes a dry run. The chain below works because
        # 'false' is a NON-EMPTY, therefore truthy, string to `||`.
        print(
            "::error::Discriminate the path. For a boolean input:\n"
            "  ${{ github.event_name == 'schedule' && 'false' "
            "|| (inputs.dry-run && 'true' || 'false') }}\n"
            '  ⚠ the consuming script MUST compare by equality — [ "$DRY_RUN" = "true" ]. '
            'Both [ -n "$VAR" ] and ${VAR:+--flag} FIRE on the string "false".\n'
            "  An exemption is possible but NOT from your repo: SCHEDULE_INPUT_EXEMPT lives "
            "in akash-github-runner/akash_runner/check_schedule_inputs_are_empty.py. "
            "Open a PR there naming the workflow and why its default is safe."
        )
        return 1
    print("OK: no scheduled workflow trusts an input the schedule cannot supply.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
