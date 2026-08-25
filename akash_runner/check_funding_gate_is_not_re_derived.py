#!/usr/bin/env python3
"""A funding decision must come from the primitive, not be re-derived per repo.

⛔ THE DEFECT, MEASURED. `akash-runner.yml` decides "can this account fund a create?"
in inline shell. On 2026-08-24 that local derivation carried four independent errors at
once, each of which the shared primitive exists to prevent:

  1. IT FIT A LINE TO A STEP FUNCTION. It sampled the allowance twice, 60s apart, and
     projected the delta forward 300s. The allowance does not drift — it moves in whole
     5.00 ACT deposits. MEASURED over 40 samples at 20s: 30 of 39 intervals FLAT, and
     every non-zero delta an integer multiple of 5.00 (-5, -5, -5, -5, +5, +5, +5, +10,
     +14.97 — the 0.03 being rent consumed). From that step rate, P(a step lands inside
     the 60s window) = 54%, and ~24% of prechecks see a FALLING step and refuse. Two
     samples cannot distinguish a step from a slope, so the gate refuses hardest exactly
     when the queue is busy — when provisioning matters most.

  2. IT READ THE WRONG QUANTITY. Console `deploy_credit` does not gate a create; the
     on-chain DepositAuthorization does. A run once read deploy_credit=$3.73 and passed
     while creates were returning HTTP 402, and a day went into investigating provider
     capacity for what was an allowance problem.

  3. IT READ THE SINGULAR KEY. `spend_limit` is `uakt:0` on a fully-funded account;
     `spend_limits` (PLURAL) holds the `uact` figure. A parser reading the singular
     reports 0.00 ACT on three funded accounts and looks like a catastrophic drain.

  4. IT DISAGREED WITH ITSELF ON THE FLOOR. Three readers, three live defaults —
     5_000_000 (measured), 6_000_000 (the estimate it replaced), 12_000_000 (2x the
     estimate, for retries) — with `AKASH_MIN_DEPLOY_CREDIT_UACT` read in three places
     and set in none.

⇒ None of these is a bug in one repo. They are what happens when every consumer derives
the same decision from raw numbers. `akash-lease-core` v0.8.0 answers it once:
`evaluate_funding(samples, policy) -> FundingDecision`, quantised, naming WHICH quantity
it read, returning THREE outcomes, and selecting max(SLOT) never the sum.

⚠ SCOPE — ONLY WORKFLOWS THAT ACTUALLY DECIDE. Printing a balance is not gating on one.
A workflow is in scope when a `run:` block both READS an allowance-ish quantity AND uses
it to decide (a comparison, a threshold, an exit). Reporting is out of scope: a diagnostic
that prints `deploy_credit` for a human is not a funding gate and demanding the primitive
of it would be noise.

⛔⛔ AND IT MATCHES CODE, NOT PROSE. Every `run:` block is comment-stripped before any
pattern is applied, and only `run:` blocks are read — never the raw file. This is not
fastidiousness: on 2026-08-24 a sibling guard in Blazing-Back flagged a DOCSTRING as an
unclassified DELETE call site because it scanned raw text with a keyword window, and the
"fix" it demanded was to register a comment in a registry of things that actually close
deployments. A rule that cannot tell code from a sentence about code will be satisfied by
editing the sentence.

★ THE EXEMPTION IS THE PRIMITIVE ITSELF. There is no allow-list here. A workflow passes by
routing through `akash-lease-core` — by name in the same `run:` block that decides. That is
checkable, and it expires by itself: rip the primitive out and the rule fails again.
"""

from __future__ import annotations

import argparse
import importlib.util
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    print("PyYAML is required: pip install pyyaml", file=sys.stderr)
    raise SystemExit(2) from None

# ⛔ THE CORPUS IS SHARED AND NEUTRAL (#171). Both funding rules import the SAME
# `run:`-block extractor; neither owns the other's corpus. Loaded by path rather than by
# name because the conformance harness loads rules via spec_from_file_location, which does
# not put the rule's directory on sys.path.
_WC_SPEC = importlib.util.spec_from_file_location(
    "akash_runner_workflow_corpus",
    Path(__file__).resolve().parent / "workflow_corpus.py",
)
assert _WC_SPEC and _WC_SPEC.loader
_wc = importlib.util.module_from_spec(_WC_SPEC)
sys.modules[_WC_SPEC.name] = _wc
_WC_SPEC.loader.exec_module(_wc)

run_blocks = _wc.run_blocks
strip_comments = _wc.strip_comments

#: How a consumer says "I used the shared decision". Any of these in the deciding block.
PRIMITIVE_MARKERS = ("akash-lease-core", "akash_lease_core", "evaluate_funding")

#: Reading an allowance-ish quantity at all.
_READS = (
    re.compile(r"spend_limits?\b"),
    re.compile(r"deploy_credit\b"),
    # ⚠ NO leading \b: `_` is a word character, so `\ballowance\b` misses the common
    # `read_allowance` / `get_allowance` spellings. My own known-negatives caught this.
    re.compile(r"allowance", re.I),
    re.compile(r"locked_in_escrow_uact\b"),
)

#: Using that reading to DECIDE. A comparison, a threshold, or an exit on it.
_DECIDES = (
    re.compile(r"\bMIN_UACT\b"),
    re.compile(r"-lt\b|-le\b|-gt\b|-ge\b"),
    re.compile(r"\bexit\s+1\b"),
    re.compile(r"::error"),
)

#: Named anti-patterns. Each is a defect that was MEASURED, not imagined.
ANTIPATTERNS: dict[str, tuple[re.Pattern[str], str]] = {
    "extrapolates-a-step-function": (
        # ⚠ WORD BOUNDARIES ARE NOT COSMETIC. Bare `rate` matched "delibeRATEly" inside an
        # echo string when this was run against the real akash-runner.yml — a correct
        # verdict that would have been reached by a wrong route, and a false accusation on
        # any block whose only "rate" is "generate"/"accurate". The decisive evidence is
        # arithmetic that scales a delta by a horizon, so prefer identifier-shaped tokens.
        re.compile(
            r"(projected?_[a-z]|projection|extrapolat|\bslope\b|per[_-]second"
            r"|\brate\b|delta\s*\*|\*\s*[A-Z_]*HORIZON|/\s*[A-Z_]*GAP)",
            re.I,
        ),
        "projects a rate from samples. The allowance moves in whole deposits: 30/39 "
        "intervals flat, every delta an integer multiple of 5.00 ACT. Two samples cannot "
        "tell a step from a slope; ~24% of prechecks refuse on the artefact.",
    ),
    "gates-on-console-deploy-credit": (
        re.compile(r"deploy_credit"),
        "gates on Console deploy_credit, which does not gate a create. The on-chain "
        "DepositAuthorization does. Reading one while meaning the other cost a day of "
        "provider-capacity investigation for an allowance problem.",
    ),
    "reads-the-singular-spend-limit": (
        re.compile(r"spend_limit\b(?!s)"),
        "reads the SINGULAR spend_limit, which is uakt:0 on a funded account. The uact "
        "figure is under spend_limits (PLURAL).",
    ),
    "sums-slots-instead-of-max": (
        re.compile(r"\b(sum|total)\b.*\bslot", re.I),
        "aggregates slots. A create draws its deposit from ONE account, so the gate must "
        "read max(SLOT); a sum authorises a create no single slot can fund.",
    ),
}


def audit(path: Path) -> list[str]:
    problems: list[str] = []
    for blk in run_blocks(path):
        job_id, code = blk.job_id, blk.code
        if not any(p.search(code) for p in _READS):
            continue
        if not any(p.search(code) for p in _DECIDES):
            continue  # reads but does not decide — reporting, not gating
        if any(m in code for m in PRIMITIVE_MARKERS):
            continue  # routed through the primitive
        hits = [f"{name}: {why}" for name, (pat, why) in ANTIPATTERNS.items() if pat.search(code)]
        detail = "; ".join(hits) if hits else "no named anti-pattern, but the decision is local"
        problems.append(
            f"{path.name}: job '{job_id}' DECIDES funding from raw numbers without "
            f"akash-lease-core. {detail}"
        )
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("targets", nargs="+", help="workflow file(s) or a workflows directory")
    args = ap.parse_args(argv)

    files: list[Path] = []
    for t in args.targets:
        p = Path(t)
        if p.is_dir():
            files.extend(sorted(q for q in p.glob("*.y*ml")))
        elif p.exists():
            files.append(p)
    if not files:
        print("no workflow files found — the scan is broken, not the repo", file=sys.stderr)
        return 2

    problems: list[str] = []
    for f in files:
        try:
            problems.extend(audit(f))
        except yaml.YAMLError as e:
            print(f"{f.name}: unparseable YAML ({e}) — NOT a pass", file=sys.stderr)
            return 2

    if problems:
        print("Funding decisions re-derived locally instead of via akash-lease-core:")
        for p in problems:
            print(f"  - {p}")
        print(
            "\n⇒ Route the decision through `evaluate_funding(samples, policy)`. It is "
            "quantised, it names WHICH quantity it read, it returns THREE outcomes "
            "(UNDETERMINED is not a pass), and it selects max(SLOT) never the sum."
        )
        return 1
    print(f"funding-gate: OK — {len(files)} workflow(s), no local re-derivation")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
