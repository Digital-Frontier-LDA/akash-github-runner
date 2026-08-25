#!/usr/bin/env python3
"""A runner pool must not be schedulable before the consumers it serves.

⛔ THE DEFECT. A job that provisions EPHEMERAL runners and a job that consumes them
are scheduled independently. If the pool's `needs` are a strict subset of its
consumer's, the pool starts EARLIER -- and ephemeral runners are consumed or expire
while the consumer is still blocked. The consumer then arrives to an empty label and
queues forever against runners nothing will serve.

⇒ MEASURED, TWICE, IN ONE RUN (Borduas-Holdings/Blazing-Back run 32837603555):

    provision-cd-pool       needs: []                     -> fired at T+2min
      its 6 C/D consumers   needs: [canary-deploy, ...]   -> blocked ~25min
      result: 0 of 6 legs ran, runner=NONE, three attempts running

    provision-akash-runner  needs: [classify-changes]     -> fired at T+2min
      mesh-e1               needs: [..., recovery-c0/1/2] -> blocked ~25min
      result: E1 queued 25+min, runner=NONE

⭐ AND THE TWO POOLS WERE VISIBLE SIDE BY SIDE ON THE SAME RUN once the first was
fixed: 12 `df-core-cdpool-<run>` runners ONLINE and IDLE, and ZERO `ci-<run>`
runners. The fix works; the unfixed pool showed the original defect unchanged.

⚠ WHY A HUMAN MISSES IT. The provisioner reports SUCCESS -- it genuinely observed a
full pool (`akash_ci_runners_online 12`, `outcome=healthy`, round 1). Nothing is red.
The only symptom is a consumer that never starts, and `runs-on` is evaluated at
SCHEDULING, so no step exists in which a guard could run: a guard would need a runner
in order to execute. That is why this must be checked STATICALLY.

⚠ AND THE FALLBACK CANNOT SAVE IT. `runner-targets` falls back to `ubuntu-latest`
only when provisioning is UNHEALTHY. There is no path for "healthy, then evaporated".

THE INVARIANT
-------------
For every pool P and every consumer C of P:

    needs(P)  MUST INCLUDE  needs(C) - {P} - {other consumers of P}

i.e. every external gate the consumer waits on must also gate the pool. Excluding
the consumers themselves is required: the raw union self-references (a C/D consumer
needs a sibling C/D job, which needs the pool) and would demand a cycle.

This is ordering only. It never touches `concurrency`, and it cannot cause
cancellation.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys

import yaml

# A consumer names its pool through the pool's runner-targets output.
_TARGETS = re.compile(r"needs\.(?P<pool>[A-Za-z0-9_-]+)\.outputs\.runner-targets")
_STATUS_CHECK = re.compile(r"\b(?:always|cancelled|failure|success)\s*\(")


def _jobs(document: dict) -> dict:
    return document.get("jobs") or {}


def _needs(job: dict) -> set:
    n = job.get("needs") or []
    return set(n) if isinstance(n, list) else {n}


def _liveness_findings(pool: str, job: dict) -> list[str]:
    """Report the implicit-success gate introduced by adding ``needs``.

    A pool with dependencies but no status-check function inherits GitHub's
    implicit ``success()`` condition.  That turns an ordering constraint into
    a liveness gate: one failed/skipped prerequisite prevents the pool from
    provisioning, while consumers can remain queued for its labels.
    """
    if not _needs(job):
        return []
    expression = str(job.get("if", ""))
    if _STATUS_CHECK.search(expression):
        if re.search(r"\balways\s*\(", expression):
            return [
                f"{pool} has needs but uses always(): ordering is checked, "
                "but a cancelled run can still provision and leak its lease"
            ]
        return []
    return [
        f"{pool} has needs but its if expression has no status-check function; "
        "GitHub applies implicit success() and can skip the pool before it provisions"
    ]


def pools_and_consumers(document: dict) -> dict:
    """pool name -> set of jobs whose runs-on resolves that pool's targets."""
    out: dict = {}
    for name, job in _jobs(document).items():
        if not isinstance(job, dict):
            continue
        m = _TARGETS.search(str(job.get("runs-on", "")))
        if m:
            out.setdefault(m.group("pool"), set()).add(name)
    return out


def check(document: dict) -> list:
    findings = []
    jobs = _jobs(document)
    for pool, consumers in sorted(pools_and_consumers(document).items()):
        if pool not in jobs:
            findings.append(f"{pool}: consumed by {sorted(consumers)} but no such job exists")
            continue
        pool_needs = _needs(jobs[pool])
        findings.extend(_liveness_findings(pool, jobs[pool]))
        for consumer in sorted(consumers):
            # external gates only: drop the pool itself and sibling consumers,
            # which would otherwise demand a cycle.
            external = _needs(jobs[consumer]) - {pool} - consumers
            missing = external - pool_needs
            if missing:
                findings.append(
                    f"{pool} can be scheduled before its consumer {consumer}: "
                    f"{consumer} waits on {sorted(missing)} and {pool} does not. "
                    f"Ephemeral runners provisioned that early expire before {consumer} "
                    f"unblocks, and it will queue against a label nothing serves."
                )
    return findings


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--workflows-dir", required=True)
    args = ap.parse_args()

    root = pathlib.Path(args.workflows_dir)
    files = sorted(list(root.glob("*.yml")) + list(root.glob("*.yaml")))
    if not files:
        print(f"::error::no workflow files under {root} -- the locator is stale")
        return 2

    examined = 0
    rc = 0
    for path in files:
        try:
            document = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            continue
        if not isinstance(document, dict) or not _jobs(document):
            continue
        pools = pools_and_consumers(document)
        if not pools:
            continue
        examined += 1
        for finding in check(document):
            print(f"::error file={path},title=Pool scheduled before its consumer::{finding}")
            rc = 1

    # ⛔ NON-VACUITY. A pass over zero pools certifies nothing.
    if examined == 0:
        print("Pool ordering: no workflow declares a runner pool -- NOT APPLICABLE")
        return 0
    if rc == 0:
        print(f"Pool ordering: PASS -- {examined} workflow(s) declaring pools examined")
    return rc


if __name__ == "__main__":
    sys.exit(main())
