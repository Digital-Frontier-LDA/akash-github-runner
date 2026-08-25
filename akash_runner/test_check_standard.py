from copy import deepcopy
import json

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


def valid_workflow():
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


def test_canonical_lifecycle_passes():
    assert check(valid_workflow()) == []


def test_teardown_must_wait_for_every_pool_consumer():
    workflow = valid_workflow()
    workflow["jobs"]["other"] = {
        "needs": ["pool"],
        "runs-on": "${{ fromJSON(needs.pool.outputs.runner-targets) }}",
    }
    assert any("missing ['other']" in finding for finding in check(workflow))


def test_always_is_required_and_local_destroy_is_forbidden():
    workflow = valid_workflow()
    workflow["jobs"]["teardown"].pop("if")
    workflow["jobs"]["work"]["steps"].append({"run": "just-akash destroy --dseq 1 -y"})
    findings = check(workflow)
    assert any("if: always()" in finding for finding in findings)
    assert any("local close logic" in finding for finding in findings)


def test_every_local_just_akash_close_spelling_is_forbidden():
    for command in ("just-akash close 1", "just-akash close-all", "just-akash destroy --dseq 1"):
        workflow = valid_workflow()
        workflow["jobs"]["work"]["steps"].append({"run": command})
        assert any("local close logic" in finding for finding in check(workflow)), command


def test_pool_and_teardown_must_use_same_immutable_release():
    workflow = valid_workflow()
    workflow["jobs"]["pool"]["uses"] = workflow["jobs"]["pool"]["uses"].replace(REF, "main")
    workflow["jobs"]["teardown"]["uses"] = workflow["jobs"]["teardown"]["uses"].replace(
        REF, "v1.42.0"
    )
    findings = check(workflow)
    assert any("not immutable" in finding for finding in findings)
    assert any("refs differ" in finding for finding in findings)


def test_identity_and_secret_mismatches_fail():
    workflow = deepcopy(valid_workflow())
    workflow["jobs"]["teardown"]["with"]["tag-prefix"] = "ci-sibling"
    workflow["jobs"]["teardown"]["secrets"]["AKASH_API_KEYS"] = "${{ secrets.OTHER }}"
    findings = check(workflow)
    assert any("tag-prefix must exactly match" in finding for finding in findings)
    assert any("credential field AKASH_API_KEYS must match" in finding for finding in findings)


def test_secrets_inherit_is_rejected_without_crashing():
    workflow = valid_workflow()
    workflow["jobs"]["pool"]["secrets"] = "inherit"
    workflow["jobs"]["teardown"]["secrets"] = "inherit"
    assert any("secrets: inherit is not allowed" in finding for finding in check(workflow))


def test_non_mapping_with_is_reported_without_crashing():
    workflow = valid_workflow()
    workflow["jobs"]["pool"]["with"] = "not-a-mapping"
    assert any("with must be a mapping" in finding for finding in check(workflow))


def test_provider_policy_is_required_and_must_contain_exact_preferred_fleet():
    workflow = valid_workflow()
    workflow["jobs"]["pool"]["with"].pop("providers")
    assert any("missing required input providers" in finding for finding in check(workflow))

    workflow = valid_workflow()
    workflow["jobs"]["pool"]["with"]["providers"] = (
        '[{"address":"akash15tl6v6gd0nte0syyxnv57zmmspgju4c3xfmdhk","preferred":true}]'
    )
    assert any("exactly the three-provider DF fleet" in finding for finding in check(workflow))


def test_preferred_provider_cannot_overlap_standing_exclusions():
    workflow = valid_workflow()
    providers = json.loads(PROVIDERS)
    providers[0]["runner_deny"] = True
    workflow["jobs"]["pool"]["with"]["providers"] = json.dumps(providers)
    assert any("overlap standing exclusions" in finding for finding in check(workflow))


def test_standing_exclusion_is_required():
    workflow = valid_workflow()
    providers = [p for p in json.loads(PROVIDERS) if not p.get("runner_deny")]
    workflow["jobs"]["pool"]["with"]["providers"] = json.dumps(providers)
    assert any("no standing runner_deny exclusions" in finding for finding in check(workflow))
