"""Reusable producers roll back failed handoff without retiring successful consumers."""

from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from akash_runner.check_pool_owns_teardown import check  # noqa: E402

MAIN = """
on:
  workflow_call:
    outputs:
      dseq:
        value: ${{ jobs.pool.outputs.dseq }}
jobs:
  pool:
    runs-on: ubuntu-latest
    outputs:
      dseq: ${{ steps.provision.outputs.dseq }}
    steps:
      - id: provision
        run: echo "dseq=1" >> "$GITHUB_OUTPUT"
"""

EARLY_CLOSE_182 = (
    MAIN
    + """  teardown:
    needs: [pool]
    if: always()
    uses: ./.github/workflows/runner-teardown.yml
    with:
      dseq: ${{ needs.pool.outputs.dseq }}
"""
)


def _c(text):
    return check(yaml.safe_load(text) or {})


def test_known_bad_a_pool_with_no_teardown_job_fails():
    findings = _c(MAIN)
    assert findings and "contains no teardown job" in findings[0]


def test_unconditional_internal_teardown_retires_before_handoff_and_fails():
    assert any("successful handoff" in f for f in _c(EARLY_CLOSE_182))


def test_failed_or_cancelled_provisioning_rolls_back():
    fixed = EARLY_CLOSE_182.replace(
        "if: always()", "if: always() && needs.pool.result != 'success'"
    )
    assert _c(fixed) == []


def test_the_population_is_not_empty_which_is_why_this_rule_replaced_the_consumer_one():
    """★★ THE VACUITY CONTROL. The rule this replaces — "every pool CONSUMER wires a
    teardown" — has ZERO consumers to check, so it passes over an empty set and cannot
    fail. This one selects on a property the pool workflow ITSELF has, so its population
    is non-empty by construction. If this ever selects nothing, every other test here is
    vacuous."""
    from akash_runner.check_pool_owns_teardown import _published_identities

    assert _published_identities(yaml.safe_load(MAIN)) == {"dseq": "pool"}


def test_a_teardown_that_does_not_need_the_producer_fails():
    detached = EARLY_CLOSE_182.replace("    needs: [pool]\n", "")
    findings = _c(detached)
    assert any("must need 'pool'" in f for f in findings)


def test_a_result_gated_teardown_fails():
    gated = EARLY_CLOSE_182.replace(
        "if: always()", "if: always() && needs.pool.result == 'success'"
    )
    findings = _c(gated)
    assert any("internal rollback must use" in f for f in findings)


def test_a_teardown_preconditioned_on_the_identity_fails():
    """Identity presence alone does not distinguish successful handoff from rollback."""
    precond = EARLY_CLOSE_182.replace(
        "if: always()", "if: always() && needs.pool.outputs.dseq != ''"
    )
    findings = _c(precond)
    assert any("internal rollback must use" in f for f in findings)


def test_a_workflow_publishing_no_lifecycle_identity_is_out_of_scope():
    """★ KNOWN-NEGATIVE: this rule must not demand a teardown of every reusable workflow."""
    assert (
        _c(
            "on:\n  workflow_call:\n    outputs:\n      report:\n        value: x\njobs:\n  run: {}\n"
        )
        == []
    )


def test_the_yaml_boolean_on_key_is_handled():
    """★ A bare `on:` parses as True, not "on". Reading document["on"] finds nothing and
    every pool silently leaves scope — the rule would pass everything."""
    document = yaml.safe_load(MAIN)
    assert True in document, "fixture no longer exercises the boolean-key trap"
    assert _c(MAIN), "the trap is unhandled: a real known-bad produced no finding"


def _manual_proof_document():
    document = yaml.safe_load(
        EARLY_CLOSE_182.replace(
            "if: always()", "if: always() && needs.pool.result != 'success'"
        )
    )
    document[True]["workflow_dispatch"] = {
        "inputs": {"private-proof": {"type": "boolean", "default": False}}
    }
    document["jobs"]["consumer"] = {"needs": "pool", "runs-on": "ubuntu-latest"}
    document["jobs"]["close-private-proof"] = {
        "needs": ["pool", "consumer"],
        "if": "always() && github.event_name == 'workflow_dispatch' && "
        "inputs.private-proof == true && needs.pool.outputs.dseq != ''",
        "uses": "./.github/workflows/akash-close.yml",
        "with": {"dseq": "${{ needs.pool.outputs.dseq }}"},
    }
    return document


def test_dispatch_only_consumer_closer_preserves_the_reusable_handoff():
    assert check(_manual_proof_document()) == []


def test_manual_closer_cannot_replace_the_required_reusable_rollback():
    document = _manual_proof_document()
    del document["jobs"]["teardown"]
    assert any("contains no teardown job" in finding for finding in check(document))


@pytest.mark.parametrize(
    "replacement",
    [
        "always() && needs.pool.outputs.dseq != ''",
        "always() && github.event_name == 'workflow_dispatch' && needs.pool.outputs.dseq != ''",
        "always() && inputs.private-proof == true && needs.pool.outputs.dseq != ''",
        "always() && github.event_name == 'workflow_dispatch' && inputs.private-proof == false && needs.pool.outputs.dseq != ''",
        "always() && github.event_name == 'workflow_dispatch' && inputs.private-proof == true && needs.pool.outputs.dseq != '' || true",
        "!(always() && github.event_name == 'workflow_dispatch' && inputs.private-proof == true && needs.pool.outputs.dseq != '')",
        "always() && github.event_name == 'workflow_dispatch' && inputs.private-proof == true && needs.pool.outputs.dseq != '' && true",
    ],
    ids=[
        "identity-only",
        "event-only",
        "input-only",
        "false-gate",
        "or",
        "not",
        "extra",
    ],
)
def test_manual_scope_expression_mutations_remain_in_rollback_scope(replacement):
    document = _manual_proof_document()
    document["jobs"]["close-private-proof"]["if"] = replacement
    assert any("close-private-proof" in finding for finding in check(document))


@pytest.mark.parametrize(
    "mutation",
    [
        "call-input",
        "call-input-upper",
        "dispatch-case-alias",
        "call-case-alias",
        "call-nonascii",
        "default-on",
        "string-default",
        "required",
        "type",
        "no-input",
    ],
)
def test_manual_scope_input_schema_mutations_remain_in_rollback_scope(mutation):
    document = _manual_proof_document()
    spec = document[True]["workflow_dispatch"]["inputs"]["private-proof"]
    if mutation == "call-input":
        document[True]["workflow_call"]["inputs"] = {
            "private-proof": {"type": "boolean", "default": False}
        }
    elif mutation == "call-input-upper":
        document[True]["workflow_call"]["inputs"] = {
            "PRIVATE-PROOF": {"type": "boolean", "default": True}
        }
    elif mutation == "dispatch-case-alias":
        document[True]["workflow_dispatch"]["inputs"]["PRIVATE-PROOF"] = {
            "type": "boolean",
            "default": True,
        }
    elif mutation == "call-case-alias":
        document[True]["workflow_call"]["inputs"] = {
            "other": {"type": "string"},
            "OTHER": {"type": "string"},
        }
    elif mutation == "call-nonascii":
        document[True]["workflow_call"]["inputs"] = {
            "prıvate-proof": {"type": "boolean"}
        }
    elif mutation == "default-on":
        spec["default"] = True
    elif mutation == "string-default":
        spec["default"] = "false"
    elif mutation == "required":
        spec["required"] = True
    elif mutation == "type":
        spec["type"] = "string"
    else:
        document[True]["workflow_dispatch"]["inputs"] = {}
    assert any("close-private-proof" in finding for finding in check(document))


def test_manual_scope_cannot_donate_identity_or_producer_dependency():
    original = _manual_proof_document()
    for field, value in (
        ("needs", ["consumer"]),
        ("with", {"dseq": "${{ needs.other.outputs.dseq }}"}),
    ):
        document = deepcopy(original)
        document["jobs"]["close-private-proof"][field] = value
        assert any("close-private-proof" in finding for finding in check(document))
