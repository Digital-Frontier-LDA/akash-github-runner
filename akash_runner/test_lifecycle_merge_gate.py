"""Effect tests for lifecycle-gated merge readiness."""

from __future__ import annotations

import os
import subprocess
from copy import deepcopy

from akash_runner.check_standard import check
from akash_runner.test_check_standard import valid_workflow


def _gate_run(workflow: dict) -> str:
    return workflow["jobs"]["gate"]["steps"][0]["run"]


def _execute_gate(workflow: dict, **values: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "DSEQ": "42", "TEARDOWN_RESULT": "success", "CLOSED": "true"}
    env.update(values)
    return subprocess.run(
        ["/bin/bash", "-c", _gate_run(workflow)],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_planted_complete_lifecycle_is_merge_ready() -> None:
    workflow = valid_workflow()
    assert check(workflow) == []
    assert _execute_gate(workflow).returncode == 0


def test_non_akash_lease_spender_is_inapplicable_to_merge_gate() -> None:
    workflow = {"jobs": {"diagnostic": {"runs-on": "ubuntu-latest", "steps": []}}}
    findings = check(workflow, target_kind="lease-spender")
    assert findings == [
        "declared --target-kind lease-spender but no Akash lease lifecycle found "
        "(no close call, no dseq, no deployment delete) — this file is not the third "
        "shape and the declaration suppresses a real finding"
    ]
    assert not any("merge-ready" in finding for finding in findings)


def test_removing_terminal_edge_exposes_premature_green_and_is_detected() -> None:
    workflow = valid_workflow()
    needs = workflow["jobs"]["gate"]["needs"]
    assert needs.count("teardown") == 1, "mutation target must exist exactly once"
    needs.remove("teardown")
    assert "teardown" not in needs
    findings = check(workflow)
    assert any(
        "must directly need pool and teardown" in finding for finding in findings
    )


def test_inverting_real_result_wiring_is_an_effect_mutation() -> None:
    workflow = valid_workflow()
    old = '"success"'
    new = '"failure"'
    run = _gate_run(workflow)
    assert run.count(old) == 1, "mutation target must exist exactly once"
    workflow["jobs"]["gate"]["steps"][0]["run"] = run.replace(old, new)
    assert _execute_gate(workflow, TEARDOWN_RESULT="failure").returncode == 0
    findings = check(workflow)
    assert any(
        "must fail closed unless teardown result" in finding for finding in findings
    )


def test_unknown_and_failed_proof_are_never_merge_ready() -> None:
    workflow = valid_workflow()
    assert _execute_gate(workflow, CLOSED="unknown").returncode != 0
    assert _execute_gate(workflow, CLOSED="false").returncode != 0
    assert _execute_gate(workflow, TEARDOWN_RESULT="cancelled").returncode != 0


def test_empty_dseq_is_the_only_non_applicable_success() -> None:
    workflow = deepcopy(valid_workflow())
    assert (
        _execute_gate(
            workflow, DSEQ="", TEARDOWN_RESULT="skipped", CLOSED=""
        ).returncode
        == 0
    )
    assert (
        _execute_gate(
            workflow, DSEQ="42", TEARDOWN_RESULT="skipped", CLOSED=""
        ).returncode
        != 0
    )
