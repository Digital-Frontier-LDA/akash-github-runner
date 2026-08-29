#!/usr/bin/env python3
"""A CI gate must consume the shared primitive, not re-derive the verdict locally.

The generalisation of `check_funding_gate_is_not_re_derived.py`. That rule named one
primitive; this one is registry-driven and covers every (question, primitive) pair in
`gate_registry.GATES` — today funding and capacity, one per cloud we spend into.

⭐ WHY GENERALISED RATHER THAN COPIED. The defect is not "this repo got funding wrong".
It is "a consumer computed a verdict from raw numbers when a shared primitive already
answers the question". Copying the funding rule per cloud reproduces that mistake one
level up: two definitions of one defect, drifting, each fixed once.

⭐ AND THE CROSS-CUTTING ANTI-PATTERN IS WHY IT PAYS. Every gate is checked for
`collapses-unknown-into-declined` — reporting a SHORTAGE on a path an instrument FAILURE
also reaches. That is #1113. It has now been observed on three artefacts across two
clouds, and a per-cloud rule cannot see it, because each author meets it once and fixes
it locally.

  --gate all        (default) every registered gate
  --gate capacity   just the GKE capacity gate
  --gate funding    just the funding gate

⚠ `--gate all` DOUBLE-REPORTS with the older funding-only rule if both are wired against
the same tree. The conformance action deliberately invokes this one as `--gate capacity`
while `check_funding_gate_is_not_re_derived.py` still owns funding — it carries its own
promotion condition, which is still pending, and collapsing the two would discard that
record. Collapse them once funding promotes.

Exit codes: 0 = no findings, 1 = findings, 2 = the scan itself is broken.
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

try:  # dual-mode import: script (python3 akash_runner/check_x.py) and package (-m) invocations
    import cli_aliases
except ImportError:  # pragma: no cover - package mode only
    from akash_runner import cli_aliases

_GR_SPEC = importlib.util.spec_from_file_location(
    "akash_runner_gate_registry",
    Path(__file__).resolve().parent / "gate_registry.py",
)
assert _GR_SPEC and _GR_SPEC.loader
_gr = importlib.util.module_from_spec(_GR_SPEC)
sys.modules[_GR_SPEC.name] = _gr
_GR_SPEC.loader.exec_module(_gr)

GATES = _gr.GATES
audit = _gr.audit


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    cli_aliases.add_multi(ap, "--targets", "targets", "workflow file(s) or a workflows directory")
    ap.add_argument(
        "--gate", default="all", choices=["all", *sorted(GATES)],
        help="which registered gate(s) to check (default: all)",
    )
    args = ap.parse_args(argv)
    cli_aliases.require_multi(args, "targets", ap)

    gates = list(GATES.values()) if args.gate == "all" else [GATES[args.gate]]

    files: list[Path] = []
    for t in args.targets:
        p = Path(t)
        if p.is_dir():
            files.extend(sorted(q for q in p.glob("*.y*ml")))
        elif p.exists():
            files.append(p)
    if not files:
        # ⛔ An empty corpus is a BROKEN SCAN, not a clean repo. Exiting 0 here would
        # report "no gates re-derived" for a path that was never read.
        print("no workflow files found — the scan is broken, not the repo", file=sys.stderr)
        return 2

    problems: list[str] = []
    unreadable = 0
    for f in files:
        try:
            problems.extend(audit(f, gates))
        except Exception as exc:  # noqa: BLE001
            # Surface, never swallow: a file we could not parse is a file we did not check.
            unreadable += 1
            print(f"  ⚠ {f.name}: could not audit ({type(exc).__name__}: {exc})")

    print(
        f"gates checked: {', '.join(g.name for g in gates)}  "
        f"workflows: {len(files)}  findings: {len(problems)}  unreadable: {unreadable}"
    )
    for p in problems:
        print(f"  {p}")

    # ⛔⛔ A PARTIAL SCAN IS NOT A PASS, AND IT IS NOT A COMPLETE FINDING SET EITHER.
    #
    # This block printed "OK: every in-scope gate routes through its primitive" and
    # returned 0 whenever `problems` was empty — INCLUDING when files had failed to audit.
    # A rule whose entire job is catching false all-clears was emitting one.
    #
    # It is `collapses-unknown-into-declined` INVERTED: that anti-pattern reports a
    # SHORTAGE on an instrument failure; this reported a CLEAN BILL on one. Same root —
    # a could-not-measure collapsing into a measured verdict — opposite direction, and the
    # quieter of the two, because nobody investigates a pass.
    #
    # ⚠ Findings still print above: an unreadable file does not make the findings we DID
    # get untrue. But `unreadable` dominates the exit code, because 1 would tell a consumer
    # "these are all of them" when the unaudited files may carry more.
    if unreadable:
        print(
            f"⛔ PARTIAL SCAN — {unreadable} of {len(files)} workflow(s) could not be "
            "audited. This is NOT a pass and NOT a complete finding set: the unaudited "
            "files may carry either. Fix the unparseable file(s) and re-run."
        )
        return 2
    if not problems:
        print("  OK: every in-scope gate routes through its primitive.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
