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
import tempfile

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


def resolve_output(expression, contexts):
    """Resolve a direct fixture output reference; absent links deliver an empty value."""
    match = re.fullmatch(
        r"\s*\$\{\{\s*(steps|jobs|needs)\.([\w-]+)\.outputs\.([\w-]+)\s*\}\}\s*",
        str(expression or ""),
    )
    if not match:
        return ""
    return contexts.get(match[1], {}).get(match[2], {}).get(match[3], "")


def produced_outputs(callee):
    # Execute only the committed offline output-emission stub, never provisioning or RPC.
    outputs = {}
    with tempfile.TemporaryDirectory() as temporary:
        for step in callee["jobs"]["pool"]["steps"]:
            output_file = Path(temporary) / "outputs"
            output_file.write_text("")
            subprocess.run(
                ["bash", "-c", step["run"]],
                check=True,
                capture_output=True,
                env={**os.environ, "GITHUB_OUTPUT": str(output_file)},
                timeout=5,
            )
            outputs[step["id"]] = dict(
                line.split("=", 1) for line in output_file.read_text().splitlines()
            )
    return {
        name: resolve_output(expression, {"steps": outputs})
        for name, expression in callee["jobs"]["pool"].get("outputs", {}).items()
    }


def lifetime(callee, caller, provision="success", work="success"):
    """Execute graph wiring against stubbed output producers and identified close operations."""
    alive = True  # Provisioning created lease 1 before its modeled final result.
    events = ["lease-created"]
    producer = produced_outputs(callee)
    # These are the actual fixture targets whose reusable calls our close stub implements.
    # A renamed noop.yml is a different operation and must have no close effect.
    close_targets = {
        graph(name)["jobs"]["teardown"]["uses"] for name in ("callee", "caller")
    }

    def close(job, contexts, label):
        nonlocal alive
        identity = resolve_output(job.get("with", {}).get("dseq"), contexts)
        if job.get("uses") in close_targets and identity == "1":
            alive = False
            events.append(label + "-close")
        else:
            events.append(label + "-no-close")

    rollback = callee["jobs"]["teardown"]
    if condition_runs(rollback["if"], {"pool": provision}):
        close(rollback, {"needs": {"pool": producer}}, "rollback")
    events.append("callee-finished")
    published = {
        name: resolve_output(spec["value"], {"jobs": {"pool": producer}})
        for name, spec in callee["on"]["workflow_call"]["outputs"].items()
    }
    # Failed/cancelled reusable calls do not promise outputs to caller jobs.
    caller_context = {"needs": {"pool": published if provision == "success" else {}}}
    done = {"pool"}
    teardown = caller["jobs"]["teardown"]
    needs = teardown["needs"]
    teardown_ran = False
    if set(needs) <= done and condition_runs(teardown["if"], {"pool": provision}):
        close(teardown, caller_context, "caller")
        teardown_ran = True
    if provision == "success":
        assert alive, events
        events.append("consumer-started")
        events.append("consumer-" + work)
    done.add("work")
    if not teardown_ran and set(needs) <= done:
        if condition_runs(teardown["if"], {"pool": provision, "work": work}):
            close(teardown, caller_context, "caller")
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


def mutate_missing_producer_output(document):
    before = deepcopy(document)
    assert "dseq" in document["jobs"]["pool"]["outputs"]
    del document["jobs"]["pool"]["outputs"]["dseq"]
    del before["jobs"]["pool"]["outputs"]["dseq"]
    assert document == before


def mutate_noop_rollback(document):
    before = deepcopy(document)
    old = document["jobs"]["teardown"]["uses"]
    assert old.count("/runner-teardown.yml@") == 1
    document["jobs"]["teardown"]["uses"] = old.replace(
        "/runner-teardown.yml@", "/noop.yml@"
    )
    before["jobs"]["teardown"]["uses"] = document["jobs"]["teardown"]["uses"]
    assert document == before


@pytest.mark.parametrize(
    "mutation", [mutate_missing_producer_output, mutate_noop_rollback]
)
@pytest.mark.parametrize("provision", ["failure", "cancelled"])
def test_broken_output_or_close_target_leaks_in_effect_model_and_fails_checkers(
    mutation, provision
):
    callee = graph("callee")
    mutation(callee)
    with pytest.raises(AssertionError, match="rollback-no-close"):
        lifetime(callee, graph("caller"), provision=provision)
    assert check_handoff(callee)
    assert check(callee, "pool")


def test_missing_producer_output_also_breaks_caller_cleanup_after_handoff():
    callee = graph("callee")
    mutate_missing_producer_output(callee)
    with pytest.raises(AssertionError, match="caller-no-close"):
        lifetime(callee, graph("caller"))


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
        ("callee", mutate_missing_producer_output, 1),
        ("callee", mutate_noop_rollback, 1),
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
        expected = {
            mutate_internal_close: "successful handoff",
            mutate_missing_consumer: "missing ['work']",
            mutate_missing_producer_output: "must publish dseq",
            mutate_noop_rollback: "must call the canonical runner-teardown",
        }
        assert expected[mutation] in result.stdout


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


@pytest.mark.parametrize(
    "output",
    [
        "",
        "${{ steps.missing.outputs.dseq }}",
        "${{ steps.provision.outputs.other }}",
        "invented",
    ],
)
def test_producer_output_must_resolve_to_its_existing_step(output):
    callee = graph("callee")
    callee["jobs"]["pool"]["outputs"]["dseq"] = output
    assert check_handoff(callee)
    assert check(callee, "pool")


@pytest.mark.parametrize(
    "target",
    [
        "./.github/workflows/noop.yml",
        "Digital-Frontier-LDA/just-akash/.github/workflows/runner-teardown.yml@main",
        "someone/else/.github/workflows/runner-teardown.yml@" + "a" * 40,
    ],
)
def test_unrecognized_or_floating_rollback_target_cannot_certify_cleanup(target):
    callee = graph("callee")
    callee["jobs"]["teardown"]["uses"] = target
    assert check_handoff(callee)
    assert check(callee, "pool")
