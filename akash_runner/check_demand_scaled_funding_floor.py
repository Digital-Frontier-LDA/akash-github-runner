#!/usr/bin/env python3
"""An Akash-provisioning workflow must DECLARE its demand and derive its floor from it.

⭐ THE OPERATOR'S ASK (2026-08-25): a funding floor scaled to demand is not just a
guard — it is a CONCURRENCY LIMITER that costs nothing. At max_slot 190 ACT with a
36 ACT floor (6 deposits × 6 ACT), ~5 runs are admissible; escrow becomes the
natural throttle, with NO cancel-in-progress and therefore no cancelled-run lease
leaks — the safe way to bound parallelism in a fleet where `concurrency:
cancel-in-progress` is a never-change invariant precisely because cancellation
skips closers.

⛔ THE FLOOR MUST BE **DERIVED, NOT CHOSEN**. The derived figure for Blazing-Back is
36 ACT (ci-pr.yml declares `AKASH_DEPOSITS_NEEDED: "6"`); an operator wanting retry
headroom says 50 via the existing override. Both are right at different scales, and
NEITHER is a constant a standard may carry: a hardcoded 50 in a shared place becomes
wrong the moment a repo needs 7 deposits. The one invariable is the FORM:

    floor = deposit_uact × declared_demand

A default demand of 1 is the bug the operator is paying for — it makes the gate a
no-op until a caller states demand, which is correct ONCE (adoption) and a standing
defect forever after. This rule therefore demands the DECLARATION be present with a
value ≥ 2 for any workflow that provisions, and that the floor expression reference
it — a literal floor beside a silent default is the measured #1617 pre-state.

⛔⛔ AND THE DEADLOCK MUST SURVIVE STANDARDISATION. A floor applied to RECOVERY
workflows (closers, sweepers, top-ups) wedges the fleet: no closer runs → no deposit
returns → the floor never opens → it looks like a working gate. Those workflows are
EXEMPT by this rule and must stay so — the exemption is load-bearing, not leniency.
Forward progress at the gated sites is the implementer's `budget = max(1, slot //
escrow_per_run)` shape (#1617's simulation: from ZERO headroom with 100 ACT locked,
recovers all of it because exactly one run is always admissible and its completion
returns a deposit).

⚠ SCOPE — WORKFLOWS THAT PROVISION AKASH DEPLOYMENTS. A workflow is in scope when a
`run:` block (comment-stripped — a sentence about deploying is not deploying) either
creates deployments (POST /v1/deployments, just-akash deploy, akash-runner call
shape) or calls a reusable that does. Reporting-only and pure-build workflows are
out of scope, and demanding a funding floor of them would be noise. The rule never
carries a number; it carries the FORM.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

import yaml

# A run: block that CREATES (or invokes creation of) Akash deployments.
_CREATES = re.compile(
    r"/v1/deployments|just[-_]akash deploy|runner-pool\.yml|akash-runner\.yml|"
    r"deploy_custom_sdl|create_deployment|MSG_DEPLOYMENT"
)
# A demand declaration, any of the spellings the fleet uses.
_DEMAND = re.compile(
    r"(AKASH_DEPOSITS_NEEDED|DEPOSITS_NEEDED|deposits[_-]needed|required_deposits)\s*[:=]\s*[\"\']?(\d+)"
)
# A floor derived from that demand (multiplied by / scaled with), not a bare literal.
_DERIVED_FLOOR = re.compile(
    r"(MIN_UACT|floor|escrow_per_run)\b[^#\n]{0,80}(DEPOSIT|deposit|demand|DEMAND|DEPOSITS)"
)
# Recovery-shaped workflows: closers, sweepers, reapers, top-ups. EXEMPT — see docstring.
_RECOVERY = re.compile(r"close|sweep|reap|cleanup|topup|top-up|drain|rollback", re.I)


def _load(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text())
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def _triggers(wf: dict[str, Any]) -> set[str]:
    on = wf.get("on", wf.get(True))
    if isinstance(on, str):
        return {on}
    if isinstance(on, list):
        return {str(x) for x in on}
    if isinstance(on, dict):
        return {str(k) for k in on}
    return set()


def _run_bodies(wf: dict[str, Any]) -> str:
    """Every run: block's text, comments stripped — code, not prose about code."""
    out: list[str] = []
    for job in (wf.get("jobs") or {}).values():
        if not isinstance(job, dict):
            continue
        for step in job.get("steps") or []:
            if isinstance(step, dict) and step.get("run"):
                body = "\n".join(
                    ln
                    for ln in str(step["run"]).splitlines()
                    if not ln.lstrip().startswith("#")
                )
                out.append(body)
    return "\n".join(out)


def _stripped_env(wf: dict[str, Any]) -> str:
    """Workflow/job/step env values, comments stripped, as one blob."""
    chunks: list[str] = []

    def _walk(node: Any) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                if k == "env" and isinstance(v, dict):
                    chunks.append(yaml.dump(v))
                else:
                    _walk(v)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(wf)
    return "\n".join(chunks)


def check_workflow(path: Path) -> list[str]:
    wf = _load(path)
    if not wf.get("jobs"):
        return []  # nothing runs; other rules own the unparseable case
    name = path.name.lower()
    # EXEMPT: recovery workflows are how the gate opens — flooring them is the wedge.
    if _RECOVERY.search(name):
        return []
    runs = _run_bodies(wf)
    env = _stripped_env(wf)
    if not (_CREATES.search(runs) or _CREATES.search(env)):
        return []  # does not provision; out of scope

    findings: list[str] = []
    declared = _DEMAND.search(env) or _DEMAND.search(runs)
    if not declared:
        findings.append(
            f"{path.name}: provisions Akash deployments but declares no DEMAND "
            "(DEPOSITS_NEEDED / required_deposits). The floor cannot be demand-scaled "
            "without it — a default of 1 is a no-op gate, which is the pre-#1617 defect."
        )
        return findings
    count = int(declared.group(2))
    if count < 2:
        findings.append(
            f"{path.name}: declares demand={count} — a floor of one deposit is the "
            "no-op shape, not a demand-scaled one. State the run's real create count."
        )
    if not _DERIVED_FLOOR.search(runs) and not _DERIVED_FLOOR.search(env):
        findings.append(
            f"{path.name}: demand is declared but no floor expression derives from it "
            "(deposit × demand). A literal floor beside a silent default is the "
            "measured pre-#1617 state: declared demand that computes nothing."
        )
    return findings


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--workflows-dir", default=".github/workflows")
    args = ap.parse_args(argv)

    d = Path(args.workflows_dir)
    if not d.is_dir():
        print(f"::warning::{d} is not a directory — nothing to check")
        return 0

    files = sorted(d.glob("*.yml")) + sorted(d.glob("*.yaml"))
    bad = 0
    for p in files:
        for finding in check_workflow(p):
            bad += 1
            print(f"::error file={p}::{finding}")
    if bad:
        print(
            "::error::A demand-scaled funding floor is a concurrency limiter that costs "
            "nothing — but only if the floor equals THIS repo's declared demand. Declare "
            "DEPOSITS_NEEDED and derive MIN_UACT = deposit × demand; recovery workflows "
            "are exempt (flooring them wedges the fleet)."
        )
        return 1
    print(
        f"OK: every provisioning workflow in {len(files)} file(s) declares its demand."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
