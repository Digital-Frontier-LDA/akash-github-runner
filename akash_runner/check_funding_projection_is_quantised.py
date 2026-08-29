"""A funding gate must not extrapolate a rate from two allowance samples.

MEASURED 2026-08-24, and this rule exists because the defect was live in a
consuming repo's `akash-runner.yml` for months.

The Akash on-chain allowance does not drift. It moves in DISCRETE quanta of one
deployment's escrow deposit (5.00 ACT) and is FLAT between steps. A 40-sample
series at 20s intervals measured 30 of 39 intervals with NO movement at all, and
every non-zero delta an integer multiple of the deposit:

    -5.00 x4 · +5.00 x3 · +10.00 x1 · +14.97 x1

(The +14.97 rather than +15.00 is three closes returning deposit MINUS ~0.03 rent
consumed — the escrow model showing itself in the residual.)

⛔ THE DEFECT: a gate that samples the allowance TWICE, `gap` seconds apart, and
projects the difference linearly over a `horizon` cannot distinguish a STEP from
a SLOPE. If a single deployment is created inside the sampling window the gate
reads "fell 5.00 ACT in 60s", projects exhaustion, and refuses — while the same
window landing between steps reads flat and allows. The two windows can END AT
THE SAME FUNDED LEVEL and get opposite verdicts.

Measured false-positive rate on the live gate: P(a step lands inside a 60s
window) ~ 54%; only a FALLING step projects a refusal, so ~24% of invocations
refused for a reason that is an artefact of two-point sampling — preferentially
when the queue is busy, i.e. exactly when provisioning matters.

⚠ THE DEFECT IS ONE-SIDED. It is a false BLOCK of a funded account, never a
false pass at a starved one — the floor comparison still catches a genuine
shortfall. That is narrower than "the gate is broken" and it is the true claim.

⇒ THE CONTRACT: decide on the QUANTISED level (how many whole deposits fit,
right now), never on a fitted rate. `akash-lease-core`'s `evaluate_funding`
implements this; consumers should call it rather than re-deriving. Sampling the
allowance repeatedly for OPERATOR DIAGNOSTICS is fine and this rule permits it —
what it forbids is feeding an extrapolation into the gate decision.

⚠ WHAT THIS RULE DELIBERATELY DOES NOT DO: it does not flag a second read. Two
reads are legitimate (a retry, a settle-wait, a diagnostic series). It flags the
co-occurrence of a second read AND a forward extrapolation of the delta, which
is the only shape that produces the phase-dependent verdict.
"""

from __future__ import annotations

import _cli

import re
from typing import Any  # noqa: F401  (parity with sibling rules' signature style)

# Re-use the conformance baseline's Finding/RuleResult — same shape, same severity
# semantics. Importing is a one-way edge, matching check_unvalidated_default.
import importlib.util
import sys
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "check_conformance_shim_funding",
    Path(__file__).resolve().parents[1] / "baseline" / "check_conformance.py",
)
assert _SPEC and _SPEC.loader
_cc = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _cc
_SPEC.loader.exec_module(_cc)

Finding = _cc.Finding
RuleResult = _cc.RuleResult
_read = _cc._read
_line_of = _cc._line_of

# ⛔ THE CORPUS FIX (#171). This rule used to slice the RAW FILE into 60-line
# half-overlapping windows, so its four conjuncts only had to co-occur in a 60-line SPAN —
# not in one shell script, not in one job, and not in code at all. Two probes reproduced it:
# all four tokens present ONLY in a comment (code was `echo "hello"`) was flagged, and the
# four tokens split across FOUR SEPARATE JOBS was flagged. A rule built to catch an artefact
# asserting a property it does not have, firing on a sentence describing the defect, IS that
# defect. The patterns, severity, measurement and message below are UNCHANGED — only the
# corpus they match against is.
_WC_SPEC = importlib.util.spec_from_file_location(
    "akash_runner_workflow_corpus",
    Path(__file__).resolve().parent / "workflow_corpus.py",
)
assert _WC_SPEC and _WC_SPEC.loader
_wc = importlib.util.module_from_spec(_WC_SPEC)
sys.modules[_WC_SPEC.name] = _wc
_WC_SPEC.loader.exec_module(_wc)

run_blocks = _wc.run_blocks


# ── Patterns ──────────────────────────────────────────────────────────────────

# The quantity being gated on. Both spellings appear in the fleet: the on-chain
# authz `spend_limits` (which actually gates a create) and Console's
# `deploy_credit` (which does not). A projection over EITHER is the defect.
# ⛔ THIRD INSTANCE OF THE SAME BUG IN THIS FILE. `\b(allowance|...)\b` matches NONE of the
# identifiers the real gate uses — `allowance_uact`, `read_allowance`, `allowance2_uact` —
# because `_` is a word character on BOTH sides. It matched only bare English, e.g. the word
# ALLOWANCE inside `::error title=ALLOWANCE COLLAPSING`. A known-positive built on that
# passes while the rule is blind to every real spelling. No boundaries on this family.
_ALLOWANCE = re.compile(r"(allowance|deploy_credit|spend_limits?|credit_uact)", re.I)

# A second sample: an explicit wait between reads. `sleep N` is how every shell
# implementation of this does it.
# ⛔ THE GAP IS A VARIABLE IN THE REAL ARTEFACT. This was `\bsleep\s+\d+` — LITERAL digits
# — and the gate it was written from writes `sleep "$DELTA_GAP_SEC"` (akash-runner.yml:467).
# So the rule could not detect the defect it was measured from: its known-positive wrote
# `sleep 60`, and that literalisation was the only reason the fixture matched. Verified by
# running BOTH the pre-fix and post-fix rule against the real file — rc=0 both times.
# A known-positive paraphrased from an artefact is not a known-positive FROM it.
_SECOND_SAMPLE = re.compile(r"""\bsleep\s+(\d+|["']?\$\{?[A-Za-z_][A-Za-z_0-9]*)""")

# The extrapolation itself. Any of:
#   - a named projection/forecast/extrapolation
#   - a per-second/per-minute rate derived from a delta
#   - a horizon applied to a drop
_PROJECTION = re.compile(
    # ⛔ `project(ed|ion)?\b` CANNOT MATCH `projected_uact` — `_` is a word character, so the
    # trailing \b fails on exactly the identifier the real gate uses (akash-runner.yml:486).
    # Before this, the only match in the real file was the ENGLISH word "projected" inside an
    # echo four lines later, so the rule cited line 490 (a notice) instead of 486 (the
    # arithmetic). Leading boundary only.
    r"(\bproject"
    r"|extrapolat"
    r"|forecast"
    r"|\brate[_ ]?per[_ ]?(sec|min)"
    r"|\bat\s*\+\s*\d+\s*s\b"
    r"|\b(drop|delta|fell)\b[^\n]{0,80}\b(horizon|window|per\s+\d+s)\b)",
    re.I,
)

# A gate decision — the projection only matters if it can refuse.
_DECISION = re.compile(r"(::error|exit\s+[1-9]|would\s+create|refus|abort|fail\s+fast)", re.I)

# How far apart the three signals may sit and still be one logical block.
def check_workflow(path: Path) -> list[Finding]:
    """Flag blocks that extrapolate an allowance delta into a gate decision."""
    findings: list[Finding] = []
    seen_starts: set[int] = set()
    for _blk in run_blocks(path):
        start, block = _blk.start_line, _blk.code
        if not _ALLOWANCE.search(block):
            continue
        if not _SECOND_SAMPLE.search(block):
            continue
        m = _PROJECTION.search(block)
        if not m:
            continue
        if not _DECISION.search(block):
            # Diagnostics-only sampling is explicitly permitted.
            continue
        # Anchor the finding on the projection token, not the block start.
        line = start + block[: m.start()].count("\n")
        if line in seen_starts:
            continue
        seen_starts.add(line)
        findings.append(
            Finding(
                rule="funding-projection-is-quantised",
                severity="required",
                path=str(path),
                line=line,
                message=(
                    "a funding gate extrapolates a rate from repeated allowance samples. "
                    "The allowance is a STEP function quantised at one deposit and is flat "
                    "between steps, so a window straddling a single step reads as a drain "
                    "while the same window between steps reads flat — the verdict depends on "
                    "sampling phase, not on funding. Decide on the quantised level (whole "
                    "deposits available now) via akash-lease-core's evaluate_funding, or "
                    "keep the series for diagnostics only and do not let it gate."
                ),
            )
        )
    return findings


def check_funding_projection_is_quantised(root: Path, traits: set[str]) -> RuleResult:
    """Repo-level wrapper: walk every workflow under `root` and aggregate.

    Matches the sibling convention (check_unvalidated_default,
    check_schedule_inputs_are_empty): the conformance action globs the dir and
    this wrapper handles the no-workflows population pin, so an empty scan is
    reported as `n-a` rather than as a pass. A zero from "nothing was scanned"
    and a zero from "nothing was wrong" must never read identically.
    """
    if not root.is_dir():
        return RuleResult(
            "funding-projection-is-quantised",
            "n-a",
            note=f"{root} is not a directory — nothing to check",
        )
    files = sorted(root.glob("*.yml")) + sorted(root.glob("*.yaml"))
    if not files:
        return RuleResult(
            "funding-projection-is-quantised",
            "n-a",
            note="no .github/workflows files to scan",
        )
    findings: list[Finding] = []
    for p in files:
        findings.extend(check_workflow(p))
    return RuleResult("funding-projection-is-quantised", _cc._status(findings), findings)


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--workflows-dir", default=".github/workflows")
    _cli.add_dir_positional(ap)
    args = ap.parse_args(argv)
    _cli.resolve_dir_positional(ap, args)
    d = Path(args.workflows_dir)
    if not d.is_dir():
        print(f"::warning::{d} is not a directory — funding-projection rule did not run")
        return 0
    res = check_funding_projection_is_quantised(d, set())
    for f in res.findings or []:
        print(f"::error file={f.path},line={f.line}::{f.message}")
    return 1 if (res.findings or []) else 0


if __name__ == "__main__":
    raise SystemExit(main())
