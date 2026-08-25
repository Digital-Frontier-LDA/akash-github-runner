"""Controls for `check_test_pins_a_literal`.

Every case is built from a regression that ACTUALLY happened, not invented:

* KNOWN-POSITIVE (the defect shape) — df-cicd
  `akash_runner/test_reusable_conformance_workflow.py:58` (verbatim, PRE-FIX
  shape — what the bug actually was before #149)::
    assert any(u == "./.github/actions/akash-runner-conformance" for u in local), (
        "reusable workflow must invoke the akash-runner-conformance action by a local "
        f"path (found uses: {step_uses})"
    )
  The pre-fix assertion body pinned the literal `./.github/actions/...` while
  the message named a property ("must invoke … by a local path"). The
  post-fix (`not any(...)` + `endswith`) flipped the comparison — that is
  WHY the post-fix shape must NOT fire (it is the FIX). (#149)

* KNOWN-POSITIVE (second shape, repro from verbatim) — just-akash
  `tests/test_runner_pool_workflow.py:339` (was, pre-#184)::
    assert "job.workflow_sha" in ref, (
        f"{label}: ref={ref!r} — a floating ref breaks the guarantee a pin exists for"
    )
  The literal `job.workflow_sha` is a context-property that resolves to "" —
  pinning it as the assertion target made the test green on every pool that
  failed the real check (#184). The message names a PROPERTY ("the guarantee
  a pin exists for"). When the fix used `github.workflow_sha`, the literal
  stopped appearing and the assertion went red.

* KNOWN-POSITIVE (second shape, repro from verbatim) — just-akash
  `tests/test_runner_pool_workflow.py:339` (was, pre-#184)::
    assert "job.workflow_sha" in ref, (
        f"{label}: ref={ref!r} — a floating ref breaks the guarantee a pin exists for"
    )
  The literal `job.workflow_sha` is a context-property that resolves to "" —
  pinning it as the assertion target made the test green on every pool that
  failed the real check (#184). The message names a PROPERTY ("the guarantee
  a pin exists for"). When the fix used `github.workflow_sha`, the literal
  stopped appearing and the assertion went red.

* KNOWN-NEGATIVE (fixture-style, must NOT flag) — a test that asserts on a
  fixed fixture path. The message names the literal it is asserting on. The
  rule's `_names_literal` heuristic deliberately skips this case so the rule
  fires only on defect-pin shape, not on every fixture assertion.

* KNOWN-NEGATIVE (no-property message) — an assertion whose body pins a
  literal but whose message is a bare diagnostic ("x is foo, expected bar").
  No property is named — the test is asserting an exact value, not pinning
  a defect shape.

The rule's scope is documented in the rule module's docstring. Severity is
`advisory` from the start — the PROMOTE WHEN lives in the rule, not the
controls. A rule that fires at `required` on a five-line idiom nobody has
hit gets disabled in a week.
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import akash_runner.check_test_pins_a_literal as tp  # noqa: E402


# ── Helpers ───────────────────────────────────────────────────────────────────


def _write_test(repo: Path, body: str) -> Path:
    """Write a test file into the workflows dir. The rule's design point is that
    a test lives NEXT TO a workflow; for synthetic fixtures we drop the test
    file inside workflows-dir and pair it with a stub workflow."""
    wf_dir = repo / ".github" / "workflows"
    wf_dir.mkdir(parents=True, exist_ok=True)
    # Stub workflow so the dir has at least one YAML — the rule's CLI globs
    # `*.yml` / `*.yaml`, but `check_file()` is path-agnostic and accepts any
    # file. We call `check_file` directly in the tests so the stub is
    # unnecessary; we keep it for visual realism.
    (wf_dir / "ci.yml").write_text("name: ci\non: workflow_dispatch\n")
    p = wf_dir / "test_reusable_conformance_workflow.py"
    p.write_text(body)
    return p


# ── Known-positive (the defect) ───────────────────────────────────────────────


def test_known_positive_caller_relative_uses_literal_with_property_docstring():
    """Reproduces the PRE-FIX shape of df-cicd #149 — what the bug actually was
    before the `not any(...)` fix landed. The assertion body pins a literal
    `./.github/actions/...` while the enclosing function's docstring names
    the property the test is supposed to enforce. The rule must flag this."""
    body = '''"""Docstring says: the workflow must invoke the conformance action
from a checkout it CONTROLS, never a bare caller-relative path."""
from pathlib import Path

def test_uses_local_action():
    local = []
    assert any(u == "./.github/actions/akash-runner-conformance" for u in local), (
        "a bare `./.github/actions/...` resolves inside the CALLER's tree"
    )
'''
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        # Rule consumes a Python test file. Place under .github/workflows
        # so the action's --workflows-dir sees it.
        wf_dir = td_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        # Stub YAML so the dir is not empty (matches the action's contract).
        (wf_dir / "ci.yml").write_text("name: ci\non: workflow_dispatch\n")
        test_file = wf_dir / "test_x.py"
        test_file.write_text(body)
        findings = tp.check_workflow(test_file)
    assert findings, "expected a finding for body-literal + property docstring"
    kind, line, what = findings[0]
    assert kind == "uses-literal", findings
    assert "./.github/actions/akash-runner-conformance" in what, findings


def test_known_positive_context_property_literal_with_property_message():
    """Reproduces just-akash #184 — the assertion body pins a context
    property (`job.workflow_sha`) while the message names a property
    ("a floating ref breaks the guarantee a pin exists for")."""
    body = '''def test_pool_workflow_is_pinned():
    """The CLI source must be pinned to the ref the caller pinned."""
    ref = "job.workflow_sha"
    assert "job.workflow_sha" in ref, (
        f"label: ref={ref!r} — a floating ref breaks the guarantee a pin exists for"
    )
'''
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        wf_dir = td_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "ci.yml").write_text("name: ci\non: workflow_dispatch\n")
        test_file = wf_dir / "test_x.py"
        test_file.write_text(body)
        findings = tp.check_workflow(test_file)
    assert findings, "expected a finding for body-literal + property message"
    kind, line, what = findings[0]
    assert kind == "context-property", findings
    assert "job.workflow_sha" in what, findings


# ── Known-negatives (these MUST NOT flag) ─────────────────────────────────────


def test_fixture_style_assertion_is_not_flagged():
    """A test asserts a fixture path. The message names the literal the test
    is checking — `_names_literal` recognises this and the rule does not fire.
    Flagging fixture assertions would train readers to ignore the rule."""
    body = '''def test_workflow_refs_local_action():
    workflow = "./.github/actions/foo"
    assert workflow == "./.github/actions/foo", (
        f"the workflow must reference {workflow!r} exactly"
    )
'''
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        wf_dir = td_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "ci.yml").write_text("name: ci\non: workflow_dispatch\n")
        test_file = wf_dir / "test_x.py"
        test_file.write_text(body)
        findings = tp.check_workflow(test_file)
    assert findings == [], (
        "fixture-style assertions (body AND message both name the literal) "
        "must not be flagged; findings: " + repr(findings)
    )


def test_negated_assertion_is_not_flagged():
    """The POST-FIX shape of df-cicd #149 — `assert not any(...)` is the FIX
    that landed to remove the literal pin. The rule MUST NOT fire on this;
    flagging the fix tells the reader to reintroduce the bug. (#166 HOLD,
    NEGATION BLINDNESS)"""
    body = '''"""The workflow must invoke the conformance action from a checkout
it CONTROLS, never a bare caller-relative path."""
from pathlib import Path

def test_no_caller_relative_uses():
    local = ["./.github/actions/akash-runner-conformance"]
    assert not any(u == "./.github/actions/akash-runner-conformance" for u in local), (
        "a bare `./.github/actions/...` resolves inside the CALLER's tree"
    )
'''
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        wf_dir = td_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "ci.yml").write_text("name: ci\non: workflow_dispatch\n")
        test_file = wf_dir / "test_x.py"
        test_file.write_text(body)
        findings = tp.check_workflow(test_file)
    assert findings == [], (
        "the negated assertion IS the fix (#149); flagging it tells the reader "
        "to reintroduce the bug. Findings: " + repr(findings)
    )


def test_expected_value_set_comparison_is_not_flagged():
    """An assertion that compares a function's RETURN VALUE against an
    expected set — `assert props == {"literal", ...}` — is asserting the
    function processed the fixture correctly. The literal is the EXPECTED
    output, not a pinned defect shape. Flagging it makes the test vacuous
    (the expected set is what the test checks against; removing the literal
    makes any function output pass). (#166 HOLD, EXPECTED-VALUE BLINDNESS.)"""
    body = '''def test_check_context_properties_exist_for_known_shape():
    """The rule must detect a set of broken-context-property cases."""
    text = "${{ !runner.osx }}"
    props = {prop for prop, _ in __import__("akash_runner.check_context_properties_exist", fromlist=["offending_expressions"]).offending_expressions(text)}
    assert props == {"runner.osx", "job.statusx"}
'''
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        wf_dir = td_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "ci.yml").write_text("name: ci\non: workflow_dispatch\n")
        test_file = wf_dir / "test_x.py"
        test_file.write_text(body)
        findings = tp.check_workflow(test_file)
    assert findings == [], (
        "expected-value comparisons (literal in Set/Dict on RHS of ==/!=) "
        "must not be flagged; findings: " + repr(findings)
    )


def test_intent_marker_in_docstring_skips_finding():
    """A control test whose docstring declares it as a known-positive
    reproduction of a regression MUST pin the literal — flagging it inverts
    the conformance-suite incentive. The allowlist-by-INTENT discriminator
    fires on docstring phrases like "known-positive", "known-negative",
    "verbatim", "control", "fixture", "reproduction of a regression".
    (#166 HOLD, FIXTURE BLINDNESS)"""
    body = '''"""Known-positive control for `check_test_pins_a_literal` — a
verbatim reproduction of just-akash #184. The literal `job.workflow_sha`
MUST be hard-coded; hard-coding is what makes the control non-vacuous."""
from pathlib import Path

def test_job_workflow_sha_is_a_pin():
    ref = "job.workflow_sha"
    assert "job.workflow_sha" in ref, (
        "a floating ref breaks the guarantee a pin exists for"
    )
'''
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        wf_dir = td_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "ci.yml").write_text("name: ci\non: workflow_dispatch\n")
        test_file = wf_dir / "test_x.py"
        test_file.write_text(body)
        findings = tp.check_workflow(test_file)
    assert findings == [], (
        "control tests whose docstring declares them as a known-positive "
        "reproduction must not be flagged; findings: " + repr(findings)
    )


def test_bare_diagnostic_message_is_not_flagged():
    """An assertion body pins a literal but the message is a bare diagnostic
    ("x is foo, expected bar"). No property is named — the test is asserting
    an exact value, not pinning a defect shape. The rule must not fire."""
    body = '''def test_returns_expected_value():
    result = "github.workflow_sha"
    assert result == "github.workflow_sha", (
        f"got {result!r}"
    )
'''
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        wf_dir = td_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "ci.yml").write_text("name: ci\non: workflow_dispatch\n")
        test_file = wf_dir / "test_x.py"
        test_file.write_text(body)
        findings = tp.check_workflow(test_file)
    assert findings == [], (
        "assertions whose message is a bare diagnostic (no property words) "
        "must not be flagged; findings: " + repr(findings)
    )


def test_assertion_without_literal_signal_is_not_flagged():
    """An assertion whose body has no `uses:` literal, no `${{ }}`, and no
    context-property is out of scope — there is no literal to pin. The
    rule's first gate (`any(signals.values())`) prevents firing."""
    body = '''def test_arithmetic_works():
    assert 1 + 1 == 2, "arithmetic must hold"
'''
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        wf_dir = td_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "ci.yml").write_text("name: ci\non: workflow_dispatch\n")
        test_file = wf_dir / "test_x.py"
        test_file.write_text(body)
        findings = tp.check_workflow(test_file)
    assert findings == [], findings


def test_control_plane_name_does_not_exempt_finding():
    """⛔ Permanent control for OVER-SUPPRESSION. The function NAME must NOT
    exempt a finding. `test_control_plane_*` is a pervasive prefix in this
    org (control-plane/api/…, tests/control_plane/…, test_control_plane_*)
    and a substring matcher on `control` would silently exempt an entire
    live namespace — false POSITIVES are LOUD (someone pushes back), false
    NEGATIVES are SILENT (nothing ever fires). Trading loud for quiet in one
    namespace is the worst failure mode for a rule whose purpose is catching
    tests that LOOK FINE.

    Two IDENTICAL defect bodies, differing only in name, BOTH must fire.
    Without this test the next person re-widens the matcher and nothing
    notices until a real consumer slips a defect through. (#166 rework,
    OVER-SUPPRESSION.)"""
    body_template = '''def {name}():
    """The CLI source must be pinned to the ref the caller pinned."""
    ref = "job.workflow_sha"
    assert "job.workflow_sha" in ref, (
        f"a floating ref breaks the guarantee a pin exists for"
    )
'''
    for name in (
        "test_the_workflow_pins_its_ref",
        "test_control_plane_pins_its_ref",
    ):
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            wf_dir = td_path / ".github" / "workflows"
            wf_dir.mkdir(parents=True)
            (wf_dir / "ci.yml").write_text("name: ci\non: workflow_dispatch\n")
            test_file = wf_dir / "test_x.py"
            test_file.write_text(body_template.format(name=name))
            findings = tp.check_workflow(test_file)
        assert findings, (
            f"expected a finding for {name!r} (same defect body, "
            f"control_plane prefix must not exempt it); got {findings!r}"
        )
        kind, line, what = findings[0]
        assert kind == "context-property", findings
        assert "job.workflow_sha" in what, findings


# ── Population pins ───────────────────────────────────────────────────────────


def test_unparseable_file_is_na_not_crash():
    """A file that fails to parse returns [] rather than raising. A rule that
    crashes on SyntaxError takes down the whole conformance action."""
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        wf_dir = td_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "ci.yml").write_text("name: ci\non: workflow_dispatch\n")
        bad = wf_dir / "test_x.py"
        bad.write_text("def broken(:\n    pass\n")
        findings = tp.check_workflow(bad)
    assert findings == []


# ── CLI smoke ─────────────────────────────────────────────────────────────────


def test_cli_exits_zero_when_no_workflows():
    """The CLI prints a `::warning` and returns 0 when --workflows-dir is
    absent. Matches the sibling convention (check_schedule_inputs_are_empty,
    check_context_properties_exist). A rule that exits non-zero on a missing
    dir takes down the action's set -e guard."""
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        # No .github/workflows dir at all.
        rc = tp.main(["--workflows-dir", str(td_path / ".github" / "workflows")])
    assert rc == 0


# ── Severity pinning ──────────────────────────────────────────────────────────


def test_rule_emits_advisory_findings_never_required():
    """PROMOTE WHEN lives in the rule's docstring; the code emits findings
    whose kind/name is advisory-by-default. The CLI prints a `::warning` and
    does not raise. A rule that emits `required` from the start has no
    operator lever — it either blocks every repo with a test (noisy) or has
    to be turned off wholesale (silent)."""
    body = '''def test_pool_workflow_is_pinned():
    """The CLI source must be pinned to the ref the caller pinned."""
    ref = "job.workflow_sha"
    assert "job.workflow_sha" in ref, (
        f"label: a floating ref breaks the guarantee a pin exists for"
    )
'''
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        wf_dir = td_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "ci.yml").write_text("name: ci\non: workflow_dispatch\n")
        test_file = wf_dir / "test_x.py"
        test_file.write_text(body)
        findings = tp.check_workflow(test_file)
    assert findings, "control should produce a finding"
    # The kind tuple has no severity field; the CLI's `::warning` print is
    # the advisory signal. The contract lives in the docstring; the code does
    # not need to enforce severity for an advisory rule (see
    # check_unvalidated_default's #164 contract).