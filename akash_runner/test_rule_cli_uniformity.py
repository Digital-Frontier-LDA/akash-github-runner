"""Every rule accepts the ONE canonical flag for its input scope; every legacy spelling lives.

⛔ WHY (agr#30). The agreement test (`test_rule_cli_agrees_with_its_call_site.py`) asserts
that the flags the ACTION passes are flags the rule accepts — it is deliberately agnostic
about the five conventions the rules themselves grew. This test is the uniformity half: a
rule wired into a NEW call site with the canonical spelling must ACCEPT it, whatever
convention that rule was born with, because a wrong spelling does not fail loudly — argparse
exits 2, the `advisory` wrapper swallows non-zero, and the job goes green having judged
nothing.

CANONICAL SPELLINGS (one per input scope):

| scope | canonical | legacy alias kept |
|---|---|---|
| directory of workflows | `--workflows-dir <dir>` | positional `<dir>` |
| one workflow file | `--workflow-file <file>` | positional `<file>` |
| targets (files or dir) | `--targets <t>...` | positional `<t>...` |
| repo roots | `--repos <r>...` | positional `<r>...` |

⚠ `--workflow-file` is DELIBERATELY not `--workflows-dir`-with-fallback: a caller assuming
the dir convention must get a loud unknown-flag error here, not a directory silently globbed
as if it were a file.

⚠ OLD PINS ARE A CONTRACT. agr is public and consumed cross-org at pinned SHAs, so the
legacy positional forms must keep working FOREVER, not just this week — the alias tests
below invoke every legacy-shaped rule positionally and require acceptance (no exit 2).

Non-vacuity: the rule populations are FLOORED on the counts measured at authoring (11 dir /
3 file / 4 multi). A drop means the classification below drifted from reality, not that the
suite shrank — re-derive the sets, do not lower the floor.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RULES = ROOT / "akash_runner"

# The classification, measured on this tree at authoring. Dir-scoped = accepts --workflows-dir.
DIR_RULES = [
    "check_backstop_covers_producers.py",
    "check_context_properties_exist.py",
    "check_dereg_backstop.py",
    "check_funding_projection_is_quantised.py",
    "check_pool_not_before_consumers.py",
    "check_reaper_schedule.py",
    "check_runner_image_digest_floor.py",
    "check_schedule_inputs_are_empty.py",
    "check_teardown_cannot_be_silenced.py",
    "check_test_pins_a_literal.py",
    "check_unvalidated_default.py",
]
FILE_RULES = [
    "check_pool_owns_teardown.py",
    "check_standard.py",
    "check_teardown_can_identify.py",
]
MULTI_RULES = [  # canonical --targets / --repos
    "check_conformance_pin_agrees_with_checker_ref.py",
    "check_funding_gate_is_not_re_derived.py",
    "check_gate_is_not_re_derived.py",
    "check_sibling_prefix_collisions.py",
]

_UNRECOGNISED = "unrecognized arguments"


def _run(rule: str, *argv: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(RULES / rule), *argv],
        capture_output=True,
        text=True,
        timeout=120,
    )


@pytest.fixture(scope="module")
def workflows_dir(tmp_path_factory):
    d = tmp_path_factory.mktemp("workflows")
    (d / "noop.yml").write_text("name: noop\non: [push]\njobs:\n  a:\n    runs-on: ubuntu-latest\n    steps: [{run: echo hi}]\n")
    return d


def test_the_classification_is_not_decorative():
    """Floors on the measured populations; a drop means drift, not shrinkage."""
    assert len(DIR_RULES) >= 11, "dir-scoped rule count dropped below the measured 11"
    assert len(FILE_RULES) >= 3, "file-scoped rule count dropped below the measured 3"
    assert len(MULTI_RULES) >= 4, "multi-value rule count dropped below the measured 4"
    for rule in [*DIR_RULES, *FILE_RULES, *MULTI_RULES]:
        assert (RULES / rule).is_file(), f"{rule} classified here but absent — re-derive"


@pytest.mark.parametrize("rule", DIR_RULES)
def test_every_dir_rule_accepts_workflows_dir(rule, workflows_dir):
    """Exit 2 + 'unrecognized arguments' is the silent-green shape this suite exists to kill."""
    r = _run(rule, "--workflows-dir", str(workflows_dir))
    assert _UNRECOGNISED not in r.stderr, (
        f"{rule} rejects --workflows-dir — the canonical dir spelling. A call site wired with "
        "it goes green having judged nothing (argparse exit 2, advisory swallows non-zero)."
    )


POSITIONAL_BORN_DIR_RULES = [  # the three born with a positional directory — the alias contract
    "check_backstop_covers_producers.py",
    "check_dereg_backstop.py",
    "check_reaper_schedule.py",
]


@pytest.mark.parametrize("rule", POSITIONAL_BORN_DIR_RULES)
def test_positional_born_dir_rules_still_accept_the_positional(rule, workflows_dir):
    r = _run(rule, str(workflows_dir))
    assert _UNRECOGNISED not in r.stderr and r.returncode != 2, (
        f"{rule} was born with a positional directory; a pinned old call site uses it. "
        "The canonical flag is an ADDITION — aliases are a contract, not a cleanup."
    )


@pytest.mark.parametrize("rule", FILE_RULES)
def test_every_file_rule_accepts_workflow_file(rule, workflows_dir):
    f = workflows_dir / "noop.yml"
    r = _run(rule, "--workflow-file", str(f))
    assert _UNRECOGNISED not in r.stderr, (
        f"{rule} rejects --workflow-file — the canonical single-file spelling. It must be "
        "distinct from --workflows-dir: a dir-convention caller passing a directory here must "
        "get a loud failure, not a directory treated as a file."
    )


@pytest.mark.parametrize("rule", FILE_RULES)
def test_file_rules_still_accept_the_positional(rule, workflows_dir):
    r = _run(rule, str(workflows_dir / "noop.yml"))
    assert _UNRECOGNISED not in r.stderr and r.returncode != 2


@pytest.mark.parametrize(
    "rule,flag",
    [
        *[(r, "--targets") for r in MULTI_RULES if not r.endswith("collisions.py")],
        ("check_sibling_prefix_collisions.py", "--repos"),
    ],
)
def test_multi_rules_accept_their_flag(rule, flag, workflows_dir):
    r = _run(rule, flag, str(workflows_dir))
    assert _UNRECOGNISED not in r.stderr, f"{rule} rejects {flag} — the canonical multi spelling"


@pytest.mark.parametrize(
    "rule",
    [r for r in MULTI_RULES if not r.endswith("collisions.py")],
)
def test_multi_rules_still_accept_the_positional(rule, workflows_dir):
    r = _run(rule, str(workflows_dir))
    assert _UNRECOGNISED not in r.stderr and r.returncode != 2


def test_neither_flag_nor_positional_is_loud(workflows_dir):
    """A required input that became optional for aliasing must fail explicitly, not None-die."""
    r = _run("check_dereg_backstop.py")
    assert r.returncode == 2 and "required" in r.stderr, (
        "bare invocation must argparse-error loudly; proceeding with None would die deep in "
        "the rule wearing a defect costume"
    )


def test_flag_beats_positional_when_both_given(workflows_dir):
    """Documented determinism: both forms given → the canonical flag wins (optionals apply last)."""
    import argparse

    sys.path.insert(0, str(RULES))
    ca = __import__("cli_aliases")
    ap = argparse.ArgumentParser()
    ca.add_workflows_dir(ap)
    ns = ap.parse_args(["legacy", "--workflows-dir", "canonical"])
    assert str(ns.workflows) == "canonical"
    ns2 = ap.parse_args(["legacy-only"])
    assert str(ns2.workflows) == "legacy-only"
