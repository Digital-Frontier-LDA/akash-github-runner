"""Controls for the backstop-reaper schedule rule.

Fixtures are the REAL just-akash workflows as they stand on origin/main 2026-08-23, not
invented shapes — the known-good and the known-bad live in the same repo on the same ref:

    cleanup-stale.yml   cron "23 0,6,12,18 * * *"  (added by just-akash #183)  PASSES
    close-orphans.yml   dispatch-only, deliberately                            EXEMPT
    runner-teardown.yml workflow_call                                          OUT OF SCOPE
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from akash_runner.check_reaper_schedule import (  # noqa: E402
    EXEMPT,
    check_directory,
    check_workflow,
)

SCHEDULED = """
name: cleanup stale
on:
  schedule:
    - cron: "23 0,6,12,18 * * *"
  workflow_dispatch:
jobs:
  sweep: {runs-on: ubuntu-latest}
"""

DISPATCH_ONLY = """
name: close orphans
on:
  workflow_dispatch:
    inputs:
      dseqs:
        description: "Deployment(s) to close. Required."
        type: string
        required: true
      execute:
        type: boolean
        default: false
jobs:
  close: {runs-on: ubuntu-latest}
"""

REUSABLE = """
name: runner teardown
on:
  workflow_call:
    inputs:
      dseq: {type: string, required: true}
jobs:
  teardown: {runs-on: ubuntu-latest}
"""


def _check(filename: str, text: str) -> list[str]:
    return check_workflow(Path(filename), yaml.safe_load(text) or {})


# ── known-good / known-bad, both real ────────────────────────────────────────────────


def test_known_good_a_scheduled_reaper_passes():
    assert _check("cleanup-stale.yml", SCHEDULED) == []


def test_known_bad_the_same_reaper_before_183_fails():
    """★ cleanup-stale.yml as it stood BEFORE just-akash #183 — the actual defect."""
    unscheduled = SCHEDULED.replace(
        '  schedule:\n    - cron: "23 0,6,12,18 * * *"\n', ""
    )
    findings = _check("cleanup-stale.yml", unscheduled)
    assert findings and "declares no schedule and no exemption" in findings[0]


def test_a_per_run_teardown_is_out_of_scope_not_exempt():
    """★★ CATEGORY ERROR GUARD. `runner-teardown.yml` runs when its caller runs; demanding
    a cron of it is meaningless. It must be OUT OF SCOPE, not silently exempted — an
    exemption would imply it ought to be scheduled one day."""
    assert _check("runner-teardown.yml", REUSABLE) == []
    assert "runner-teardown.yml" not in EXEMPT


def test_a_non_reaper_workflow_is_ignored():
    """★ KNOWN-NEGATIVE for the name selector: this rule demands a cron, so a false
    positive is a demand to schedule something that must not be."""
    assert _check("ci.yml", DISPATCH_ONLY.replace("close orphans", "ci")) == []


# ── the exemption, and its expiry ────────────────────────────────────────────────────


def test_close_orphans_is_exempt_while_its_reason_holds():
    assert _check("close-orphans.yml", DISPATCH_ONLY) == []


def test_the_exemption_EXPIRES_when_a_safe_default_appears():
    """★★ THE FALSIFIABILITY PROPERTY. The exemption says a cron cannot supply `dseqs`
    safely because it is required with no default. Give it a default and that reason stops
    being true — so the exemption must stop holding, WITHOUT anyone remembering to revisit
    it. An exemption nobody re-examines is permanent by default."""
    with_default = DISPATCH_ONLY.replace(
        "        type: string\n        required: true\n",
        '        type: string\n        required: true\n        default: ""\n',
    )
    findings = _check("close-orphans.yml", with_default)
    assert findings and "the exemption has expired" in findings[0]


def test_the_exemption_EXPIRES_when_the_input_it_cites_is_removed():
    """★ The other way the justification can rot: the cited input simply goes away."""
    renamed = DISPATCH_ONLY.replace("      dseqs:", "      targets:")
    findings = _check("close-orphans.yml", renamed)
    assert findings and "no longer exists" in findings[0]


def test_the_exemption_EXPIRES_when_required_is_dropped():
    not_required = DISPATCH_ONLY.replace("        required: true\n", "")
    findings = _check("close-orphans.yml", not_required)
    assert findings and "the exemption has expired" in findings[0]


def test_every_exemption_states_a_reason_and_a_checkable_predicate():
    for filename, exemption in EXEMPT.items():
        assert len(exemption.reason.strip()) >= 40, (
            f"{filename}: reason is not substantive"
        )
        assert exemption.required_input_without_default, (
            f"{filename}: no checkable predicate"
        )


# ── traps ────────────────────────────────────────────────────────────────────────────


def test_the_yaml_boolean_on_key_is_handled():
    """★★ YAML 1.1 parses a bare `on:` as the BOOLEAN True, not the string "on". A checker
    reading document["on"] finds nothing, concludes the workflow has no triggers, and this
    rule fires on everything — or, with the opposite default, on nothing."""
    document = yaml.safe_load(SCHEDULED)
    assert True in document or "on" in document
    assert _check("cleanup-stale.yml", SCHEDULED) == []


def test_an_unreadable_workflow_is_reported_not_skipped(tmp_path):
    """★★ Unreadable is not clean. A parse failure returning no findings makes a broken
    workflow indistinguishable from a compliant one."""
    (tmp_path / "cleanup-broken.yml").write_text("this: [is: not: valid")
    findings = check_directory(tmp_path)
    assert findings and "was NOT checked" in findings[0]


def test_directory_scan_finds_the_unscheduled_one_among_several(tmp_path):
    (tmp_path / "cleanup-stale.yml").write_text(SCHEDULED)
    (tmp_path / "close-orphans.yml").write_text(DISPATCH_ONLY)
    (tmp_path / "runner-teardown.yml").write_text(REUSABLE)
    assert check_directory(tmp_path) == []
    (tmp_path / "sweep-leases.yml").write_text(
        REUSABLE.replace("workflow_call", "workflow_dispatch")
    )
    findings = check_directory(tmp_path)
    assert len(findings) == 1 and "sweep-leases.yml" in findings[0]


@pytest.mark.parametrize(
    "filename,in_scope",
    [
        ("close-orphans.yml", True),  # ⛔ was MISSED: "orphan" + "s" is not a boundary
        ("cleanup-stale.yml", True),
        ("sweep-leases.yml", True),
        ("reap-runners.yml", True),
        ("prune-images.yml", True),
        ("runner-teardown.yml", False),
        ("ci.yml", False),
        ("provider-canary.yml", False),
    ],
)
def test_the_selector_matches_the_real_filenames(filename, in_scope):
    """★★ THE CONTROL THAT CAUGHT A FALSE PASS IN THIS FILE.

    `test_close_orphans_is_exempt_while_its_reason_holds` passed while the selector did
    not match `close-orphans.yml` at all — so it asserted nothing about the exemption, and
    all three expiry tests returned [] because the file was never in scope.

    A selector is a population definition. Asserting behaviour without asserting the
    population is how a rule ships covering nothing."""
    from akash_runner.check_reaper_schedule import REAPER_NAME

    assert bool(REAPER_NAME.search(filename)) is in_scope
