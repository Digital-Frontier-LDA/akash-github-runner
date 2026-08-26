#!/usr/bin/env python3
"""`DISABLE_AUTO_UPDATE` must be ABSENT from every runner definition.

⛔⛔ THE DEFECT — observed on just-akash deployment 1787733947684, four times in ~63s::

    Disable auto update option is enabled
    Current runner version: '2.334.0'
    2026-08-26 16:20:32Z: Listening for Jobs
    An error occurred: Runner version v2.334.0 is deprecated and cannot receive messages.
    ... supervisor restarts and RE-REGISTERS: 16:21:07, 16:21:21, 16:21:35

The runner REGISTERS fine and is then never sent a job. Three costs compound:

  * the Akash lease is PAID for its whole life having executed nothing;
  * every restart adds another org runner registration -- a registration PUMP. The listing
    stood at 3,071 on 2026-08-26, and its PAGE COUNT is what sets the pre-strike quota
    floor (1400), so this converts directly into refused CI;
  * the failure surfaces AFTER provisioning, so nothing cheaper catches it.

⇒ WHY A VERSION FLOOR CANNOT REPLACE THIS RULE. GitHub deprecates a runner version on a
DATE, not at merge. An image that satisfies a floor today is deprecated tomorrow with NO
code change, so a static version check passes and then rots. Auto-update is the only
mechanism that survives the NEXT deprecation. A digest pin still fixes a known starting
image; it must not also freeze the runner there.

⚠ PRESENCE, NOT VALUE — AND THAT IS THE WHOLE RULE. Measured in Blazing-Back run
31614227678: with `DISABLE_AUTO_UPDATE=false` the container STILL printed "Disable auto
update option is enabled" and stayed on the deprecated 2.334.0. The upstream entrypoint
tests the variable's PRESENCE, so any non-empty string -- including "false" -- applies
`--disableupdate`. A rule that accepted `=false` would certify the exact outage it exists
to prevent.

⚠ SDLs ARE IN SCOPE, NOT ONLY WORKFLOWS. just-akash set this at TWO sites --
`.github/workflows/runner-pool.yml` AND `sdl/github-runner-probe.yaml`. A workflows-only
scan would have reported PASS while half the fleet still froze its runner, which is the
"correct about what it looked at" failure this rule set keeps hitting. The repo root is
derived from the workflows dir and `sdl/` is scanned alongside it.
"""

from __future__ import annotations

import argparse
import importlib.util
import re
import sys
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "check_conformance_shim",
    Path(__file__).resolve().parents[1] / "baseline" / "check_conformance.py",
)
assert _SPEC and _SPEC.loader
_cc = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _cc
_SPEC.loader.exec_module(_cc)

Finding = _cc.Finding

# ⛔ MATCH THE SETTING, NOT THE MENTION — AND A KNOWN-NEGATIVE IS WHY.
# The first version matched the bare identifier anywhere outside a comment. Run against
# Blazing-Back (which correctly DELETED the variable) it flagged
# `runner-time-to-ready.yml:109-110` — that repo's OWN guard, whose grep and ::error
# message both name the variable. A rule that flags detection code as the defect is the
# "pattern that cannot match its own subject" trap in reverse: it matches everything that
# TALKS about the subject.
#
# The discriminator is the ASSIGNMENT shape. Two forms actually set it:
#     - DISABLE_AUTO_UPDATE=true        (SDL / docker env list, YAML sequence item)
#       DISABLE_AUTO_UPDATE: "true"     (workflow `env:` mapping)
# The value is still NOT parsed — presence is the defect, so `=false` and `=0` are
# findings too (the entrypoint tests presence, measured run 31614227678).
_ASSIGN = re.compile(
    r"""^\s*
        (?:-\s*DISABLE_AUTO_UPDATE\s*=      # env-list item:  - DISABLE_AUTO_UPDATE=...
         | DISABLE_AUTO_UPDATE\s*:)          # yaml mapping:   DISABLE_AUTO_UPDATE: ...
    """,
    re.VERBOSE,
)
# Lines that DETECT rather than set — a guard, an echo, an error message. Excluded so a
# repo may police this variable without tripping the rule that polices it.
_DETECTS = re.compile(r"\b(grep|echo|::error|::warning|if\s|test\s|\[\[)")


def _scan(path: Path) -> list[Finding]:
    out: list[Finding] = []
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return out
    for n, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        # A comment EXPLAINING the deletion is the documented fix, not a violation --
        # Blazing-Back's akash-runner.yml carries the whole analysis in comments.
        if stripped.startswith("#"):
            continue
        if _DETECTS.search(line):
            continue
        if _ASSIGN.search(line):
            out.append(
                Finding(
                    rule="disable-auto-update-absent",
                    severity="required",
                    path=str(path),
                    line=n,
                    message=(
                        "DISABLE_AUTO_UPDATE is present. The entrypoint tests PRESENCE, not "
                        "value, so even `=false` applies --disableupdate and freezes the "
                        "runner at a version GitHub will deprecate. DELETE the line."
                    ),
                )
            )
    return out


def _targets(workflows_dir: Path) -> list[Path]:
    """Workflow YAML plus any sibling `sdl/` — the second site lives there."""
    files = sorted(workflows_dir.glob("*.yml")) + sorted(workflows_dir.glob("*.yaml"))
    # .github/workflows -> repo root
    root = workflows_dir.parent.parent
    sdl = root / "sdl"
    if sdl.is_dir():
        files += sorted(sdl.glob("*.yml")) + sorted(sdl.glob("*.yaml"))
    return files


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workflows-dir", required=True)
    args = ap.parse_args()

    d = Path(args.workflows_dir)
    if not d.is_dir():
        print(f"::warning::{d} is not a directory — nothing to check")
        return 0

    files = _targets(d)
    if not files:
        # sites=0 is NOT-JUDGEABLE, never clean.
        print(f"[n-a] disable-auto-update-absent — no workflow or SDL files under {d}")
        return 0

    findings: list[Finding] = []
    for p in files:
        findings.extend(_scan(p))

    print(f"Scanned {len(files)} workflow/SDL file(s) under {d} and its sibling sdl/.")
    status = "pass" if not findings else "fail"
    print(f"[{status}] disable-auto-update-absent")
    for f in findings:
        print(
            f"::error file={f.path},line={f.line},title=DISABLE_AUTO_UPDATE::{f.message}"
        )
        print(f"  - [{f.severity}] {f.path}:{f.line}: {f.message}")
    return 0 if not findings else 1


if __name__ == "__main__":
    raise SystemExit(main())
