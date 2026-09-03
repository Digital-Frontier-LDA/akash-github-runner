"""Tests for `check_schedule_inputs_are_empty`.

The known-bad is the REAL expression, copied from Blazing-Back's
`cleanup-stale-akash.yml` as it stood on 2026-08-24, not a synthetic one. A rule that
can only demonstrate itself against a fixture invented for it has not been shown to
catch anything that actually happened.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "check_schedule_inputs_are_empty",
    Path(__file__).resolve().parent / "check_schedule_inputs_are_empty.py",
)
chk = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(chk)


# The real defect, verbatim.
KNOWN_BAD = """\
name: Cleanup Stale Akash CI Runners
on:
  schedule:
    - cron: '0 */6 * * *'
  workflow_dispatch:
    inputs:
      dry_run:
        description: 'Dry run (list but do not close)'
jobs:
  close:
    runs-on: ubuntu-latest
    steps:
      - name: Close orphaned CI runner deployments
        env:
          DRY_RUN: ${{ github.event.inputs.dry_run || 'false' }}
        run: python3 scripts/ci_cleanup_runner_deployments.py
"""

# The real fix, verbatim.
KNOWN_GOOD = KNOWN_BAD.replace(
    "DRY_RUN: ${{ github.event.inputs.dry_run || 'false' }}",
    "DRY_RUN: ${{ github.event_name == 'schedule' && 'true' "
    "|| (github.event.inputs.dry_run || 'false') }}",
)

NO_SCHEDULE = KNOWN_BAD.replace("  schedule:\n    - cron: '0 */6 * * *'\n", "")


def _write(tmp_path: Path, body: str, name: str = "w.yml") -> Path:
    d = tmp_path / ".github" / "workflows"
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_text(body)
    return p


def test_the_real_defect_is_caught(tmp_path):
    """KNOWN-BAD. Without this the rule is satisfiable by never flagging anything."""
    hits = chk.check_workflow(_write(tmp_path, KNOWN_BAD))
    assert hits, "The rule did not catch the expression it was written for."
    assert "dry_run" in hits[0]


def test_the_real_fix_passes(tmp_path):
    """KNOWN-GOOD. Without this the rule is satisfiable by flagging everything, which
    would make it noise and get it disabled."""
    assert chk.check_workflow(_write(tmp_path, KNOWN_GOOD)) == []


def test_a_workflow_with_no_cron_is_out_of_scope(tmp_path):
    """Scope. A dispatch-only workflow cannot exhibit this — `inputs` are supplied."""
    assert chk.check_workflow(_write(tmp_path, NO_SCHEDULE)) == []


def test_a_bare_on_key_still_yields_triggers():
    """⚠ YAML parses an unquoted `on:` as the BOOLEAN True, not the string 'on'.

    A workflow-parsing rule that reads `wf.get("on")` alone finds nothing on EVERY real
    workflow, reports zero scheduled files, and passes vacuously on the entire repo it
    was written for. This is the single most common way a rule of this shape is born
    dead, so it is asserted rather than assumed.
    """
    assert chk._triggers({True: {"schedule": [{"cron": "0 * * * *"}]}}) == {"schedule"}
    assert chk._triggers({"on": {"schedule": []}}) == {"schedule"}


def test_the_modern_inputs_context_is_also_caught(tmp_path):
    """`inputs.X` (without the `github.event.` prefix) is empty under schedule too."""
    body = KNOWN_BAD.replace("github.event.inputs.dry_run", "inputs.dry_run")
    assert chk.check_workflow(_write(tmp_path, body))


@pytest.mark.parametrize("expr", ["github.event_name == 'schedule'", "github.event_name == 'workflow_dispatch'"])
def test_an_event_name_discriminator_satisfies_the_rule(expr, tmp_path):
    body = KNOWN_BAD.replace(
        "${{ github.event.inputs.dry_run || 'false' }}",
        "${{ " + expr + " && 'true' || github.event.inputs.dry_run }}",
    )
    assert chk.check_workflow(_write(tmp_path, body)) == []


def test_main_returns_nonzero_on_the_known_bad(tmp_path):
    """The exit code is what a CI gate reads — assert it, not just the finding list."""
    _write(tmp_path, KNOWN_BAD)
    assert chk.main(["--workflows-dir", str(tmp_path / ".github" / "workflows")]) == 1


def test_main_returns_zero_on_the_known_good(tmp_path):
    _write(tmp_path, KNOWN_GOOD)
    assert chk.main(["--workflows-dir", str(tmp_path / ".github" / "workflows")]) == 0


def test_a_missing_directory_is_not_a_silent_pass(capsys, tmp_path):
    """rc=0 on an absent dir is deliberate (a consumer may have no workflows), but it
    must SAY so — an unqualified 0 is indistinguishable from 'checked, all clean'."""
    assert chk.main(["--workflows-dir", str(tmp_path / "nope")]) == 0
    assert "not a directory" in capsys.readouterr().out


# ── forms that DO discriminate, and were reported as if they did not ─────────

@pytest.mark.parametrize(
    "expr",
    [
        # The reference implementation's own guard. Measured 2026-09-03 in
        # Borduas-Holdings/Blazing-Back's escrow-reaper.yml, the caller this repo ships
        # as the example for reusable-akash-escrow-reaper.yml.
        "execute: ${{ inputs.execute == true }}",
        "execute: ${{ inputs.execute == 'true' }}",
        # The same question as the accepted `==` form, asked the other way round.
        "dry-run: ${{ github.event_name != 'schedule' && inputs.dry-run }}",
    ],
)
def test_a_comparison_is_not_a_fall_through(expr):
    """No `||` anywhere in these. A schedule supplies nothing, so `null == true` is FALSE
    on every cron firing — the safe value, reached by comparison rather than by a default
    nobody passed. Reporting it teaches the fleet's most-copied caller that the rule does
    not understand the shape it recommends by example."""
    assert chk.offending_expressions(expr) == []


@pytest.mark.parametrize(
    "expr",
    [
        # ⛔ THE ASYMMETRY IS THE POINT. An absent input can never equal `true`; it very
        # easily equals `false`, and THAT yields true under a schedule — the silent
        # destructive default this rule exists to catch.
        "destroy: ${{ inputs.destroy == false }}",
        # A comparison must not launder a fall-through sharing the line.
        "x: ${{ (inputs.a == true) || inputs.b }}",
        "DRY_RUN: ${{ inputs.dry_run || 'false' }}",
    ],
)
def test_the_comparison_allowance_does_not_open_a_hole(expr):
    assert chk.offending_expressions(expr) != []
