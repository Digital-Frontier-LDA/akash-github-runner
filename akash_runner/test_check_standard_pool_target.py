"""check_standard must be able to judge the canonical POOL, not only its consumers.

⛔ MEASURED — just-akash#200, run 32826850257, the first execution of these rules against
real code (8 prior runs produced jobs=0 because a public repo cannot call an internal
reusable). It reported:

    no canonical just-akash runner-pool reusable job found

against `.github/workflows/runner-pool.yml`, which IS the canonical pool. The locator
selects jobs that `uses:` the pool — it is written for CONSUMERS — and a pool does not
`uses:` itself.

★ THE TARGET REPO IS NOT AT FAULT AND NEITHER IS THE RULE. Every other rule judged the
same file correctly in that run (teardown-can-identify PASS on 4 run-steps,
pool-owns-teardown PASS on 2 jobs). What was missing is a mode.

⚠ just-akash has NO consumer workflow — it is the pool OWNER, and runner-conformance.yml
dogfoods the check against its own pool on purpose ("if the canonical pool workflow
doesn't satisfy the contract, the conformance check fails on this repo's own PRs"). So
"reject a pool target and tell them to point at a consumer" would leave that repo with
nothing to check and silently drop the pool from coverage. The pool's own contract is
today verified by NOTHING.

⇒ Pool mode checks the SUPPLY side of exactly the contract consumer mode demands: every
input consumer mode requires a consumer to PASS, every secret it requires MAPPED, and
every output it DEREFERENCES, must be declared by the pool. If the pool dropped `dseq`
from its outputs, every downstream teardown pairing would break and nothing would catch it.
"""

from __future__ import annotations

from akash_runner.check_standard import check

NO_POOL = "no canonical just-akash runner-pool reusable job found"


def _pool(inputs=None, secrets=None, outputs=None, jobs=None):
    """A minimal well-formed canonical pool."""
    return {
        "on": {
            "workflow_call": {
                "inputs": {
                    k: {"required": True, "type": "string"}
                    for k in (
                        inputs
                        if inputs is not None
                        else ["runner-label", "tag-prefix", "github-org", "providers"]
                    )
                },
                "secrets": {
                    k: {"required": True}
                    for k in (
                        secrets
                        if secrets is not None
                        else ["AKASH_API_KEY", "AKASH_API_KEYS", "GH_RUNNER_PAT"]
                    )
                },
                "outputs": {
                    k: {"value": "x"}
                    for k in (
                        outputs
                        if outputs is not None
                        else ["dseq", "runner-targets"]
                    )
                },
            }
        },
        "jobs": jobs if jobs is not None else {"pool": {"runs-on": "ubuntu-latest"}},
    }


# ── The reported defect ──────────────────────────────────────────────────────────────


def test_a_well_formed_pool_is_not_reported_as_a_missing_pool():
    """★ THE BUG. This is the exact string just-akash#200 got against its own pool."""
    assert NO_POOL not in check(_pool())


def test_a_well_formed_pool_has_no_findings_at_all():
    assert check(_pool()) == []


# ── Pool mode is NOT vacuous: each half of the contract has a known-negative ─────────


def test_pool_missing_a_required_consumer_input_is_rejected():
    """Consumer mode requires a consumer to pass `providers`. A pool that does not
    declare it makes every conforming consumer un-callable."""
    findings = check(_pool(inputs=["runner-label", "tag-prefix", "github-org"]))
    assert any("providers" in f for f in findings), findings


def test_pool_missing_a_required_secret_is_rejected():
    findings = check(_pool(secrets=["AKASH_API_KEY", "GH_RUNNER_PAT"]))
    assert any("AKASH_API_KEYS" in f for f in findings), findings


def test_pool_that_stops_publishing_dseq_is_rejected():
    """⛔ THE HIGH-VALUE CASE. Consumer mode pairs a teardown by matching
    `needs.<pool>.outputs.dseq`. If the pool stops publishing dseq, every consumer's
    teardown pairing silently breaks — and nothing in this package would notice."""
    findings = check(_pool(outputs=["runner-targets"]))
    assert any("dseq" in f for f in findings), findings


def test_pool_that_stops_publishing_runner_targets_is_rejected():
    """Consumers put `needs.<pool>.outputs.runner-targets` in runs-on."""
    findings = check(_pool(outputs=["dseq"]))
    assert any("runner-targets" in f for f in findings), findings


# ── The teardown predicate rule is target-agnostic and must still fire in pool mode ──


def test_result_gated_teardown_inside_the_pool_is_still_caught():
    """This rule runs before the pool gate precisely so it is never mode-dependent."""
    findings = check(
        _pool(
            jobs={
                "provision": {"runs-on": "ubuntu-latest"},
                "close-runner": {
                    "needs": ["provision"],
                    "if": "always() && needs.provision.result == 'success'",
                    "runs-on": "ubuntu-latest",
                },
            }
        )
    )
    assert any("must not be gated on its provisioner's result" in f for f in findings)


# ── Consumer mode must be untouched ──────────────────────────────────────────────────


def test_a_plain_repo_is_still_reported_as_having_no_pool():
    """Regression guard on the characterisation tests: adding pool mode must not make
    an ordinary non-canonical repo start being judged as a pool."""
    assert check({"jobs": {"build": {"runs-on": "ubuntu-latest"}}}) == [NO_POOL]


def test_an_unrelated_reusable_workflow_is_not_mistaken_for_the_pool():
    """⚠ The narrow-detection boundary. `on: workflow_call` alone must NOT select pool
    mode, or every reusable workflow in the org starts being judged against the pool
    contract and the rule's scope silently widens."""
    doc = {
        "on": {"workflow_call": {"inputs": {"foo": {"type": "string"}}}},
        "jobs": {"build": {"runs-on": "ubuntu-latest"}},
    }
    assert check(doc) == [NO_POOL]


# ── CLI surface ──────────────────────────────────────────────────────────────────────

import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _run(*args):
    return subprocess.run(
        [sys.executable, str(ROOT / "akash_runner" / "check_standard.py"), *args],
        capture_output=True,
        text=True,
    )


def _write(tmp_path, doc):
    p = tmp_path / "wf.yml"
    p.write_text(yaml.safe_dump(doc))
    return str(p)


def test_cli_accepts_an_explicit_pool_target_kind(tmp_path):
    r = _run("--target-kind", "pool", _write(tmp_path, _pool()))
    assert r.returncode == 0, r.stdout + r.stderr


def test_cli_explicit_pool_mode_fails_a_pool_missing_dseq(tmp_path):
    """Known-positive control: the mode is not inert when driven from the CLI."""
    r = _run("--target-kind", "pool", _write(tmp_path, _pool(outputs=["runner-targets"])))
    assert r.returncode == 1
    assert "dseq" in r.stdout


def test_cli_still_accepts_the_bare_double_dash_call_used_by_the_action(tmp_path):
    """⚠ The composite action invokes `check_standard.py -- "$WORKFLOW"`. Adding an
    option must not break that call shape."""
    r = _run("--", _write(tmp_path, _pool()))
    assert r.returncode == 0, r.stdout + r.stderr


def test_cli_names_pool_mode_when_a_consumer_scan_finds_no_pool(tmp_path):
    """⛔ The message just-akash#200 actually received said only that no pool was found,
    which reads as 'your repo is wrong' when the truth was 'you pointed me at the pool'.
    The finding string itself is pinned by the characterisation tests, so the guidance
    goes alongside it — not into the finding."""
    r = _run(_write(tmp_path, {"jobs": {"build": {"runs-on": "ubuntu-latest"}}}))
    assert r.returncode == 1
    assert "--target-kind pool" in r.stdout + r.stderr
