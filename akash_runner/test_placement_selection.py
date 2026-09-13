"""Mutation-backed contract for request-aware Akash provider selection."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from akash_runner import check_standard as standard
from akash_runner.test_check_standard import valid_workflow


CAPABLE_REF = "f" * 40
OLD_REF = "16e47373f5fead96de2cd0f9609e4b50fb8e845"
CAPABLE = {
    CAPABLE_REF: frozenset({"request_profiles", "per_node_fit"}),
}


def _runner_pool():
    document = valid_workflow()
    for job_name in ("pool", "teardown"):
        document["jobs"][job_name]["uses"] = document["jobs"][job_name][
            "uses"
        ].replace("v1.43.1", CAPABLE_REF)
    document["jobs"]["pool"]["with"].update(
        {"provider-select": "emptiest", "just-akash-ref": CAPABLE_REF}
    )
    return document


def _check(document):
    return standard.check(document, placement_implementations=CAPABLE)


def _selection_findings(document):
    return [
        finding
        for finding in _check(document)
        if "provider-select" in finding
        or "just-akash-ref" in finding
        or "request-aware per-node" in finding
        or "price ranking" in finding
        or "invokes just-akash deploy" in finding
    ]


def test_planted_request_aware_runner_pool_passes():
    assert _check(_runner_pool()) == []


def test_missing_provider_select_mutation_is_rejected():
    document = _runner_pool()
    target = "provider-select"
    assert list(document["jobs"]["pool"]["with"]).count(target) == 1
    document["jobs"]["pool"]["with"].pop(target)
    assert any("provider-select" in finding for finding in _selection_findings(document))


def test_old_implementation_pin_mutation_is_rejected():
    document = _runner_pool()
    target = CAPABLE_REF
    replacement = OLD_REF
    encoded = str(document)
    assert encoded.count(target) == 3
    for job_name in ("pool", "teardown"):
        document["jobs"][job_name]["uses"] = document["jobs"][job_name][
            "uses"
        ].replace(target, replacement)
    document["jobs"]["pool"]["with"]["just-akash-ref"] = replacement
    assert any(
        "not stamped for request-aware per-node placement" in finding
        for finding in _selection_findings(document)
    )


def test_call_site_ref_wiring_mutation_is_rejected():
    document = _runner_pool()
    target = CAPABLE_REF
    assert document["jobs"]["pool"]["with"]["just-akash-ref"].count(target) == 1
    document["jobs"]["pool"]["with"]["just-akash-ref"] = OLD_REF
    assert any(
        "just-akash-ref must exactly match" in finding
        for finding in _selection_findings(document)
    )


def test_request_profile_only_candidate_is_not_blessed_as_per_node_capable():
    candidate = "ebf2e37ac786ad1b7a0643625cbe0626131707fa"
    assert standard.PLACEMENT_IMPLEMENTATIONS[candidate] == frozenset(
        {"request_profiles"}
    )
    document = _runner_pool()
    document["jobs"]["pool"]["uses"] = document["jobs"]["pool"]["uses"].replace(
        CAPABLE_REF, candidate
    )
    findings = standard.check(document)
    assert any("per_node_fit" in finding for finding in findings)


def _lease_spender(script: str):
    return {
        "jobs": {
            "deploy": {
                "runs-on": "ubuntu-latest",
                "steps": [{"run": script}, {"run": "just-akash close 123"}],
            }
        }
    }


def test_planted_explicit_emptiest_deploy_passes_selection():
    document = _lease_spender(
        "just-akash deploy --select emptiest --provider akash1a --provider akash1b"
    )
    assert _selection_findings(document) == []


def test_multi_provider_deploy_without_select_mutation_is_rejected():
    script = "just-akash deploy --select emptiest --provider akash1a --provider akash1b"
    target = "--select emptiest "
    assert script.count(target) == 1
    document = _lease_spender(script.replace(target, ""))
    assert any("invokes just-akash deploy" in f for f in _selection_findings(document))


def test_single_provider_without_select_is_the_negative_control():
    document = _lease_spender("just-akash deploy --provider akash1only")
    assert _selection_findings(document) == []


def test_one_safe_deploy_cannot_mask_a_second_missing_select():
    document = _lease_spender(
        "just-akash deploy --select emptiest --provider akash1a --provider akash1b\n"
        "just-akash deploy --provider akash1a --provider akash1b"
    )
    findings = _selection_findings(document)
    assert sum("invokes just-akash deploy" in finding for finding in findings) == 1


def test_hand_written_price_sort_mutation_is_rejected():
    script = "BIDS=$(jq 'map(select(.ok))' bids.json)"
    target = "map(select(.ok))"
    replacement = "sort_by(.bid.price.amount)"
    assert script.count(target) == 1
    document = _lease_spender(script.replace(target, replacement))
    assert any("price ranking" in f for f in _selection_findings(document))


def test_min_price_shape_is_also_rejected():
    document = _lease_spender("winner = min(eligible, key=lambda bid: bid.price)")
    assert any("price ranking" in f for f in _selection_findings(document))


def test_detection_population_is_nonempty_and_every_case_fires():
    mutations = {
        "missing-provider-select": lambda d: d["jobs"]["pool"]["with"].pop(
            "provider-select"
        ),
        "old-pin": lambda d: d["jobs"]["pool"].update(
            {"uses": standard.POOL + OLD_REF}
        ),
    }
    assert mutations, "the reusable-runner mutation population is empty"
    for name, mutate in mutations.items():
        document = _runner_pool()
        mutate(document)
        assert _selection_findings(document), f"{name} survived without a finding"


def test_capability_stamp_fixture_has_no_dead_entry():
    exercised = {
        _ref
        for _ref in CAPABLE
        if not _selection_findings(_runner_pool())
    }
    assert exercised == set(CAPABLE), "a stamped test ref is not exercised by a positive"


def test_removing_the_check_call_site_makes_the_missing_select_mutation_survive(tmp_path):
    source_path = Path(standard.__file__)
    source = source_path.read_text()
    target = (
        "    findings.extend(_placement_selection_findings(document, pools, "
        "placement_inventory))\n"
    )
    assert source.count(target) == 1
    mutated_path = tmp_path / "mutated_check_standard.py"
    mutated_path.write_text(source.replace(target, "", 1))
    spec = importlib.util.spec_from_file_location("mutated_check_standard", mutated_path)
    assert spec and spec.loader
    mutated = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mutated)

    document = _runner_pool()
    document["jobs"]["pool"]["with"].pop("provider-select")
    findings = mutated.check(document, placement_implementations=CAPABLE)
    assert not any("provider-select" in finding for finding in findings), (
        "mutation probe is stale: removing the wiring no longer bypasses the rule"
    )


def test_bypassing_the_capability_lookup_makes_the_old_pin_mutation_survive(tmp_path):
    source = Path(standard.__file__).read_text()
    target = "        capabilities = implementation_inventory.get(pool_ref, frozenset())\n"
    replacement = "        capabilities = PLACEMENT_REQUIRED_CAPABILITIES\n"
    assert source.count(target) == 1
    mutated_path = tmp_path / "stamp_bypass.py"
    mutated_path.write_text(source.replace(target, replacement, 1))
    spec = importlib.util.spec_from_file_location("stamp_bypass", mutated_path)
    assert spec and spec.loader
    mutated = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mutated)

    document = _runner_pool()
    document["jobs"]["pool"]["uses"] = standard.POOL + OLD_REF
    document["jobs"]["pool"]["with"]["just-akash-ref"] = OLD_REF
    findings = mutated.check(document, placement_implementations=CAPABLE)
    assert not any("request-aware per-node placement" in finding for finding in findings), (
        "mutation probe is stale: bypassing the stamp no longer admits an old pin"
    )


def test_production_stamp_has_no_dead_or_falsely_capable_entry():
    assert standard.PLACEMENT_IMPLEMENTATIONS, "stamp inventory disappeared"
    assert set(standard.PLACEMENT_IMPLEMENTATIONS) == {
        "ebf2e37ac786ad1b7a0643625cbe0626131707fa"
    }, "an implementation stamp was added without a corresponding exercised audit case"
    assert all(
        capabilities <= standard.PLACEMENT_REQUIRED_CAPABILITIES
        for capabilities in standard.PLACEMENT_IMPLEMENTATIONS.values()
    )
    assert not any(
        standard.PLACEMENT_REQUIRED_CAPABILITIES <= capabilities
        for capabilities in standard.PLACEMENT_IMPLEMENTATIONS.values()
    ), "an implementation was marked eligible before core#48 and just-akash#346 released"
