"""A workflow that spends money on leases without consuming the pool has a category now (#11).

⛔ The standard had exactly two: `pool` (it IS the canonical just-akash runner pool) and
`consumer` (it `uses:` that pool). A workflow that manages Akash lease lifecycle without
consuming the pool fits neither — so `auto` calls it a consumer and reports a missing pool it
was never supposed to have, and the honest response was to point nothing at it. Then nothing
judged it. df-cicd#1553 measured 484 ACT left in unclosed orders behind exactly this shape.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import yaml

RULE = Path(__file__).with_name("check_standard.py")
_spec = importlib.util.spec_from_file_location("check_standard_ls", RULE)
assert _spec and _spec.loader
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)

# Shape drawn from the worked example in #11: df-akash-gate.yml carries the
# `just-akash close "$DSEQ"` teardown and never `uses:` a canonical pool.
SPENDER = yaml.safe_load(
    "on:\n"
    "  workflow_call: {}\n"
    "jobs:\n"
    "  gate:\n"
    "    runs-on: ubuntu-latest\n"
    "    steps:\n"
    '      - run: just-akash close "$DSEQ"\n'
)
NOT_A_SPENDER = yaml.safe_load(
    "on:\n  push: {}\njobs:\n  build:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo hi\n"
)


def test_a_lease_spender_is_not_accused_of_missing_a_pool() -> None:
    assert mod.check(SPENDER, target_kind="lease-spender") == []


def test_KNOWN_NEGATIVE_the_same_file_under_auto_still_reports_the_missing_pool() -> (
    None
):
    """⭐ The control that proves the new kind changes something. Without it the file is
    judged as a consumer and fails on a pool it was never meant to have."""
    findings = mod.check(SPENDER, target_kind="auto")
    assert any("no canonical just-akash runner-pool" in f for f in findings)


def test_the_category_CANNOT_be_used_as_an_escape_hatch() -> None:
    """⛔ Declaring this kind suppresses the pool requirement, so a real consumer could
    silence a genuine finding by mislabelling itself. The declaration is CHECKED."""
    findings = mod.check(NOT_A_SPENDER, target_kind="lease-spender")
    assert findings, "a file with no lease lifecycle must NOT pass as a lease-spender"
    assert any("no Akash lease lifecycle" in f for f in findings)


@pytest.mark.parametrize(
    "step",
    [
        'just-akash close "$DSEQ"',
        "curl -X DELETE https://console-api.akash.network/v1/deployments/$DSEQ",
        "python3 -c 'close_deployment(dseq)'",
        "echo dseq=$DSEQ",
    ],
)
def test_lease_evidence_is_recognised_in_its_real_forms(step: str) -> None:
    doc = yaml.safe_load(
        f"on:\n  workflow_call: {{}}\njobs:\n  j:\n    runs-on: ubuntu-latest\n"
        f"    steps:\n      - run: {step!r}\n"
    )
    assert mod._spends_on_leases(doc), f"should count as lease lifecycle: {step}"


def test_the_teardown_rules_still_run_under_the_new_kind() -> None:
    """⚠ The whole value is that teardown IS judged. A result-gated teardown must still be
    reported — otherwise the new category is a way to stop being judged at all."""
    # ⚠ The gate must be on a PROVISIONER'S RESULT (`needs.<job>.result`), which is the
    # actual defect shape. A bare `success()` is a different thing and RESULT_GATE
    # deliberately does not match it — my first version of this fixture used `success()`
    # and failed, and the FIXTURE was wrong, not the rule.
    gated = yaml.safe_load(
        "on:\n"
        "  workflow_call: {}\n"
        "jobs:\n"
        "  close:\n"
        "    runs-on: ubuntu-latest\n"
        "    if: needs.provision.result == 'success'\n"
        "    steps:\n"
        '      - run: just-akash close "$DSEQ"\n'
    )
    findings = mod.check(gated, target_kind="lease-spender")
    assert findings, (
        "a success()-gated teardown must still be caught under lease-spender"
    )


def test_the_existing_kinds_are_unchanged() -> None:
    assert mod.check(NOT_A_SPENDER, target_kind="auto") == mod.check(
        NOT_A_SPENDER, target_kind="consumer"
    )
