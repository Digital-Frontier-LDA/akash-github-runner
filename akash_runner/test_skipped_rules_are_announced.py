"""An absent `workflows-dir` must announce EVERY rule it skips, and not undercount.

⛔ MEASURED 2026-08-25 on the action as it stands. The `else` branch already announces —
that is not the gap. It announces the WRONG SET:

    ::notice title=2 repo-scoped rules were NOT run::check_dereg_backstop and
    check_reaper_schedule ...

while the `if` branch it mirrors gates TEN rules, THREE of them ENFORCING
(check_dereg_backstop, check_backstop_covers_producers, check_context_properties_exist).
So a consumer with no `workflows-dir` is told two advisory-sounding rules were skipped,
and is not told that three build-failing rules never ran. The job goes green.

★ THE NOTICE WAS CORRECT WHEN WRITTEN. It rotted because it is a hand-maintained prose
list of a set that lives ten lines above it: eight rules were added to the `if` and none
to the `else`. A count and a name list that a human must remember to update is the same
defect shape as a rule with no call site — right at merge, wrong by the next commit.

⇒ These tests do not pin the sentence. They pin the RELATIONSHIP: whatever set the `if`
runs, the `else` must name, and the severity must match the stakes. Adding rule eleven
without touching the announcement must fail here.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
ACTION = ROOT / ".github/actions/akash-runner-conformance/action.yml"

RULE = re.compile(r"check_[a-z_]+\.py")


def _script() -> str:
    document = yaml.safe_load(ACTION.read_text())
    steps = document["runs"]["steps"]
    bodies = [s["run"] for s in steps if "run" in s]
    assert len(bodies) == 1, "expected a single composite run block"
    return bodies[0]


def _guarded_block() -> tuple[str, str]:
    """The body of `if [ -n "$WORKFLOWS_DIR" ]` and the body of its `else`.

    ⚠ Matched at COLUMN ZERO. A YAML block scalar strips the block's own indentation, so
    the shell here is flush-left once parsed, not indented as it appears in the file. The
    first version of this helper searched for an 8-space `else` and silently found none,
    which made every test in this module error instead of measure —
    `test_the_guarded_block_actually_gates_rules` is what caught it.

    Column zero also disambiguates: the `advisory()` shell function above has its own
    `else`, nested and therefore indented.
    """
    script = _script()
    start = script.index('if [ -n "${WORKFLOWS_DIR:-}" ]')
    else_match = re.compile(r"^else$", re.M).search(script, start)
    assert else_match, "no column-zero `else` after the workflows-dir guard"
    fi_match = re.compile(r"^fi$", re.M).search(script, else_match.end())
    assert fi_match, "no column-zero `fi` closing the workflows-dir guard"
    return script[start : else_match.start()], script[else_match.end() : fi_match.start()]


def _gated_rules() -> set[str]:
    """What the guarded block ACTUALLY runs — the ground truth."""
    return set(RULE.findall(_guarded_block()[0]))


def _declared(array: str) -> set[str]:
    """Names in a `NAME=( ... )` bash array in the script."""
    script = _script()
    match = re.search(rf"^{array}=\(([^)]*)\)", script, re.M)
    return set(RULE.findall(match.group(1))) if match else set()


def _announced_rules() -> set[str]:
    return _declared("DIR_SCOPED_ENFORCING") | _declared("DIR_SCOPED_ADVISORY")


def test_the_guarded_block_actually_gates_rules():
    """★ CONTROL on the parser. If this ever reads an empty set, every test below
    passes vacuously and this module measures nothing."""
    assert len(_gated_rules()) >= 5, _gated_rules()


def test_every_gated_rule_is_named_in_the_announcement():
    missing = _gated_rules() - _announced_rules()
    assert not missing, (
        f"{len(missing)} rule(s) are skipped without being named: {sorted(missing)}. "
        "A consumer cannot act on a rule it is not told was skipped."
    )


def test_the_announcement_does_not_name_rules_it_did_not_skip():
    """The mirror. Over-claiming is the same defect pointed the other way."""
    extra = _announced_rules() - _gated_rules()
    assert not extra, f"announced but not actually gated: {sorted(extra)}"


def test_the_announcement_is_generated_from_the_lists_not_retyped():
    """⛔ THE ACTUAL FIX. The old notice was a hand-typed sentence naming two rules while
    ten were gated; it rotted because a human had to remember it. A count or a name list
    written out by hand in the `else` is the same defect waiting to recur, so the
    announcement must be BUILT from the same arrays the runner uses."""
    body = _guarded_block()[1]
    assert "DIR_SCOPED_ENFORCING" in body and "DIR_SCOPED_ADVISORY" in body, (
        "the announcement must expand the rule arrays rather than restate them"
    )
    assert not RULE.findall(body), (
        f"rule names are hard-coded in the announcement: {RULE.findall(body)}. "
        "Expand the arrays instead — a retyped list is what drifted."
    )


def test_no_stated_count_is_hard_coded():
    """A wrong number is worse than no number — it reads as a measurement. '2
    repo-scoped rules' was literally true once and wrong eight rules later."""
    body = _guarded_block()[1]
    hard_coded = re.findall(r"\b(\d+)\s+(?:repo-scoped\s+)?rules?\b", body)
    assert not hard_coded, f"hard-coded rule count(s) in the announcement: {hard_coded}"


def test_the_announcement_is_at_least_a_warning_because_enforcing_rules_are_skipped():
    """⛔ `::notice` is the quietest annotation GitHub has — it does not surface in the
    checks UI the way a warning does. Three of the gated rules FAIL THE BUILD when they
    run, so their absence is the difference between a green job that judged the repo and
    a green job that did not."""
    body = _guarded_block()[1]
    assert "::warning" in body or "::error" in body, (
        "skipping enforcing rules must be announced at warning severity or higher; "
        f"found only: {body.strip()[:200]}"
    )


def test_the_enforcing_rules_are_identified_as_enforcing_in_the_announcement():
    """Naming ten rules flatly hides that three of them are build-failing. The consumer
    needs to know which absences changed the meaning of their green tick."""
    body = _guarded_block()[1]
    assert re.search(r"enforc", body, re.I), (
        "the announcement must say that some of the skipped rules are enforcing"
    )


def test_the_enforcing_list_matches_the_rules_that_actually_fail_the_build():
    """★ The severity split must be measured, not asserted. A rule invoked with
    `|| rc=1` fails the consumer's build; one passed to `advisory` does not."""
    ran = _guarded_block()[0]
    truly_enforcing = {
        m.group(1)
        for m in re.finditer(r"python3 \"\$ROOT/(check_[a-z_]+\.py)\".*?\|\| rc=1", ran)
    }
    assert _declared("DIR_SCOPED_ENFORCING") == truly_enforcing, (
        f"declared enforcing {sorted(_declared('DIR_SCOPED_ENFORCING'))} != "
        f"actually build-failing {sorted(truly_enforcing)}"
    )


# ── The same contract, for the WORKFLOW-scoped half ──────────────────────────────────
#
# ⛔ ADDED because `workflow` became optional. The dir-scoped announcement above exists
# because a hand-maintained list of a set defined ten lines away rots — it was right when
# written and wrong eight rules later. Introducing a SECOND skip path without the same
# pins would reproduce that defect exactly, in a file whose docstring describes it.
#
# These mirror the dir-scoped tests one for one: whatever the `if` runs, the `else` must
# name, generated from the arrays and never retyped.


def _workflow_guarded_block() -> tuple[str, str]:
    """Body of `if [ -n "$WORKFLOW" ]` and of its `else`. Column-zero, as above."""
    script = _script()
    start = script.index('if [ -n "${WORKFLOW:-}" ]')
    else_match = re.compile(r"^else$", re.M).search(script, start)
    assert else_match, "no column-zero `else` after the workflow guard"
    fi_match = re.compile(r"^fi$", re.M).search(script, else_match.end())
    assert fi_match, "no column-zero `fi` closing the workflow guard"
    return script[start:else_match.start()], script[else_match.end():fi_match.start()]


def _wf_declared() -> set[str]:
    return _declared("WORKFLOW_SCOPED_ENFORCING") | _declared("WORKFLOW_SCOPED_ADVISORY")


def test_the_workflow_guard_actually_gates_rules():
    body, _ = _workflow_guarded_block()
    assert RULE.findall(body), "the workflow guard gates no rules — the helper is matching the wrong block"


def test_every_workflow_gated_rule_is_named_in_the_announcement():
    body, _ = _workflow_guarded_block()
    run = set(RULE.findall(body))
    assert run == _wf_declared(), (
        f"the workflow guard runs {sorted(run)} but the arrays declare "
        f"{sorted(_wf_declared())} — a rule was added to one and not the other, so the "
        "skip warning undercounts and a consumer is told less than was skipped"
    )


def test_the_workflow_announcement_is_generated_not_retyped():
    _, else_body = _workflow_guarded_block()
    assert "WORKFLOW_SCOPED_ENFORCING" in else_body and "WORKFLOW_SCOPED_ADVISORY" in else_body, (
        "the workflow skip warning does not expand the arrays — a hand-typed list is the "
        "exact defect this module exists to prevent"
    )
    assert not RULE.findall(else_body), (
        f"the workflow skip warning names rules by hand ({RULE.findall(else_body)}); it "
        "must expand the arrays so it cannot drift"
    )


def test_no_workflow_count_is_hard_coded():
    _, else_body = _workflow_guarded_block()
    for n in re.findall(r"\b\d+\b", else_body):
        assert False, f"hard-coded count {n} in the workflow skip warning — use ${{#ARRAY[@]}}"


def test_the_workflow_announcement_is_at_least_a_warning():
    _, else_body = _workflow_guarded_block()
    assert "::warning" in else_body or "::error" in else_body, (
        "ENFORCING rules are skipped here; ::notice does not surface in the checks UI, "
        "which is how the dir-scoped undercount stayed invisible"
    )


def test_the_workflow_enforcing_list_matches_what_actually_fails_the_build():
    body, _ = _workflow_guarded_block()
    truly_enforcing = {
        m for line in body.splitlines() if "|| rc=1" in line for m in RULE.findall(line)
    }
    assert _declared("WORKFLOW_SCOPED_ENFORCING") == truly_enforcing, (
        f"declared enforcing {sorted(_declared('WORKFLOW_SCOPED_ENFORCING'))} != "
        f"rules that actually fail the build {sorted(truly_enforcing)} — the warning would "
        "misstate which skipped rules would have failed this build"
    )
