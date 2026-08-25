"""The pool-ordering rule must FIRE on the shape that cost three CI attempts.

⚠ EVERY CASE HERE IS A SHAPE MEASURED IN PRODUCTION, not a synthetic fixture.
Blazing-Back run 32837603555 carried both defective pools and both are reproduced.
"""

from __future__ import annotations

import importlib.util
import pathlib

import yaml

RULE = (
    pathlib.Path(__file__).resolve().parent / "check_pool_not_before_consumers.py"
)
_spec = importlib.util.spec_from_file_location("pool_order", RULE)
mod = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(mod)


def _doc(text: str) -> dict:
    return yaml.safe_load(text)


TARGETS = "${{ fromJSON(needs.pool.outputs.runner-targets) }}"


def test_the_locator_finds_a_pool() -> None:
    """⛔ Non-vacuity. If runs-on parsing breaks, every assertion below passes over nothing."""
    doc = _doc(
        f"""
jobs:
  gate: {{runs-on: ubuntu-latest}}
  pool: {{runs-on: ubuntu-latest}}
  work:
    needs: [gate, pool]
    runs-on: "{TARGETS}"
"""
    )
    assert mod.pools_and_consumers(doc) == {"pool": {"work"}}


def test_KNOWN_NEGATIVE_pool_scheduled_before_its_consumer_is_FLAGGED() -> None:
    """The measured defect: pool has no gates, consumer waits on one.

    This is provision-cd-pool (needs: []) against six C/D consumers that wait on
    canary-deploy and the B-tier. It produced 0 of 6 legs run, three times.
    """
    doc = _doc(
        f"""
jobs:
  gate: {{runs-on: ubuntu-latest}}
  pool: {{runs-on: ubuntu-latest}}
  work:
    needs: [gate, pool]
    runs-on: "{TARGETS}"
"""
    )
    findings = mod.check(doc)
    assert findings, "the rule did not fire on the exact production defect"
    assert "gate" in findings[0], findings
    assert "work" in findings[0], findings


def test_KNOWN_POSITIVE_pool_gated_like_its_consumer_PASSES() -> None:
    doc = _doc(
        f"""
jobs:
  gate: {{runs-on: ubuntu-latest}}
  pool:
    needs: [gate]
    if: ${{{{ !cancelled() }}}}
    runs-on: ubuntu-latest
  work:
    needs: [gate, pool]
    runs-on: "{TARGETS}"
"""
    )
    assert mod.check(doc) == []


def test_a_SIBLING_consumer_is_not_a_required_gate() -> None:
    """⚠ Excluding sibling consumers is load-bearing, not tidiness.

    recovery-c1 needs recovery-c0, and both consume the pool. Demanding the pool
    wait on recovery-c0 would make it depend on a job that depends on it — the
    rule would be requiring a cycle. This is the trap the real `needs:` set hit.
    """
    doc = _doc(
        f"""
jobs:
  gate: {{runs-on: ubuntu-latest}}
  pool:
    needs: [gate]
    if: ${{{{ !cancelled() }}}}
    runs-on: ubuntu-latest
  c0:
    needs: [gate, pool]
    runs-on: "{TARGETS}"
  c1:
    needs: [gate, pool, c0]
    runs-on: "{TARGETS}"
"""
    )
    assert mod.check(doc) == [], "a sibling consumer must not be demanded as a pool gate"


def test_a_pool_that_does_not_exist_is_reported() -> None:
    doc = _doc(
        f"""
jobs:
  work:
    runs-on: "{TARGETS}"
"""
    )
    findings = mod.check(doc)
    assert findings and "no such job exists" in findings[0]


def test_PARTIAL_fix_is_still_flagged() -> None:
    """⭐ The case that actually happened: one pool fixed, a second left defective.

    After gating provision-cd-pool correctly, E1 still queued 25+ minutes because
    provision-akash-runner had the same shape. A per-pool rule catches the second;
    a rule that stopped at the first pool would have reported clean.
    """
    doc = _doc(
        f"""
jobs:
  gate: {{runs-on: ubuntu-latest}}
  slow: {{needs: [gate], runs-on: ubuntu-latest}}
  poolA:
    needs: [gate]
    if: ${{{{ !cancelled() }}}}
    runs-on: ubuntu-latest
  poolB:
    runs-on: ubuntu-latest
  workA:
    needs: [gate, poolA]
    runs-on: "${{{{ fromJSON(needs.poolA.outputs.runner-targets) }}}}"
    # Keep this fixture tied to the shared target expression: {TARGETS}
  workB:
    needs: [gate, slow, poolB]
    runs-on: "${{{{ fromJSON(needs.poolB.outputs.runner-targets) }}}}"
"""
    )
    findings = mod.check(doc)
    assert len(findings) == 1, f"expected exactly the poolB finding, got {findings}"
    assert "poolB" in findings[0] and "workB" in findings[0], findings


def test_pool_without_needs_is_not_flagged_for_implicit_success() -> None:
    doc = _doc(
        f"""
jobs:
  pool:
    runs-on: ubuntu-latest
  work:
    needs: [pool]
    runs-on: "{TARGETS}"
"""
    )
    assert not [f for f in mod.check(doc) if "status-check function" in f]


def test_pool_with_needs_and_not_cancelled_passes_liveness_check() -> None:
    doc = _doc(
        f"""
jobs:
  gate: {{runs-on: ubuntu-latest}}
  pool:
    needs: [gate]
    if: ${{{{ !cancelled() }}}}
    runs-on: ubuntu-latest
  work:
    needs: [gate, pool]
    runs-on: "{TARGETS}"
"""
    )
    assert not [f for f in mod.check(doc) if "status-check function" in f]


def test_pool_with_needs_and_always_warns_about_lease_leak() -> None:
    doc = _doc(
        f"""
jobs:
  gate: {{runs-on: ubuntu-latest}}
  pool:
    needs: [gate]
    if: ${{{{ always() }}}}
    runs-on: ubuntu-latest
  work:
    needs: [gate, pool]
    runs-on: "{TARGETS}"
"""
    )
    findings = mod.check(doc)
    assert any("uses always()" in f for f in findings), findings
    assert not any("no status-check function" in f for f in findings), findings


def test_blazing_back_pool_with_needs_but_no_status_function_is_flagged() -> None:
    doc = _doc(
        f"""
jobs:
  provision-cd-pool:
    needs: [canary-deploy, setup-providers, smoke-dfc, smoke-single]
    if: ${{{{ github.event.action != 'closed' }}}}
    runs-on: ubuntu-latest
  c0:
    needs: [canary-deploy, setup-providers, smoke-dfc, smoke-single, provision-cd-pool]
    runs-on: "{TARGETS.replace('pool', 'provision-cd-pool')}"
"""
    )
    findings = mod.check(doc)
    assert any("provision-cd-pool" in f and "no status-check function" in f for f in findings)


def test_provision_akash_runner_with_always_is_not_implicit_success() -> None:
    doc = _doc(
        f"""
jobs:
  provision-akash-runner:
    needs: [classify-changes]
    if: ${{{{ always() && github.event.action != 'closed' }}}}
    runs-on: ubuntu-latest
  e1:
    needs: [classify-changes, provision-akash-runner]
    runs-on: "{TARGETS.replace('pool', 'provision-akash-runner')}"
"""
    )
    findings = mod.check(doc)
    assert not any("no status-check function" in f for f in findings), findings
    assert any("uses always()" in f for f in findings), findings
