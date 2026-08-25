"""A category the checker judges but no consumer can select is not a feature.

⛔ MEASURED 2026-08-25. `check_standard.py` has judged THREE shapes since #11 —
consumer, pool, and lease-spender — and `test_lease_spender_target_kind.py` proves the
third one works. It could not be reached. The composite action invoked the checker with
no `--target-kind` at all, so every caller got `auto`, and `auto` errs toward consumer
mode. A repo that spends on Akash leases through its own provisioner therefore failed
with "no canonical just-akash runner-pool reusable job found" on every run, forever,
against a contract it was never in scope for.

★ THE RULE WAS RIGHT, THE TEST WAS RIGHT, AND THE WIRING WAS THE WHOLE DEFECT. That is
this repo's own recurring shape: a test proves the rule WORKS; only the call site proves
it RUNS. `test_every_rule_has_a_call_site.py` pins that a rule is INVOKED — nothing
pinned that its OPTIONS are reachable.

Measured cost before the fix, on the two repos that hit it (Blazing-Back #1628,
df-cicd): the only escape from the permanent red was to omit `workflow` entirely, which
also drops the workflow-scoped rules that DO apply — `check_teardown_can_identify`
passes non-vacuously on Blazing-Back (9 run-steps examined) and was being discarded to
dodge an inapplicable finding.

⇒ These tests pin the CHAIN, not the sentence: reusable input → action input → env →
argv. Any link dropped fails here.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
ACTION = ROOT / ".github/actions/akash-runner-conformance/action.yml"
REUSABLE = ROOT / ".github/workflows/reusable-akash-runner-conformance.yml"


def _action() -> dict:
    return yaml.safe_load(ACTION.read_text())


def _reusable() -> dict:
    return yaml.safe_load(REUSABLE.read_text())


def _kind_guard() -> str:
    """The contiguous KIND_ARGS block, from its initialiser to its closing `fi`.

    ⚠ Extracted as a SPAN, not by filtering lines that "look relevant". A predicate
    filter over the whole script collected every `fi` in the action — the extracted
    snippet was unbalanced shell that failed to parse, which reads exactly like the
    guard being broken. The instrument must not manufacture the failure it reports.
    """
    lines = _run_block().splitlines()
    start = next(
        i for i, ln in enumerate(lines) if ln.strip().startswith("KIND_ARGS=()")
    )
    end = next(i for i in range(start, len(lines)) if lines[i].strip() == "fi")
    return "\n".join(lines[start : end + 1])


def _run_block() -> str:
    """The action's single composite `run:` script."""
    steps = _action()["runs"]["steps"]
    blocks = [s["run"] for s in steps if isinstance(s, dict) and s.get("run")]
    assert blocks, "the action has no run block — the shape changed, re-read this test"
    return "\n".join(blocks)


def test_the_checker_still_offers_the_third_shape():
    """A control. If check_standard drops `lease-spender`, every other test here is
    pinning plumbing to a destination that no longer exists — and would still pass."""
    out = subprocess.run(
        ["python3", str(ROOT / "akash_runner/check_standard.py"), "--help"],
        capture_output=True,
        text=True,
    ).stdout
    assert "lease-spender" in out, "check_standard no longer offers lease-spender"


def test_the_reusable_exposes_target_kind():
    inputs = _reusable()[True]["workflow_call"]["inputs"]
    assert "target-kind" in inputs, "consumers cannot select a target kind"
    # Optional: every existing caller omits it and must keep working unchanged.
    assert inputs["target-kind"].get("required") is not True
    assert inputs["target-kind"].get("default") == ""


def test_the_reusable_forwards_it_to_the_action():
    """The input existing is not the input arriving."""
    steps = [
        st for job in _reusable()["jobs"].values() for st in (job.get("steps") or [])
    ]
    with_blocks = [
        st.get("with") or {}
        for st in steps
        if "akash-runner-conformance" in str(st.get("uses", ""))
    ]
    assert with_blocks, "the reusable no longer invokes the composite action"
    forwarded = any(
        "inputs.target-kind" in str(w.get("target-kind", "")) for w in with_blocks
    )
    assert forwarded, "the reusable declares target-kind and drops it on the floor"


def test_the_action_exposes_it_and_puts_it_in_the_environment():
    assert "target-kind" in _action()["inputs"]
    steps = _action()["runs"]["steps"]
    envs = [s.get("env") or {} for s in steps if isinstance(s, dict)]
    assert any("inputs.target-kind" in str(e.get("TARGET_KIND", "")) for e in envs), (
        "TARGET_KIND never reaches the script's environment"
    )


def test_the_script_passes_it_to_check_standard_and_only_to_check_standard():
    run = _run_block()
    assert "TARGET_KIND" in run, "the script ignores the environment variable"
    line = [
        ln for ln in run.splitlines() if "check_standard.py" in ln and "python3" in ln
    ]
    assert len(line) == 1, f"expected ONE check_standard invocation, found {len(line)}"
    assert "KIND_ARGS" in line[0], "check_standard is still invoked without the kind"


def test_an_unset_target_kind_contributes_no_argument():
    """⛔ THE REGRESSION THAT WOULD BREAK EVERY EXISTING CALLER.

    `--target-kind ""` is not the same as omitting the flag: argparse rejects the empty
    string against its `choices`, so interpolating the variable directly would fail the
    conformance job on every consumer that leaves this unset — which today is all of
    them. Asserted by RUNNING the guard, not by reading it.
    """
    guard = _kind_guard()
    script = (
        f'set -euo pipefail\nTARGET_KIND=""\n{guard}\necho "COUNT=${{#KIND_ARGS[@]}}"'
    )
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
    assert r.returncode == 0, f"the guard exits non-zero when unset: {r.stderr}"
    assert "COUNT=0" in r.stdout, f"an unset kind still contributes argv: {r.stdout}"


def test_a_set_target_kind_contributes_exactly_the_flag_and_its_value():
    guard = _kind_guard()
    script = (
        f'set -euo pipefail\nTARGET_KIND="lease-spender"\n{guard}\n'
        'printf "%s\\n" "${KIND_ARGS[@]}"'
    )
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.split() == ["--target-kind", "lease-spender"], r.stdout
