#!/usr/bin/env python3
"""The sweep step's SHELL is extracted from the workflow and EXECUTED against a stubbed `uv`.

Not a grep over the YAML, for the reason the sibling reaper's test already gives: a
source-scan proves a string is present, it cannot prove that a dry run stays dry. The three
properties here all fail SILENTLY or DESTRUCTIVELY, and every one of them has a measured
precedent in this fleet:

  1. `execute=false` and `execute=""` must NOT close. `${EXECUTE:+--execute}` and
     `[ -n "$EXECUTE" ]` both FIRE on the string "false" that a dry-run dispatch supplies
     verbatim, and `DRY_RUN=1` parses as false under `== "true"` (Blazing-Back #1581). Three
     input shapes, and only equality against the literal "true" gets all three right.
  2. `--reap-runners` must ALWAYS be passed. With it off, classify() returns
     LEAVE-real-or-unknown for EVERY services==['runner'] deployment, so the population this
     workflow exists for is invisible regardless of --execute. MEASURED on just-akash's
     2026-08-25 12:35Z run: 22 runner leases holding 110 ACT, verdict "stale (closable): 0".
  3. A FAILED sweep must not report a clean account. The command is piped to `tee`, and
     after a pipe `$?` is tee's status — 0 even when the sweep died. An unswept account
     would then read exactly like an empty one.
"""

from __future__ import annotations

import subprocess
import textwrap
from pathlib import Path

import pytest
import yaml

WF = Path(__file__).resolve().parents[1] / ".github/workflows/reusable-akash-escrow-reaper.yml"


def _sweep_script() -> str:
    doc = yaml.safe_load(WF.read_text())
    job = doc["jobs"]["reap"]
    step = next(s for s in job["steps"] if s.get("id") == "sweep")
    return step["run"]


def _sweep_executable() -> str:
    """The sweep step with COMMENT LINES STRIPPED.

    ⛔ WHY THIS EXISTS, MEASURED ON THIS FILE. `test_pipefail_is_set_in_the_sweep` first
    asserted against the raw block and passed under BOTH mutations that should have broken
    it — because the comment explaining the guard quotes the very strings the guard looks
    for. The assertion was reading its own prose. A rule keyed to a quotable string
    retargets onto the paragraph describing it, and then it can never fail.
    """
    return "\n".join(
        line for line in _sweep_script().splitlines() if not line.lstrip().startswith("#")
    )


def _run(
    tmp_path: Path,
    *,
    execute: str,
    sweep_rc: int = 0,
    closed_line: str = "closed=20 failed=0",
    prefix: str = "just-akash-",
):
    """Execute the real step script with a fake `uv` that records its argv."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "uv").write_text(
        textwrap.dedent(f"""\
        #!/bin/bash
        printf '%s\\n' "$*" >> "{tmp_path}/argv.txt"
        echo "stale (closable): 20"
        echo "{closed_line}"
        exit {sweep_rc}
        """)
    )
    (bindir / "uv").chmod(0o755)
    env = {
        "PATH": f"{bindir}:/usr/bin:/bin",
        "EXECUTE": execute,
        "PLACEMENT_PREFIX": prefix,
        "AKASH_API_KEY": "stub",
        "GITHUB_OUTPUT": str(tmp_path / "out.txt"),
        "GITHUB_STEP_SUMMARY": str(tmp_path / "summary.txt"),
    }
    proc = subprocess.run(["bash", "-c", _sweep_script()], env=env, capture_output=True, text=True)
    argv = (tmp_path / "argv.txt").read_text() if (tmp_path / "argv.txt").exists() else ""
    out = (tmp_path / "out.txt").read_text() if (tmp_path / "out.txt").exists() else ""
    return proc, argv, out


# ── 1. a dry run must stay dry, across all three input shapes ────────────────────────────

@pytest.mark.parametrize("execute", ["false", "", "False", "0", "1", "TRUE"])
def test_only_the_literal_true_closes(tmp_path, execute):
    """Everything that is not exactly "true" must report, never close.

    "0"/"1" are the DRY_RUN=1 shape; "" is what a SCHEDULED caller supplies (no inputs);
    "False"/"TRUE" are case variants a hand-written dispatch produces.
    """
    _, argv, _ = _run(tmp_path, execute=execute)
    assert "--execute" not in argv, f"EXECUTE={execute!r} passed --execute — a dry run closed deployments"


def test_the_literal_true_does_close(tmp_path):
    """Anti-vacuity for the test above: if nothing ever closed, every assertion there would
    pass while the workflow was inert."""
    _, argv, _ = _run(tmp_path, execute="true")
    assert "--execute" in argv, "EXECUTE=true did NOT pass --execute — the reaper cannot close"


# ── 2. the flag without which this cannot reach its own population ───────────────────────

@pytest.mark.parametrize("execute", ["true", "false", ""])
def test_reap_runners_is_unconditional(tmp_path, execute):
    _, argv, _ = _run(tmp_path, execute=execute)
    assert "--reap-runners" in argv, (
        f"EXECUTE={execute!r} omitted --reap-runners; every runner lease would classify as "
        "LEAVE-real-or-unknown and the sweep would report 0 closable against a real leak"
    )


# ── 3. a failed sweep is an UNSWEPT account, not a clean one ─────────────────────────────

def test_a_failing_sweep_fails_the_step(tmp_path):
    proc, _, _ = _run(tmp_path, execute="true", sweep_rc=3)
    assert proc.returncode != 0, (
        "the sweep exited 3 and the step succeeded — `$?` after a pipe is tee's status, so an "
        "unswept account reports exactly like an empty one"
    )


def test_a_successful_sweep_passes(tmp_path):
    """Anti-vacuity partner: a step that always failed would satisfy the test above."""
    proc, _, _ = _run(tmp_path, execute="true")
    assert proc.returncode == 0, f"a clean sweep failed the step: {proc.stderr[:300]}"


# ── the reported count must come from the sweep, not be assumed ──────────────────────────

def test_closed_count_is_read_from_the_sweep_output(tmp_path):
    _, _, out = _run(tmp_path, execute="true", closed_line="closed=7 failed=0")
    assert "closed=7" in out, f"the step output did not carry the sweep's own count: {out!r}"


def test_a_sweep_that_closed_nothing_reports_zero_not_blank(tmp_path):
    _, _, out = _run(tmp_path, execute="false", closed_line="(no closes on a report run)")
    assert "closed=0" in out, f"a report-only run must emit closed=0, got {out!r}"


# ── the workflow's own shape ─────────────────────────────────────────────────────────────

def test_execute_defaults_to_report():
    doc = yaml.safe_load(WF.read_text())
    # YAML 1.1 parses a bare `on:` as boolean True — the trap check_dereg_backstop notes.
    call = doc[True]["workflow_call"] if True in doc else doc["on"]["workflow_call"]
    assert call["inputs"]["execute"]["default"] is False


def test_just_akash_ref_is_required_with_no_default():
    """A floating ref resolves at INSTALL time, so the closing logic can change under a
    caller that changed nothing."""
    doc = yaml.safe_load(WF.read_text())
    call = doc[True]["workflow_call"] if True in doc else doc["on"]["workflow_call"]
    ref = call["inputs"]["just-akash-ref"]
    assert ref["required"] is True
    assert "default" not in ref, "a default ref would let the closing logic drift silently"


def test_the_workflow_declares_no_schedule():
    """`check_reaper_schedule.py` scopes its cron rule to workflows that are NOT
    workflow_call-invocable, because such a workflow runs when its caller runs. The CALLER
    owns the schedule."""
    doc = yaml.safe_load(WF.read_text())
    triggers = doc[True] if True in doc else doc["on"]
    assert "schedule" not in triggers
    assert "workflow_call" in triggers


def test_pipefail_is_set_in_the_sweep():
    """The other half of the rc guard.

    ⚠ Mutating `rc=${PIPESTATUS[0]}` to `rc=$?` left every behavioural test green, because
    `pipefail` already makes `$?` correct. That makes PIPESTATUS redundant TODAY and load
    bearing the moment `pipefail` goes — so the property worth pinning is that BOTH are
    present, not either one. A test that could not tell the two apart is how a redundant
    guard gets deleted as dead weight and takes the real one with it.
    """
    script = _sweep_executable()
    assert "pipefail" in script, "pipefail dropped — `$?` after the pipe becomes tee's 0"
    assert "PIPESTATUS[0]" in script, "PIPESTATUS dropped — the rc guard now rests on pipefail alone"


# ── the ownership prefix must reach the mechanism, and blank must be refused ──────────

@pytest.mark.parametrize("execute", ["true", "false", ""])
def test_the_placement_prefix_is_passed_through(tmp_path, execute):
    """⛔ If it does not reach the mechanism, the sweep runs under the mechanism's OWN
    default (`just-akash-`) and a consumer stamping something else matches NOTHING — 0
    closable forever, while an adoption audit reads green. An inert reaper is worse than an
    absent one."""
    _, argv, _ = _run(tmp_path, execute=execute, prefix="dfci-infra-")
    assert "--placement-prefix dfci-infra-" in argv, (
        f"EXECUTE={execute!r}: the prefix never reached the sweep — argv was {argv!r}"
    )


@pytest.mark.parametrize("blank", ["", "   "])
def test_a_blank_prefix_fails_the_step(tmp_path, blank):
    """`"".startswith(x)` is True for every string, so a blank prefix claims every
    deployment on the account — including other repos'."""
    proc, argv, _ = _run(tmp_path, execute="true", prefix=blank)
    assert proc.returncode != 0, "a blank placement-prefix was accepted"
    assert "--placement-prefix" not in argv, "the sweep ran despite a blank prefix"


def test_a_present_prefix_does_not_fail_the_step(tmp_path):
    """Anti-vacuity partner: a step that always failed would satisfy the test above."""
    proc, _, _ = _run(tmp_path, execute="true", prefix="dfci-infra-")
    assert proc.returncode == 0, proc.stderr[:300]


def test_the_prefix_input_is_required_with_no_default():
    """A default would silently hand every consumer the mechanism's own prefix — which is
    correct for exactly one repo and wrong, invisibly, for all the others."""
    doc = yaml.safe_load(WF.read_text())
    call = doc[True]["workflow_call"] if True in doc else doc["on"]["workflow_call"]
    spec = call["inputs"]["placement-prefix"]
    assert spec["required"] is True
    assert "default" not in spec, "a default prefix makes an inert adoption the easy path"
