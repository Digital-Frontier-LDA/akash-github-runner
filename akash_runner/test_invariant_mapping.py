"""Prove the leak-safety invariants declared in standards/AKASH-RUNNER-CI.md are
enforced by the conformance checker.

The standards doc maps each invariant to a finding emitted by
`akash_runner/check_standard.check()`. This test asserts the mapping by
mutating a valid workflow in the way the invariant forbids and confirming the
named finding appears. A future edit to either side (the doc's mapping table
or the checker's findings) must update the other; the tests are the cross-check.
"""

import json
from copy import deepcopy

import pytest

from akash_runner.check_standard import check

REF = "v1.43.1"
PROVIDERS = (
    '[{"address":"akash1hgulk6aekakqzc0v6wukrd3dy9n90f5gkl4ezk","preferred":true},'
    '{"address":"akash1z9nr23cgweu45g2jktfx95v7g2xp8qlsa3ys2x","preferred":true},'
    '{"address":"akash1aaul837r7en7hpk9wv2svg8u78fdq0t2j2e82z","preferred":true,"runner_host":true},'
    '{"address":"akash1s3hq36mpas4nmkqasn7fgwhs9968cgl3u5esnw","preferred":false,"runner_host":true,"ci_only":true},'
    '{"address":"akash1ggfvyhr9sar4uxjs4hth3p4kzrwk7lysnenj3g","preferred":false,"runner_host":true,"ci_only":true},'
    '{"address":"akash15tl6v6gd0nte0syyxnv57zmmspgju4c3xfmdhk","ci_only":true},'
    '{"address":"akash19zzh7whjt4vfwxd5wtj3tjtyatnpntfhldshd8","runner_deny":true,"ci_only":true}]'
)


def _valid_workflow() -> dict:
    label = "pool-${{ github.run_id }}"
    secrets = {
        "AKASH_API_KEY": "${{ secrets.AKASH_API_KEY }}",
        "AKASH_API_KEYS": "${{ secrets.AKASH_API_KEYS }}",
        "GH_RUNNER_PAT": "${{ secrets.GH_RUNNER_PAT }}",
    }
    return {
        "jobs": {
            "pool": {
                "uses": f"Digital-Frontier-LDA/just-akash/.github/workflows/runner-pool.yml@{REF}",
                "with": {
                    "runner-label": label,
                    "tag-prefix": "ci-example",
                    "github-org": "Borduas-Holdings",
                    "providers": PROVIDERS,
                },
                "secrets": dict(secrets),
            },
            "work": {
                "needs": ["pool"],
                "runs-on": "${{ fromJSON(needs.pool.outputs.runner-targets) }}",
                "steps": [{"run": "pytest"}],
            },
            "teardown": {
                "needs": ["pool", "work"],
                "if": "${{ always() }}",
                "uses": f"Digital-Frontier-LDA/just-akash/.github/workflows/runner-teardown.yml@{REF}",
                "with": {
                    "dseq": "${{ needs.pool.outputs.dseq }}",
                    "runner-label": label,
                    "tag-prefix": "ci-example",
                    "github-org": "Borduas-Holdings",
                },
                "secrets": dict(secrets),
            },
        }
    }


def _assert_finding_contains(findings: list[str], fragment: str):
    assert any(fragment in f for f in findings), (
        f"expected a finding containing {fragment!r}, got: {findings}"
    )


# --- Invariant 1: repo-specific tag-prefix is mandatory ----------------------

def test_invariant_1_missing_tag_prefix_fails_with_required_input_finding():
    workflow = _valid_workflow()
    workflow["jobs"]["pool"]["with"].pop("tag-prefix")
    findings = check(workflow)
    _assert_finding_contains(findings, "missing required input tag-prefix")


# --- Invariant 3: catch-all local destroy is forbidden -----------------------

@pytest.mark.parametrize(
    "command",
    [
        "just-akash destroy --dseq 1 -y",
        "just-akash close 1",
        "just-akash close-all",
    ],
)
def test_invariant_3_local_close_command_emits_canonical_teardown_finding(command):
    workflow = _valid_workflow()
    workflow["jobs"]["work"]["steps"].append({"run": command})
    _assert_finding_contains(check(workflow), "local close logic bypasses canonical runner-teardown")


def test_invariant_3_close_deployment_action_emits_canonical_teardown_finding():
    workflow = _valid_workflow()
    # Replace any pre-existing steps so the close-deployment action is the
    # ONLY thing the checker reacts to — avoids a coincidental 'just-akash
    # close' match from earlier steps.
    workflow["jobs"]["work"]["steps"] = [
        {"uses": "dfc/close-deployment@v1"},
    ]
    # The finding text is constant; the trigger is `close-deployment` in
    # the step's `uses:`. The test asserts the trigger and the finding
    # together: the matcher says the LOCAL close path is forbidden.
    _assert_finding_contains(check(workflow), "local close logic bypasses canonical runner-teardown")


# --- Invariant 4a: if: always() is required ----------------------------------

def test_invariant_4a_missing_if_always_emits_teardown_must_use_finding():
    workflow = _valid_workflow()
    workflow["jobs"]["teardown"].pop("if")
    _assert_finding_contains(check(workflow), "if: always()")


# --- Invariant 4b: complete needs on teardown -------------------------------

def test_invariant_4b_new_consumer_must_appear_in_teardown_needs():
    workflow = _valid_workflow()
    workflow["jobs"]["other"] = {
        "needs": ["pool"],
        "runs-on": "${{ fromJSON(needs.pool.outputs.runner-targets) }}",
    }
    _assert_finding_contains(check(workflow), "missing ['other']")


def test_invariant_4b_pool_omitted_from_teardown_needs_is_caught():
    workflow = _valid_workflow()
    workflow["jobs"]["teardown"]["needs"] = ["work"]
    _assert_finding_contains(check(workflow), "missing ['pool']")


# --- Pin / identity / credentials match -------------------------------------

def test_identity_mismatch_runner_label_emits_exact_match_finding():
    workflow = _valid_workflow()
    workflow["jobs"]["teardown"]["with"]["runner-label"] = "ci-other-${{ github.run_id }}"
    _assert_finding_contains(check(workflow), "runner-label must exactly match")


def test_credential_mismatch_akash_api_keys_emits_credential_finding():
    workflow = _valid_workflow()
    workflow["jobs"]["teardown"]["secrets"]["AKASH_API_KEYS"] = "${{ secrets.OTHER }}"
    _assert_finding_contains(check(workflow), "credential field AKASH_API_KEYS must match")


def test_pool_pin_drift_to_branch_emits_immutable_finding():
    workflow = _valid_workflow()
    workflow["jobs"]["pool"]["uses"] = (
        "Digital-Frontier-LDA/just-akash/.github/workflows/runner-pool.yml@main"
    )
    _assert_finding_contains(check(workflow), "not immutable")


def test_pool_and_teardown_pin_drift_emits_refs_differ_finding():
    workflow = _valid_workflow()
    workflow["jobs"]["pool"]["uses"] = (
        workflow["jobs"]["pool"]["uses"].replace(REF, "v1.42.0")
    )
    _assert_finding_contains(check(workflow), "refs differ")


# --- Provider policy --------------------------------------------------------

def test_provider_policy_exact_three_fleet_required():
    workflow = _valid_workflow()
    workflow["jobs"]["pool"]["with"]["providers"] = (
        '[{"address":"akash15tl6v6gd0nte0syyxnv57zmmspgju4c3xfmdhk","preferred":true}]'
    )
    _assert_finding_contains(check(workflow), "exactly the three-provider DF fleet")


def test_provider_policy_preferred_cannot_overlap_excluded():
    workflow = _valid_workflow()
    providers = json.loads(PROVIDERS)
    providers[0]["runner_deny"] = True
    workflow["jobs"]["pool"]["with"]["providers"] = json.dumps(providers)
    _assert_finding_contains(check(workflow), "overlap standing exclusions")


def test_provider_policy_requires_at_least_one_standing_exclusion():
    workflow = _valid_workflow()
    providers = [p for p in json.loads(PROVIDERS) if not p.get("runner_deny")]
    workflow["jobs"]["pool"]["with"]["providers"] = json.dumps(providers)
    _assert_finding_contains(check(workflow), "no standing runner_deny exclusions")
