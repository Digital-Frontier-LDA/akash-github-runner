"""Behavioral and wiring tests for lifecycle-gated merge readiness."""

from __future__ import annotations

import os
import subprocess
from copy import deepcopy
from pathlib import Path

import yaml

from akash_runner.check_standard import check as check_standard
from akash_runner.test_check_standard import valid_workflow

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = {"Akash lifecycle gate"}


def check(workflow: dict, required: set[str] = REQUIRED) -> list[str]:
    return check_standard(workflow, required_contexts=required)


def _action_run() -> str:
    action = yaml.safe_load(
        (ROOT / ".github/actions/akash-lifecycle-gate/action.yml").read_text()
    )
    steps = action["runs"]["steps"]
    assert len(steps) == 1
    return steps[0]["run"]


def _execute_gate(**values: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "DSEQ": "42", "TEARDOWN_RESULT": "success", "CLOSED": "true"}
    env.update(values)
    return subprocess.run(
        ["/bin/bash", "-c", _action_run()],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_planted_complete_lifecycle_is_merge_ready() -> None:
    assert check(valid_workflow()) == []
    assert _execute_gate().returncode == 0


def test_non_akash_lease_spender_is_inapplicable_to_merge_gate() -> None:
    workflow = {"jobs": {"diagnostic": {"runs-on": "ubuntu-latest", "steps": []}}}
    findings = check_standard(workflow, target_kind="lease-spender")
    assert not any("merge-ready" in finding for finding in findings)


def test_typed_terminal_advisory_cannot_cover_an_earlier_required_green() -> None:
    workflow = valid_workflow()
    workflow["jobs"]["tests"] = {
        "name": "Tests",
        "needs": ["work"],
        "runs-on": "ubuntu-latest",
        "steps": [{"run": "true"}],
    }
    assert "teardown" not in workflow["jobs"]["tests"]["needs"]
    findings = check(workflow, required={"Tests"})
    assert any("is not declared required on protected main" in f for f in findings)


def test_removing_terminal_edge_is_an_exact_call_site_mutation() -> None:
    workflow = valid_workflow()
    needs = workflow["jobs"]["gate"]["needs"]
    assert needs.count("teardown") == 1, "mutation target must exist exactly once"
    needs.remove("teardown")
    assert "teardown" not in needs
    assert any("must directly need pool and teardown" in f for f in check(workflow))


def test_replacing_typed_closed_wiring_with_a_literal_exposes_false_green() -> None:
    workflow = valid_workflow()
    wiring = workflow["jobs"]["gate"]["steps"][0]["with"]
    target = "${{ needs.teardown.outputs.closed }}"
    assert list(wiring.values()).count(target) == 1
    wiring["closed"] = "true"
    assert _execute_gate(CLOSED=wiring["closed"]).returncode == 0
    assert any("exact typed wiring for ['closed']" in f for f in check(workflow))


def test_bypassing_the_canonical_call_site_is_detected() -> None:
    workflow = deepcopy(valid_workflow())
    uses = workflow["jobs"]["gate"]["steps"][0]["uses"]
    target = "/akash-lifecycle-gate@"
    assert uses.count(target) == 1
    workflow["jobs"]["gate"]["steps"][0]["uses"] = uses.replace(target, "/noop@")
    assert any("terminal merge-ready gate" in f for f in check(workflow))


def test_unknown_failed_and_cancelled_proof_are_never_merge_ready() -> None:
    assert _execute_gate(CLOSED="unknown").returncode != 0
    assert _execute_gate(CLOSED="false").returncode != 0
    assert _execute_gate(TEARDOWN_RESULT="cancelled").returncode != 0


def test_empty_dseq_is_the_only_non_applicable_success() -> None:
    assert _execute_gate(DSEQ="", TEARDOWN_RESULT="skipped", CLOSED="").returncode == 0
    assert (
        _execute_gate(DSEQ="42", TEARDOWN_RESULT="skipped", CLOSED="").returncode != 0
    )
