"""Offline effects of the real caller/callee job graphs, plus the adoption entry point.

These model scheduling and close effects, not GitHub's expression engine or Akash RPC.
Fixtures record their source commits; provisioning and reusable calls never execute.
"""

from copy import deepcopy
import ast
import os
from pathlib import Path
import re
import subprocess
import sys

import pytest
import yaml

from akash_runner.check_pool_owns_teardown import check as check_handoff
from akash_runner.check_standard import check

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).with_name("fixtures") / "pool_handoff"


def graph(name):
    return yaml.safe_load((FIXTURES / f"{name}.yml").read_text())


def condition_runs(expression, results):
    """Evaluate only the fixture expression vocabulary, independently of the checker."""
    text = str(expression).removeprefix("${{").removesuffix("}}").strip()
    text = re.sub(r"needs\.([\w-]+)\.result", lambda m: repr(results[m[1]]), text)
    text = text.replace("always()", "True").replace("&&", " and ").replace("||", " or ")
    tree = ast.parse(text, mode="eval")
    allowed = (
        ast.Expression,
        ast.BoolOp,
        ast.And,
        ast.Or,
        ast.Compare,
        ast.Eq,
        ast.NotEq,
        ast.Constant,
    )
    assert all(isinstance(node, allowed) for node in ast.walk(tree))
    return eval(compile(tree, "<fixture condition>", "eval"), {"__builtins__": {}})


def lifetime(callee, caller, provision="success", work="success"):
    """Schedule teardown as early as its actual needs allow; work requires a live lease."""
    alive = True  # Provisioning has already created the test lease, even on failure.
    events = ["lease-created"]
    rollback = callee["jobs"]["teardown"]
    if condition_runs(rollback["if"], {"pool": provision}):
        alive = False
        events.append("rollback-close")
    events.append("callee-finished")
    done = {"pool"}
    teardown = caller["jobs"]["teardown"]
    needs = teardown["needs"]
    if set(needs) <= done and condition_runs(teardown["if"], {"pool": provision}):
        alive = False
        events.append("caller-close")
    if provision == "success":
        assert alive, events  # Consumers cannot run until the entire callee finishes.
        events.append("consumer-started")
        events.append("consumer-" + work)
    done.add("work")
    if "caller-close" not in events and set(needs) <= done:
        if condition_runs(teardown["if"], {"pool": provision, "work": work}):
            alive = False
            events.append("caller-close")
    assert not alive, events
    return events


@pytest.mark.parametrize("work", ["success", "failure", "cancelled"])
def test_successful_handoff_survives_until_consumers_finish(work):
    callee, caller = graph("callee"), graph("caller")
    assert check(callee, "pool") == []
    assert check(caller, "consumer") == []
    events = lifetime(callee, caller, work=work)
    assert "rollback-close" not in events
    assert events.index("consumer-" + work) < events.index("caller-close")


@pytest.mark.parametrize("provision", ["failure", "cancelled"])
def test_failed_or_cancelled_provisioning_rolls_back_before_return(provision):
    events = lifetime(graph("callee"), graph("caller"), provision=provision)
    assert events.index("rollback-close") < events.index("callee-finished")
    assert "consumer-started" not in events


def mutate_internal_close(document):
    before = deepcopy(document)
    document["jobs"]["teardown"]["if"] = "always()"
    assert document != before
    before["jobs"]["teardown"]["if"] = "always()"
    assert document == before  # Exactly the predicate changed.


def mutate_missing_consumer(document):
    before = deepcopy(document)
    assert document["jobs"]["teardown"]["needs"].count("work") == 1
    document["jobs"]["teardown"]["needs"].remove("work")
    before["jobs"]["teardown"]["needs"].remove("work")
    assert document == before  # Exactly one dependency changed.


def test_unconditional_internal_close_changes_lifetime_and_both_checker_verdicts():
    callee, caller = graph("callee"), graph("caller")
    mutate_internal_close(callee)
    with pytest.raises(AssertionError, match="rollback-close"):
        lifetime(callee, caller)
    assert check_handoff(callee)
    assert any("successful handoff" in f for f in check(callee, "pool"))


def test_missing_consumer_dependency_changes_lifetime_and_verdict():
    callee, caller = graph("callee"), graph("caller")
    mutate_missing_consumer(caller)
    with pytest.raises(AssertionError, match="caller-close"):
        lifetime(callee, caller)
    assert any("missing ['work']" in f for f in check(caller, "consumer"))


@pytest.mark.parametrize(
    "bad",
    [
        "always() && needs.pool.result == 'success'",
        "always() && needs.pool.result == 'failure'",
        "always() && needs.other.result != 'success'",
        "always() && needs.pool.result != 'success' || true",
        "failure()",
    ],
)
def test_internal_rollback_cannot_close_success_or_skip_cancellation(bad):
    callee = graph("callee")
    callee["jobs"]["teardown"]["if"] = bad
    assert check_handoff(callee)
    assert check(callee, "pool")


def test_failure_only_caller_cleanup_is_still_rejected():
    caller = graph("caller")
    caller["jobs"]["teardown"]["if"] = "always() && needs.pool.result != 'success'"
    assert any(
        "must not be gated on its provisioner's result" in f for f in check(caller)
    )


def test_rollback_exception_requires_identity_wiring_and_producer_dependency():
    for field in ("with", "needs"):
        callee = graph("callee")
        del callee["jobs"]["teardown"][field]
        findings = check(callee, "pool")
        assert any(
            "must not be gated on its provisioner's result" in f for f in findings
        )


@pytest.mark.parametrize(
    "name,mutation,want",
    [
        ("callee", None, 0),
        ("callee", mutate_internal_close, 1),
        ("caller", None, 0),
        ("caller", mutate_missing_consumer, 1),
    ],
)
def test_actual_composite_entry_point_enforces_handoff(tmp_path, name, mutation, want):
    document = graph(name)
    if mutation:
        mutation(document)
    workflow = tmp_path / "workflow.yml"
    workflow.write_text(yaml.safe_dump(document))
    action_dir = ROOT / ".github/actions/akash-runner-conformance"
    action = yaml.safe_load((action_dir / "action.yml").read_text())
    steps = action["runs"]["steps"]
    assert len(steps) == 1
    script = steps[0]["run"].replace("${{ inputs.not-judgeable }}", "error")
    result = subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        timeout=30,
        env={
            **os.environ,
            "PATH": str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"],
            "GITHUB_ACTION_PATH": str(action_dir),
            "WORKFLOW": str(workflow),
            "WORKFLOWS_DIR": "",
            "TARGET_KIND": "pool" if name == "callee" else "consumer",
        },
    )
    assert result.returncode == want, result.stdout + result.stderr
    if mutation:
        assert (
            "successful handoff" in result.stdout
            if name == "callee"
            else "missing ['work']" in result.stdout
        )


def test_rollback_is_bound_to_producer_identity_not_a_job_name_exception():
    callee = graph("callee")
    # Rename all producer references together, preserving actual wiring.
    serialized = yaml.safe_dump(callee)
    assert serialized.count("jobs.pool.outputs.dseq") == 1
    serialized = serialized.replace("jobs.pool.outputs", "jobs.provisioned.outputs")
    serialized = serialized.replace("needs.pool.", "needs.provisioned.")
    renamed = yaml.safe_load(serialized)
    renamed["jobs"]["provisioned"] = renamed["jobs"].pop("pool")
    renamed["jobs"]["return-resource"] = renamed["jobs"].pop("teardown")
    renamed["jobs"]["return-resource"]["needs"] = ["provisioned"]
    assert check(renamed, "pool") == []
    renamed["jobs"]["return-resource"]["if"] = "always()"
    assert any("successful handoff" in f for f in check(renamed, "pool"))


@pytest.mark.parametrize(
    "value",
    [
        "${{ jobs.missing.outputs.dseq }}",
        '${{ jobs.pool.outputs.dseq || "invented" }}',
        "",
    ],
)
def test_unresolved_handoff_output_is_not_an_exemption(value):
    callee = graph("callee")
    callee["on"]["workflow_call"]["outputs"]["dseq"]["value"] = value
    assert check(callee, "pool")


def test_expression_wrappers_and_whitespace_do_not_change_handoff_contract():
    callee = graph("callee")
    callee["jobs"]["teardown"]["if"] = (
        "${{ always() && needs.pool.result != 'success' }}"
    )
    callee["jobs"]["teardown"]["with"]["dseq"] = "${{needs.pool.outputs.dseq}}"
    assert check(callee, "pool") == []
